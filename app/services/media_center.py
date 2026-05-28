from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from app.core.config import settings
from app.domains.inventory.models import MediaPlayer
from app.domains.media_center.models import MediaAsset, MediaAssignment, MediaClientHeartbeat
from app.domains.media_center.schemas import (
    MediaAssignmentCreate,
    MediaAssignmentUpdate,
    MediaClientHeartbeatPayload,
    MediaClientManifest,
)


class MediaPlayerMissingError(LookupError):
    pass


class MediaAssetMissingError(LookupError):
    pass


class MediaAssetUploadError(ValueError):
    pass


_ALLOWED_MEDIA_EXTENSIONS = {
    ".aac",
    ".avi",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ogg",
    ".wav",
    ".webm",
}
_AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}
_VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}


def get_media_player_or_raise(session: Session, player_id: uuid.UUID) -> MediaPlayer:
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise MediaPlayerMissingError("Media player not found")
    return player


def get_assignment(session: Session, player_id: uuid.UUID) -> MediaAssignment | None:
    return session.exec(select(MediaAssignment).where(MediaAssignment.player_id == player_id)).first()


def list_assets(session: Session) -> list[MediaAsset]:
    return session.exec(
        select(MediaAsset).where(MediaAsset.is_active == True).order_by(MediaAsset.created_at.desc())  # noqa: E712
    ).all()


def get_asset_or_raise(session: Session, asset_id: uuid.UUID) -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if not asset or not asset.is_active:
        raise MediaAssetMissingError("Media asset not found")
    return asset


def media_library_dir() -> Path:
    path = Path(settings.MEDIA_LIBRARY_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_asset_path(asset: MediaAsset) -> Path:
    if not asset.stored_filename:
        raise MediaAssetMissingError("Media asset file is missing")
    path = media_library_dir() / asset.stored_filename
    if not path.exists() or not path.is_file():
        raise MediaAssetMissingError("Media asset file is missing")
    return path


def _infer_media_type(extension: str, content_type: str | None) -> str:
    if extension in _AUDIO_EXTENSIONS or (content_type or "").startswith("audio/"):
        return "audio"
    if extension in _VIDEO_EXTENSIONS or (content_type or "").startswith("video/"):
        return "video"
    return "stream"


def _safe_title(filename: str) -> str:
    title = Path(filename).stem.strip() or "Media file"
    return title[:255]


def create_uploaded_asset(session: Session, *, upload_file, title: str | None = None) -> MediaAsset:
    original_filename = Path(upload_file.filename or "media").name
    extension = Path(original_filename).suffix.lower()
    if extension not in _ALLOWED_MEDIA_EXTENSIONS:
        raise MediaAssetUploadError("Unsupported media file type")

    asset_id = uuid.uuid4()
    stored_filename = f"{asset_id}{extension}"
    destination = media_library_dir() / stored_filename
    max_bytes = max(1, settings.MEDIA_LIBRARY_MAX_UPLOAD_MB) * 1024 * 1024

    size = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise MediaAssetUploadError("Media file is too large")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    media_type = _infer_media_type(extension, upload_file.content_type)
    asset = MediaAsset(
        id=asset_id,
        title=(title or _safe_title(original_filename)).strip()[:255],
        media_type=media_type,
        source_url=f"/assets/{asset_id}/file",
        original_filename=original_filename,
        stored_filename=stored_filename,
        content_type=upload_file.content_type,
        file_size_bytes=size,
        is_active=True,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def get_client_heartbeat(session: Session, player_id: uuid.UUID) -> MediaClientHeartbeat | None:
    return session.exec(select(MediaClientHeartbeat).where(MediaClientHeartbeat.player_id == player_id)).first()


def upsert_assignment(
    session: Session,
    *,
    player_id: uuid.UUID,
    payload: MediaAssignmentCreate | MediaAssignmentUpdate,
) -> MediaAssignment:
    get_media_player_or_raise(session, player_id)
    row = get_assignment(session, player_id)
    now = datetime.now(UTC)
    data = payload.model_dump(exclude_unset=True)

    if row is None:
        row = MediaAssignment(player_id=player_id, **data)
    else:
        row.sqlmodel_update(data)
        row.revision += 1
        row.updated_at = now

    if not row.updated_at:
        row.updated_at = now
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def build_client_manifest(session: Session, player_id: uuid.UUID) -> MediaClientManifest:
    get_media_player_or_raise(session, player_id)
    assignment = get_assignment(session, player_id)
    if not assignment or not assignment.enabled:
        return MediaClientManifest(device_id=str(player_id), revision=0, enabled=False)

    return MediaClientManifest(
        device_id=str(player_id),
        revision=assignment.revision,
        enabled=assignment.enabled,
        title=assignment.title,
        media_type=assignment.media_type,
        source_url=assignment.source_url,
        playback_mode=assignment.playback_mode,
        volume=assignment.volume,
    )


def record_client_heartbeat(
    session: Session,
    player_id: uuid.UUID,
    payload: MediaClientHeartbeatPayload,
) -> MediaClientHeartbeat:
    get_media_player_or_raise(session, player_id)
    now = datetime.now(UTC)
    data = payload.model_dump()
    values = {
        **data,
        "id": uuid.uuid4(),
        "player_id": player_id,
        "last_seen_at": now,
        "created_at": now,
        "updated_at": now,
    }
    update_values = {
        **data,
        "last_seen_at": now,
        "updated_at": now,
    }
    dialect_name = session.get_bind().dialect.name
    insert_factory = sqlite_insert if dialect_name == "sqlite" else postgresql_insert
    stmt = insert_factory(MediaClientHeartbeat).values(**values).on_conflict_do_update(
        index_elements=[MediaClientHeartbeat.player_id],
        set_=update_values,
    )
    session.exec(stmt)
    session.commit()
    row = get_client_heartbeat(session, player_id)
    if row is None:
        raise RuntimeError("Media client heartbeat was not persisted")
    session.refresh(row)
    return row

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.domains.inventory.media_polling import (
    MediaPlayerNotFoundError,
    invalidate_media_player_cache,
    poll_all_media_players_local,
    poll_single_media_player_local,
    rediscover_media_players_local,
)
from app.domains.inventory.models import MediaPlayer
from app.domains.inventory.schemas import (
    DiscoveryResults,
    MediaPlayerCreate,
    MediaPlayerPublic,
    MediaPlayersPublic,
    MediaPlayerUpdate,
    ScanProgress,
    ScanRequest,
)
from app.domains.shared.schemas import Message
from app.observability.metrics import (
    media_player_ops_total,
)
from app.services.cache import get_cached_model, set_cached_model
from app.services.discovery import get_discovery_progress, get_discovery_results, run_discovery_scan
from app.services.event_log import write_event_log
from app.services.iconbit import (
    delete_all_files as iconbit_delete_all,
)
from app.services.iconbit import (
    delete_file as iconbit_delete_file,
)
from app.services.iconbit import (
    get_status as iconbit_get_status,
)
from app.services.iconbit import (
    play as iconbit_play,
)
from app.services.iconbit import (
    play_file as iconbit_play_file,
)
from app.services.iconbit import (
    stop as iconbit_stop,
)
from app.services.iconbit import (
    upload_file as iconbit_upload_file,
)
from app.services.internal_services import _proxy_request
from app.services.mac_lookup import resolve_mac_for_ip_address
from app.services.smart_search import build_ilike_filter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media-players"])

CACHE_TTL = 30


async def _run_iconbit_discovery(subnet: str, ports: str, known_players: list[dict]) -> None:
    try:
        await run_discovery_scan("iconbit", subnet, ports, known_players)
    except Exception as exc:
        logger.error("Iconbit discovery failed: %s", exc)


async def _invalidate_cache() -> None:
    await invalidate_media_player_cache()


@router.get("/", response_model=MediaPlayersPublic)
async def read_media_players(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, le=500),
    name: str | None = None,
    device_type: str | None = None,
) -> MediaPlayersPublic:
    cache_key = f"media_players:{device_type or ''}:{name or ''}:{skip}:{limit}"
    if cached := await get_cached_model(cache_key, MediaPlayersPublic):
        return cached

    statement = select(MediaPlayer)
    count_stmt = select(func.count()).select_from(MediaPlayer)

    if device_type:
        statement = statement.where(MediaPlayer.device_type == device_type)
        count_stmt = count_stmt.where(MediaPlayer.device_type == device_type)
    if name:
        flt = build_ilike_filter(
            [
                MediaPlayer.name,
                MediaPlayer.hostname,
                MediaPlayer.ip_address,
                MediaPlayer.model,
                MediaPlayer.mac_address,
                MediaPlayer.os_info,
            ],
            name,
        )
        if flt is not None:
            statement = statement.where(flt)
            count_stmt = count_stmt.where(flt)

    count = session.exec(count_stmt).one()
    players = session.exec(statement.offset(skip).limit(limit).order_by(MediaPlayer.name)).all()
    result = MediaPlayersPublic(data=players, count=count)

    await set_cached_model(cache_key, result, ttl=CACHE_TTL)

    return result


@router.post("/", response_model=MediaPlayerPublic, dependencies=[Depends(get_current_active_superuser)])
async def create_media_player(session: SessionDep, player_in: MediaPlayerCreate) -> MediaPlayer:
    existing = session.exec(select(MediaPlayer).where(MediaPlayer.ip_address == player_in.ip_address)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Device with this IP already exists")
    player = MediaPlayer(**player_in.model_dump())
    if not player.mac_address:
        player.mac_address = await resolve_mac_for_ip_address(player.ip_address, prefer_snmp=player.device_type != "iconbit")
    session.add(player)
    session.commit()
    session.refresh(player)
    await _invalidate_cache()
    return player


@router.post("/discover/scan", response_model=ScanProgress, dependencies=[Depends(get_current_active_superuser)])
async def discover_iconbit_scan(
    body: ScanRequest,
    session: SessionDep,
) -> dict:
    players = session.exec(select(MediaPlayer).where(MediaPlayer.device_type == "iconbit")).all()
    known = [{"id": str(p.id), "ip_address": p.ip_address, "mac_address": p.mac_address} for p in players]
    if settings.DISCOVERY_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="POST",
            path="/discover/iconbit/scan",
            json_body={
                "subnet": body.subnet,
                "ports": body.ports,
                "known_devices": known,
            },
        )
    asyncio.create_task(_run_iconbit_discovery(body.subnet, body.ports, known))
    return {"status": "running", "scanned": 0, "total": 0, "found": 0, "message": None}


@router.get("/discover/status", response_model=ScanProgress)
async def discover_iconbit_status(current_user: CurrentUser) -> dict:
    del current_user
    if settings.DISCOVERY_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="GET",
            path="/discover/iconbit/status",
        )
    return await get_discovery_progress("iconbit")


@router.get("/discover/results", response_model=DiscoveryResults)
async def discover_iconbit_results(current_user: CurrentUser) -> dict:
    del current_user
    if settings.DISCOVERY_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="GET",
            path="/discover/iconbit/results",
        )
        return DiscoveryResults.model_validate(payload).model_dump()
    progress = await get_discovery_progress("iconbit")
    devices = await get_discovery_results("iconbit")
    return {"progress": progress, "devices": devices}


@router.post("/discover/add", response_model=MediaPlayerPublic, dependencies=[Depends(get_current_active_superuser)])
async def discover_add_iconbit(
    session: SessionDep,
    payload: dict,
) -> MediaPlayer:
    ip = str(payload.get("ip_address", "")).strip()
    if not ip:
        raise HTTPException(status_code=422, detail="ip_address is required")
    existing = session.exec(select(MediaPlayer).where(MediaPlayer.ip_address == ip)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Device with this IP already exists")
    name = str(payload.get("name") or f"Iconbit {ip}")
    model = str(payload.get("model") or "Iconbit")
    player = MediaPlayer(
        device_type="iconbit",
        name=name[:255],
        model=model[:255],
        ip_address=ip,
        mac_address=str(payload.get("mac_address") or "")[:17] or None,
    )
    if not player.mac_address:
        player.mac_address = await resolve_mac_for_ip_address(ip, prefer_snmp=False)
    session.add(player)
    session.commit()
    session.refresh(player)
    await _invalidate_cache()
    return player


@router.post(
    "/discover/update-ip/{player_id}",
    response_model=MediaPlayerPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
async def discover_update_iconbit_ip(
    player_id: uuid.UUID,
    session: SessionDep,
    new_ip: str = "",
    new_mac: str | None = None,
) -> MediaPlayer:
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    old_ip = player.ip_address
    if new_ip:
        conflict = session.exec(
            select(MediaPlayer).where(MediaPlayer.ip_address == new_ip, MediaPlayer.id != player.id)
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Another device already has this IP")
        player.ip_address = new_ip
        if old_ip != new_ip:
            write_event_log(
                session,
                category="network",
                event_type="ip_changed",
                severity="warning",
                device_kind="media_player",
                device_name=player.name,
                ip_address=new_ip,
                message=f"Media player '{player.name}' moved IP: {old_ip} -> {new_ip}",
            )
    if new_mac:
        player.mac_address = new_mac
    elif new_ip:
        resolved_mac = await resolve_mac_for_ip_address(new_ip, prefer_snmp=player.device_type != "iconbit")
        if resolved_mac:
            player.mac_address = resolved_mac
    player.updated_at = datetime.now(UTC)
    session.add(player)
    session.commit()
    session.refresh(player)
    await _invalidate_cache()
    return player


@router.get("/{player_id}", response_model=MediaPlayerPublic)
def read_media_player(player_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> MediaPlayer:
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    return player


@router.patch("/{player_id}", response_model=MediaPlayerPublic, dependencies=[Depends(get_current_active_superuser)])
async def update_media_player(session: SessionDep, player_id: uuid.UUID, player_in: MediaPlayerUpdate) -> MediaPlayer:
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    update_data = player_in.model_dump(exclude_unset=True)
    if "ip_address" in update_data and update_data["ip_address"] is not None:
        existing = session.exec(
            select(MediaPlayer).where(
                MediaPlayer.ip_address == update_data["ip_address"],
                MediaPlayer.id != player_id,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Device with this IP already exists")
    player.updated_at = datetime.now(UTC)
    ip_changed = "ip_address" in update_data and update_data.get("ip_address") != player.ip_address
    explicit_mac = "mac_address" in update_data
    player.sqlmodel_update(update_data)
    if ip_changed and not explicit_mac:
        resolved_mac = await resolve_mac_for_ip_address(
            player.ip_address,
            prefer_snmp=player.device_type != "iconbit",
        )
        if resolved_mac:
            player.mac_address = resolved_mac
    session.add(player)
    session.commit()
    session.refresh(player)
    await _invalidate_cache()
    return player


@router.delete("/{player_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_media_player(session: SessionDep, player_id: uuid.UUID) -> Message:
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    session.delete(player)
    session.commit()
    await _invalidate_cache()
    return Message(message="Media player deleted")


# -- Polling ---------------------------------------------------------------


@router.post("/{player_id}/poll", response_model=MediaPlayerPublic)
async def poll_single_player(player_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> MediaPlayer:
    del current_user
    try:
        return await poll_single_media_player_local(session=session, player_id=player_id)
    except MediaPlayerNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Media player not found") from exc


@router.post("/poll-all", response_model=MediaPlayersPublic)
async def poll_all_players(
    session: SessionDep,
    current_user: CurrentUser,
    device_type: str | None = Query(default=None),
) -> MediaPlayersPublic:
    del current_user
    if settings.POLLING_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.POLLING_SERVICE_URL,
            method="POST",
            path="/poll/media-players",
            params={"device_type": device_type} if device_type else None,
        )
        return MediaPlayersPublic.model_validate(payload)

    return await poll_all_media_players_local(session=session, device_type=device_type)


# -- Rediscovery -----------------------------------------------------------


@router.post("/rediscover", response_model=MediaPlayersPublic)
async def rediscover_devices(
    session: SessionDep,
    current_user: CurrentUser,
) -> MediaPlayersPublic:
    del current_user
    return await rediscover_media_players_local(session=session)


# ── Iconbit control ──────────────────────────────────────────────


@router.get("/{player_id}/iconbit/status")
async def iconbit_status(player_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> dict:
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="GET",
            path=f"/iconbit/{player_id}/status",
        )
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    if player.device_type != "iconbit":
        raise HTTPException(status_code=400, detail="Not an Iconbit device")
    result = await asyncio.to_thread(iconbit_get_status, player.ip_address)
    media_player_ops_total.labels(operation="iconbit_status", result="success").inc()
    return {
        "now_playing": result.now_playing,
        "is_playing": result.is_playing,
        "state": result.state,
        "position": result.position,
        "duration": result.duration,
        "files": result.files,
        "free_space": result.free_space,
    }


@router.post("/{player_id}/iconbit/play")
async def iconbit_play_action(player_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> dict:
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path=f"/iconbit/{player_id}/play",
        )
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    if player.device_type != "iconbit":
        raise HTTPException(status_code=400, detail="Not an Iconbit device")
    ok = await asyncio.to_thread(iconbit_play, player.ip_address)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_play", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to start playback")
    media_player_ops_total.labels(operation="iconbit_play", result="success").inc()
    return {"status": "playing"}


@router.post("/{player_id}/iconbit/stop")
async def iconbit_stop_action(player_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> dict:
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path=f"/iconbit/{player_id}/stop",
        )
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    if player.device_type != "iconbit":
        raise HTTPException(status_code=400, detail="Not an Iconbit device")
    ok = await asyncio.to_thread(iconbit_stop, player.ip_address)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_stop", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to stop playback")
    media_player_ops_total.labels(operation="iconbit_stop", result="success").inc()
    return {"status": "stopped"}


@router.post("/{player_id}/iconbit/play-file")
async def iconbit_play_file_action(
    player_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    filename: str = Body(embed=True),
) -> dict:
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path=f"/iconbit/{player_id}/play-file",
            json_body={"filename": filename},
        )
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    if player.device_type != "iconbit":
        raise HTTPException(status_code=400, detail="Not an Iconbit device")
    ok = await asyncio.to_thread(iconbit_play_file, player.ip_address, filename)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_play_file", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to play file")
    media_player_ops_total.labels(operation="iconbit_play_file", result="success").inc()
    return {"status": "playing", "file": filename}


@router.post("/{player_id}/iconbit/delete-file")
async def iconbit_delete_file_action(
    player_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    filename: str = Body(embed=True),
) -> dict:
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path=f"/iconbit/{player_id}/delete-file",
            json_body={"filename": filename},
        )
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    if player.device_type != "iconbit":
        raise HTTPException(status_code=400, detail="Not an Iconbit device")
    ok = await asyncio.to_thread(iconbit_delete_file, player.ip_address, filename)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_delete_file", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to delete file")
    media_player_ops_total.labels(operation="iconbit_delete_file", result="success").inc()
    return {"status": "deleted", "file": filename}


@router.post("/{player_id}/iconbit/upload")
async def iconbit_upload_action(
    player_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    file: UploadFile = ...,
) -> dict:
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        content = await file.read()
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path=f"/iconbit/{player_id}/upload",
            files={"file": (file.filename or "upload.mp3", content, file.content_type or "application/octet-stream")},
        )
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    if player.device_type != "iconbit":
        raise HTTPException(status_code=400, detail="Not an Iconbit device")
    content = await file.read()
    ok = await asyncio.to_thread(iconbit_upload_file, player.ip_address, file.filename or "upload.mp3", content)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_upload", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to upload file")
    media_player_ops_total.labels(operation="iconbit_upload", result="success").inc()
    return {"status": "uploaded", "file": file.filename}


# ── Bulk Iconbit operations ─────────────────────────────────────


def _get_all_iconbits(session) -> list[MediaPlayer]:
    return list(session.exec(select(MediaPlayer).where(MediaPlayer.device_type == "iconbit")).all())


@router.post("/iconbit/bulk-play")
async def iconbit_bulk_play(session: SessionDep, current_user: CurrentUser) -> dict:
    """Start playback on all Iconbit devices."""
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path="/iconbit/bulk-play",
        )
    players = _get_all_iconbits(session)
    if not players:
        return {"success": 0, "failed": 0}

    results = []
    for p in players:
        ok = await asyncio.to_thread(iconbit_play, p.ip_address)
        results.append(ok)
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_play", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_play", result="error").inc(failed)
    return {"success": success, "failed": failed}


@router.post("/iconbit/bulk-stop")
async def iconbit_bulk_stop(session: SessionDep, current_user: CurrentUser) -> dict:
    """Stop playback on all Iconbit devices."""
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path="/iconbit/bulk-stop",
        )
    players = _get_all_iconbits(session)
    if not players:
        return {"success": 0, "failed": 0}

    results = []
    for p in players:
        ok = await asyncio.to_thread(iconbit_stop, p.ip_address)
        results.append(ok)
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_stop", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_stop", result="error").inc(failed)
    return {"success": success, "failed": failed}


@router.post("/iconbit/bulk-upload")
async def iconbit_bulk_upload(
    session: SessionDep,
    current_user: CurrentUser,
    file: UploadFile = ...,
) -> dict:
    """Upload a media file to all Iconbit devices."""
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        content = await file.read()
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path="/iconbit/bulk-upload",
            files={"file": (file.filename or "upload.mp3", content, file.content_type or "application/octet-stream")},
        )
    players = _get_all_iconbits(session)
    if not players:
        return {"success": 0, "failed": 0}

    content = await file.read()
    fname = file.filename or "upload.mp3"
    results = []
    for p in players:
        ok = await asyncio.to_thread(iconbit_upload_file, p.ip_address, fname, content)
        results.append(ok)
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_upload", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_upload", result="error").inc(failed)
    return {"success": success, "failed": failed, "file": fname}


@router.post("/iconbit/bulk-delete-file")
async def iconbit_bulk_delete(
    session: SessionDep,
    current_user: CurrentUser,
    filename: str = Body(embed=True),
) -> dict:
    """Delete a file from all Iconbit devices."""
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path="/iconbit/bulk-delete-file",
            json_body={"filename": filename},
        )
    players = _get_all_iconbits(session)
    if not players:
        return {"success": 0, "failed": 0}

    results = []
    for p in players:
        ok = await asyncio.to_thread(iconbit_delete_file, p.ip_address, filename)
        results.append(ok)
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_delete", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_delete", result="error").inc(failed)
    return {"success": success, "failed": failed, "file": filename}


@router.post("/iconbit/bulk-play-file")
async def iconbit_bulk_play_file(
    session: SessionDep,
    current_user: CurrentUser,
    filename: str = Body(embed=True),
) -> dict:
    """Play a specific file on all Iconbit devices."""
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path="/iconbit/bulk-play-file",
            json_body={"filename": filename},
        )
    players = _get_all_iconbits(session)
    if not players:
        return {"success": 0, "failed": 0}

    results = []
    for p in players:
        ok = await asyncio.to_thread(iconbit_play_file, p.ip_address, filename)
        results.append(ok)
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_play_file", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_play_file", result="error").inc(failed)
    return {"success": success, "failed": failed, "file": filename}


@router.post("/iconbit/bulk-replace")
async def iconbit_bulk_replace(
    session: SessionDep,
    current_user: CurrentUser,
    file: UploadFile = ...,
) -> dict:
    """Replace playlist on all Iconbit: delete old files, upload new, start playback."""
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        content = await file.read()
        return await _proxy_request(
            base_url=settings.NETWORK_CONTROL_SERVICE_URL,
            method="POST",
            path="/iconbit/bulk-replace",
            files={"file": (file.filename or "upload.mp3", content, file.content_type or "application/octet-stream")},
        )
    players = _get_all_iconbits(session)
    if not players:
        return {"success": 0, "failed": 0}

    content = await file.read()
    fname = file.filename or "upload.mp3"
    success = 0
    failed = 0
    for p in players:
        try:
            await asyncio.to_thread(iconbit_delete_all, p.ip_address)
            uploaded = await asyncio.to_thread(iconbit_upload_file, p.ip_address, fname, content)
            if uploaded:
                await asyncio.to_thread(iconbit_play, p.ip_address)
                success += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    media_player_ops_total.labels(operation="iconbit_bulk_replace", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_replace", result="error").inc(failed)
    return {"success": success, "failed": failed, "file": fname}

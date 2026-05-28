from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.domains.media_center.models import MediaAsset, MediaAssignment, MediaClientHeartbeat
from app.domains.media_center.schemas import (
    MediaAssetPublic,
    MediaAssetsPublic,
    MediaAssignmentCreate,
    MediaAssignmentPublic,
    MediaAssignmentsPublic,
    MediaAssignmentUpdate,
    MediaClientHeartbeatPublic,
    MediaClientHeartbeatsPublic,
    MediaClientManifest,
)
from app.services.media_center import (
    MediaAssetMissingError,
    MediaAssetUploadError,
    MediaPlayerMissingError,
    build_client_manifest,
    create_uploaded_asset,
    get_asset_or_raise,
    get_assignment,
    get_client_heartbeat,
    list_assets,
    media_asset_path,
    upsert_assignment,
)

router = APIRouter(tags=["media-center"])


@router.get("/assignments", response_model=MediaAssignmentsPublic)
def list_assignments(session: SessionDep, current_user: CurrentUser) -> MediaAssignmentsPublic:
    del current_user
    rows = session.exec(select(MediaAssignment).order_by(MediaAssignment.updated_at.desc())).all()
    return MediaAssignmentsPublic(data=rows, count=len(rows))


@router.get("/assets", response_model=MediaAssetsPublic)
def read_assets(session: SessionDep, current_user: CurrentUser) -> MediaAssetsPublic:
    del current_user
    rows = list_assets(session)
    return MediaAssetsPublic(data=rows, count=len(rows))


@router.post(
    "/assets",
    response_model=MediaAssetPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def upload_asset(
    session: SessionDep,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> MediaAsset:
    try:
        return create_uploaded_asset(session, upload_file=file, title=title)
    except MediaAssetUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/file")
def read_asset_file(asset_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> FileResponse:
    del current_user
    try:
        asset = get_asset_or_raise(session, asset_id)
        path = media_asset_path(asset)
    except MediaAssetMissingError as exc:
        raise HTTPException(status_code=404, detail="Media asset not found") from exc
    return FileResponse(
        path,
        media_type=asset.content_type or "application/octet-stream",
        filename=asset.original_filename or path.name,
    )


@router.get("/heartbeats", response_model=MediaClientHeartbeatsPublic)
def list_client_heartbeats(session: SessionDep, current_user: CurrentUser) -> MediaClientHeartbeatsPublic:
    del current_user
    rows = session.exec(select(MediaClientHeartbeat).order_by(MediaClientHeartbeat.last_seen_at.desc())).all()
    return MediaClientHeartbeatsPublic(data=rows, count=len(rows))


@router.get("/heartbeats/{player_id}", response_model=MediaClientHeartbeatPublic)
def read_client_heartbeat(player_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> MediaClientHeartbeat:
    del current_user
    row = get_client_heartbeat(session, player_id)
    if not row:
        raise HTTPException(status_code=404, detail="Media client heartbeat not found")
    return row


@router.get("/assignments/{player_id}", response_model=MediaAssignmentPublic)
def read_assignment(player_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> MediaAssignment:
    del current_user
    row = get_assignment(session, player_id)
    if not row:
        raise HTTPException(status_code=404, detail="Media assignment not found")
    return row


@router.put(
    "/assignments/{player_id}",
    response_model=MediaAssignmentPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def set_assignment(player_id: uuid.UUID, payload: MediaAssignmentCreate, session: SessionDep) -> MediaAssignment:
    try:
        return upsert_assignment(session, player_id=player_id, payload=payload)
    except MediaPlayerMissingError as exc:
        raise HTTPException(status_code=404, detail="Media player not found") from exc


@router.patch(
    "/assignments/{player_id}",
    response_model=MediaAssignmentPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def update_assignment(player_id: uuid.UUID, payload: MediaAssignmentUpdate, session: SessionDep) -> MediaAssignment:
    if not get_assignment(session, player_id):
        raise HTTPException(status_code=404, detail="Media assignment not found")
    try:
        return upsert_assignment(session, player_id=player_id, payload=payload)
    except MediaPlayerMissingError as exc:
        raise HTTPException(status_code=404, detail="Media player not found") from exc


@router.get("/manifest/{player_id}", response_model=MediaClientManifest)
def read_manifest(player_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> MediaClientManifest:
    del current_user
    try:
        return build_client_manifest(session, player_id)
    except MediaPlayerMissingError as exc:
        raise HTTPException(status_code=404, detail="Media player not found") from exc

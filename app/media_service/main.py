from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.readiness import build_readiness_response, check_database, check_redis
from app.core.redis import close_redis, get_redis
from app.domains.media_center.schemas import (
    MediaClientHeartbeatPayload,
    MediaClientHeartbeatPublic,
    MediaClientManifest,
)
from app.observability.tracing import setup_tracing
from app.services.media_center import (
    MediaAssetMissingError,
    MediaPlayerMissingError,
    build_client_manifest,
    get_asset_or_raise,
    media_asset_path,
    record_client_heartbeat,
)


def _verify_media_client_token(x_media_client_token: str | None = Header(default=None)) -> None:
    if not settings.MEDIA_CLIENT_TOKEN:
        return
    if x_media_client_token != settings.MEDIA_CLIENT_TOKEN:
        raise HTTPException(status_code=401, detail="invalid media client token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(title="InfraScope Media Service", lifespan=lifespan)
setup_tracing(app, service_name="media-service")
Instrumentator(excluded_handlers=["/metrics", "/health"]).instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict | object:
    checks = {
        "database": check_database(engine),
        "redis": await check_redis(get_redis),
    }
    return build_readiness_response(checks)


@app.get(
    "/clients/{player_id}/manifest",
    response_model=MediaClientManifest,
    dependencies=[Depends(_verify_media_client_token)],
)
def client_manifest(player_id: uuid.UUID) -> MediaClientManifest:
    with Session(engine) as session:
        try:
            return build_client_manifest(session, player_id)
        except MediaPlayerMissingError as exc:
            raise HTTPException(status_code=404, detail="Media player not found") from exc


@app.get("/assets/{asset_id}/file")
def asset_file(asset_id: uuid.UUID) -> FileResponse:
    with Session(engine) as session:
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


@app.post(
    "/clients/{player_id}/heartbeat",
    response_model=MediaClientHeartbeatPublic,
    dependencies=[Depends(_verify_media_client_token)],
)
def client_heartbeat(player_id: uuid.UUID, payload: MediaClientHeartbeatPayload) -> MediaClientHeartbeatPublic:
    with Session(engine) as session:
        try:
            return record_client_heartbeat(session, player_id, payload)
        except MediaPlayerMissingError as exc:
            raise HTTPException(status_code=404, detail="Media player not found") from exc

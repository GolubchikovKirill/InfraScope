from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, Header, HTTPException, UploadFile
from prometheus_fastapi_instrumentator import Instrumentator
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.readiness import build_readiness_response, check_database, check_redis
from app.core.redis import close_redis, get_redis
from app.domains.inventory.models import MediaPlayer, NetworkSwitch
from app.domains.shared.schemas import Message
from app.observability.metrics import (
    media_player_ops_total,
    switch_ops_total,
    switch_port_op_duration_seconds,
    switch_port_ops_total,
)
from app.observability.tracing import setup_tracing
from app.services.cisco_ssh import poe_cycle_ap, reboot_ap
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
from app.services.switches import resolve_switch_provider


def _verify_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not settings.INTERNAL_SERVICE_TOKEN:
        return
    if x_internal_token != settings.INTERNAL_SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="invalid internal token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(title="InfraScope Network Control Service", lifespan=lifespan)
setup_tracing(app, service_name="network-control-service")
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


def _get_iconbit_or_404(session: Session, player_id: uuid.UUID) -> MediaPlayer:
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Media player not found")
    if player.device_type != "iconbit":
        raise HTTPException(status_code=400, detail="Not an Iconbit device")
    return player


def _get_switch_or_404(session: Session, switch_id: uuid.UUID) -> NetworkSwitch:
    sw = session.get(NetworkSwitch, switch_id)
    if not sw:
        raise HTTPException(status_code=404, detail="Switch not found")
    return sw


@app.get("/iconbit/{player_id}/status", dependencies=[Depends(_verify_internal_token)])
async def iconbit_status(player_id: str) -> dict:
    with Session(engine) as session:
        player = _get_iconbit_or_404(session, uuid.UUID(player_id))
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


@app.post("/iconbit/{player_id}/play", dependencies=[Depends(_verify_internal_token)])
async def iconbit_play_action(player_id: str) -> dict:
    with Session(engine) as session:
        player = _get_iconbit_or_404(session, uuid.UUID(player_id))
    ok = await asyncio.to_thread(iconbit_play, player.ip_address)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_play", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to start playback")
    media_player_ops_total.labels(operation="iconbit_play", result="success").inc()
    return {"status": "playing"}


@app.post("/iconbit/{player_id}/stop", dependencies=[Depends(_verify_internal_token)])
async def iconbit_stop_action(player_id: str) -> dict:
    with Session(engine) as session:
        player = _get_iconbit_or_404(session, uuid.UUID(player_id))
    ok = await asyncio.to_thread(iconbit_stop, player.ip_address)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_stop", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to stop playback")
    media_player_ops_total.labels(operation="iconbit_stop", result="success").inc()
    return {"status": "stopped"}


@app.post("/iconbit/{player_id}/play-file", dependencies=[Depends(_verify_internal_token)])
async def iconbit_play_file_action(player_id: str, filename: str = Body(embed=True)) -> dict:
    with Session(engine) as session:
        player = _get_iconbit_or_404(session, uuid.UUID(player_id))
    ok = await asyncio.to_thread(iconbit_play_file, player.ip_address, filename)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_play_file", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to play file")
    media_player_ops_total.labels(operation="iconbit_play_file", result="success").inc()
    return {"status": "playing", "file": filename}


@app.post("/iconbit/{player_id}/delete-file", dependencies=[Depends(_verify_internal_token)])
async def iconbit_delete_file_action(player_id: str, filename: str = Body(embed=True)) -> dict:
    with Session(engine) as session:
        player = _get_iconbit_or_404(session, uuid.UUID(player_id))
    ok = await asyncio.to_thread(iconbit_delete_file, player.ip_address, filename)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_delete_file", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to delete file")
    media_player_ops_total.labels(operation="iconbit_delete_file", result="success").inc()
    return {"status": "deleted", "file": filename}


@app.post("/iconbit/{player_id}/upload", dependencies=[Depends(_verify_internal_token)])
async def iconbit_upload_action(player_id: str, file: UploadFile = ...) -> dict:
    with Session(engine) as session:
        player = _get_iconbit_or_404(session, uuid.UUID(player_id))
    content = await file.read()
    ok = await asyncio.to_thread(iconbit_upload_file, player.ip_address, file.filename or "upload.mp3", content)
    if not ok:
        media_player_ops_total.labels(operation="iconbit_upload", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to upload file")
    media_player_ops_total.labels(operation="iconbit_upload", result="success").inc()
    return {"status": "uploaded", "file": file.filename}


def _iconbits(session: Session) -> list[MediaPlayer]:
    return list(session.exec(select(MediaPlayer).where(MediaPlayer.device_type == "iconbit")).all())


@app.post("/iconbit/bulk-play", dependencies=[Depends(_verify_internal_token)])
async def iconbit_bulk_play() -> dict:
    with Session(engine) as session:
        players = _iconbits(session)
    results = [await asyncio.to_thread(iconbit_play, p.ip_address) for p in players]
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_play", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_play", result="error").inc(failed)
    return {"success": success, "failed": failed}


@app.post("/iconbit/bulk-stop", dependencies=[Depends(_verify_internal_token)])
async def iconbit_bulk_stop() -> dict:
    with Session(engine) as session:
        players = _iconbits(session)
    results = [await asyncio.to_thread(iconbit_stop, p.ip_address) for p in players]
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_stop", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_stop", result="error").inc(failed)
    return {"success": success, "failed": failed}


@app.post("/iconbit/bulk-upload", dependencies=[Depends(_verify_internal_token)])
async def iconbit_bulk_upload(file: UploadFile = ...) -> dict:
    with Session(engine) as session:
        players = _iconbits(session)
    content = await file.read()
    fname = file.filename or "upload.mp3"
    results = [await asyncio.to_thread(iconbit_upload_file, p.ip_address, fname, content) for p in players]
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_upload", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_upload", result="error").inc(failed)
    return {"success": success, "failed": failed, "file": fname}


@app.post("/iconbit/bulk-delete-file", dependencies=[Depends(_verify_internal_token)])
async def iconbit_bulk_delete(filename: str = Body(embed=True)) -> dict:
    with Session(engine) as session:
        players = _iconbits(session)
    results = [await asyncio.to_thread(iconbit_delete_file, p.ip_address, filename) for p in players]
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_delete", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_delete", result="error").inc(failed)
    return {"success": success, "failed": failed, "file": filename}


@app.post("/iconbit/bulk-play-file", dependencies=[Depends(_verify_internal_token)])
async def iconbit_bulk_play_file(filename: str = Body(embed=True)) -> dict:
    with Session(engine) as session:
        players = _iconbits(session)
    results = [await asyncio.to_thread(iconbit_play_file, p.ip_address, filename) for p in players]
    success = sum(results)
    failed = len(results) - success
    media_player_ops_total.labels(operation="iconbit_bulk_play_file", result="success").inc(success)
    media_player_ops_total.labels(operation="iconbit_bulk_play_file", result="error").inc(failed)
    return {"success": success, "failed": failed, "file": filename}


@app.post("/iconbit/bulk-replace", dependencies=[Depends(_verify_internal_token)])
async def iconbit_bulk_replace(file: UploadFile = ...) -> dict:
    with Session(engine) as session:
        players = _iconbits(session)
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


@app.post("/switches/{switch_id}/reboot-ap", dependencies=[Depends(_verify_internal_token)])
async def reboot_access_point(switch_id: str, payload: dict = Body(default_factory=dict)) -> dict:
    with Session(engine) as session:
        switch = _get_switch_or_404(session, uuid.UUID(switch_id))
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="AP reboot is available for Cisco switches")
    interface = str(payload.get("interface", "")).strip()
    method = str(payload.get("method", "poe")).strip().lower()
    if not interface:
        raise HTTPException(status_code=422, detail="interface is required")
    if method not in {"poe", "shutdown"}:
        raise HTTPException(status_code=422, detail="method must be 'poe' or 'shutdown'")
    if method == "poe":
        ok = await asyncio.to_thread(
            poe_cycle_ap,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            interface,
        )
    else:
        ok = await asyncio.to_thread(
            reboot_ap,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            interface,
        )
    if not ok:
        switch_ops_total.labels(operation="reboot_ap", result="error").inc()
        raise HTTPException(status_code=502, detail="Failed to reboot AP")
    switch_ops_total.labels(operation="reboot_ap", result="success").inc()
    return {"status": "rebooting", "interface": interface, "method": method}


async def _run_port_write(switch_id: str, port: str, operation: str, callback) -> Message:
    with Session(engine) as session:
        switch = _get_switch_or_404(session, uuid.UUID(switch_id))
        provider = resolve_switch_provider(switch)
        vendor = switch.vendor
        with switch_port_op_duration_seconds.labels(vendor=vendor, operation=operation).time():
            try:
                await asyncio.to_thread(callback, switch, provider, port)
                switch_port_ops_total.labels(vendor=vendor, operation=operation, result="success").inc()
            except Exception as exc:
                switch_port_ops_total.labels(vendor=vendor, operation=operation, result="error").inc()
                raise HTTPException(status_code=502, detail=f"Port operation failed: {exc}") from exc
    return Message(message="ok")


@app.post(
    "/switches/{switch_id}/ports/{port:path}/admin-state",
    response_model=Message,
    dependencies=[Depends(_verify_internal_token)],
)
async def set_port_admin_state(switch_id: str, port: str, body: dict = Body(default_factory=dict)) -> Message:
    admin_state = str(body.get("admin_state", "")).strip().lower()
    if admin_state not in {"up", "down"}:
        raise HTTPException(status_code=422, detail="admin_state must be 'up' or 'down'")
    return await _run_port_write(
        switch_id,
        port,
        "admin_state",
        callback=lambda sw, provider, p: provider.set_admin_state(sw, p, admin_state),
    )


@app.post(
    "/switches/{switch_id}/ports/{port:path}/description",
    response_model=Message,
    dependencies=[Depends(_verify_internal_token)],
)
async def set_port_description(switch_id: str, port: str, body: dict = Body(default_factory=dict)) -> Message:
    description = str(body.get("description", ""))
    return await _run_port_write(
        switch_id,
        port,
        "description",
        callback=lambda sw, provider, p: provider.set_description(sw, p, description),
    )


@app.post(
    "/switches/{switch_id}/ports/{port:path}/vlan",
    response_model=Message,
    dependencies=[Depends(_verify_internal_token)],
)
async def set_port_vlan(switch_id: str, port: str, body: dict = Body(default_factory=dict)) -> Message:
    vlan = int(body.get("vlan", 0))
    if vlan < 1 or vlan > 4094:
        raise HTTPException(status_code=422, detail="vlan must be 1-4094")
    return await _run_port_write(
        switch_id,
        port,
        "vlan",
        callback=lambda sw, provider, p: provider.set_vlan(sw, p, vlan),
    )


@app.post(
    "/switches/{switch_id}/ports/{port:path}/poe",
    response_model=Message,
    dependencies=[Depends(_verify_internal_token)],
)
async def set_port_poe(switch_id: str, port: str, body: dict = Body(default_factory=dict)) -> Message:
    action = str(body.get("action", "")).strip().lower()
    if action not in {"on", "off", "cycle"}:
        raise HTTPException(status_code=422, detail="action must be 'on', 'off', or 'cycle'")
    return await _run_port_write(
        switch_id,
        port,
        "poe",
        callback=lambda sw, provider, p: provider.set_poe(sw, p, action),
    )


@app.post(
    "/switches/{switch_id}/ports/{port:path}/mode",
    response_model=Message,
    dependencies=[Depends(_verify_internal_token)],
)
async def set_port_mode(switch_id: str, port: str, body: dict = Body(default_factory=dict)) -> Message:
    mode = str(body.get("mode", "")).strip().lower()
    if mode not in {"access", "trunk"}:
        raise HTTPException(status_code=422, detail="mode must be 'access' or 'trunk'")
    return await _run_port_write(
        switch_id,
        port,
        "mode",
        callback=lambda sw, provider, p: provider.set_mode(
            sw,
            p,
            mode,
            access_vlan=body.get("access_vlan"),
            native_vlan=body.get("native_vlan"),
            allowed_vlans=body.get("allowed_vlans"),
        ),
    )

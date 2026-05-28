from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.readiness import build_readiness_response, check_redis
from app.core.redis import close_redis, get_redis
from app.domains.inventory.schemas import DiscoveryResults, ScanProgress, ScanResults
from app.observability.tracing import setup_tracing
from app.services.discovery import get_discovery_progress, get_discovery_results, run_discovery_scan
from app.services.scanner import get_scan_progress, get_scan_results, scan_subnet


def _verify_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not settings.INTERNAL_SERVICE_TOKEN:
        return
    if x_internal_token != settings.INTERNAL_SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="invalid internal token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(title="InfraScope Discovery Service", lifespan=lifespan)
setup_tracing(app, service_name="discovery-service")
Instrumentator(excluded_handlers=["/metrics", "/health"]).instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict | object:
    checks = {
        "redis": await check_redis(get_redis),
    }
    return build_readiness_response(checks)


@app.post("/discover/printers/scan", response_model=ScanProgress, dependencies=[Depends(_verify_internal_token)])
async def start_printer_scan(payload: dict[str, Any]) -> dict[str, Any]:
    subnet = str(payload.get("subnet", "")).strip()
    ports = str(payload.get("ports", "")).strip() or "9100,631,80,443"
    known_printers = payload.get("known_printers") or []
    asyncio.create_task(scan_subnet(subnet, ports, known_printers))
    return {"status": "running", "scanned": 0, "total": 0, "found": 0, "message": None}


@app.post("/discover/printers/run", dependencies=[Depends(_verify_internal_token)])
async def run_printer_scan(payload: dict[str, Any]) -> dict[str, Any]:
    subnet = str(payload.get("subnet", "")).strip()
    ports = str(payload.get("ports", "")).strip() or "9100,631,80,443"
    known_printers = payload.get("known_printers") or []
    devices = await scan_subnet(subnet, ports, known_printers)
    return {"devices": devices, "found_devices": len(devices)}


@app.get("/discover/printers/status", response_model=ScanProgress, dependencies=[Depends(_verify_internal_token)])
async def printer_scan_status() -> dict[str, Any]:
    return await get_scan_progress()


@app.get("/discover/printers/results", response_model=ScanResults, dependencies=[Depends(_verify_internal_token)])
async def printer_scan_results() -> dict[str, Any]:
    progress = await get_scan_progress()
    devices = await get_scan_results()
    return {"progress": progress, "devices": devices}


@app.post("/discover/{kind}/scan", response_model=ScanProgress, dependencies=[Depends(_verify_internal_token)])
async def start_kind_scan(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind not in {"iconbit", "switch"}:
        raise HTTPException(status_code=422, detail="unsupported discovery kind")
    subnet = str(payload.get("subnet", "")).strip()
    ports = str(payload.get("ports", "")).strip()
    known_devices = payload.get("known_devices") or []
    asyncio.create_task(run_discovery_scan(kind, subnet, ports, known_devices))
    return {"status": "running", "scanned": 0, "total": 0, "found": 0, "message": None}


@app.get("/discover/{kind}/status", response_model=ScanProgress, dependencies=[Depends(_verify_internal_token)])
async def kind_status(kind: str) -> dict[str, Any]:
    if kind not in {"iconbit", "switch"}:
        raise HTTPException(status_code=422, detail="unsupported discovery kind")
    return await get_discovery_progress(kind)


@app.get("/discover/{kind}/results", response_model=DiscoveryResults, dependencies=[Depends(_verify_internal_token)])
async def kind_results(kind: str) -> dict[str, Any]:
    if kind not in {"iconbit", "switch"}:
        raise HTTPException(status_code=422, detail="unsupported discovery kind")
    progress = await get_discovery_progress(kind)
    devices = await get_discovery_results(kind)
    return {"progress": progress, "devices": devices}

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.readiness import build_readiness_response, check_database, check_redis
from app.core.redis import close_redis, get_redis
from app.domains.inventory.models import MediaPlayer, NetworkSwitch, Printer
from app.domains.inventory.schemas import MediaPlayersPublic, NetworkSwitchPublic, PrintersPublic
from app.domains.operations.models import CashRegister
from app.domains.operations.schemas import CashRegisterPublic, CashRegistersPublic
from app.domains.shared.schemas import Message
from app.observability.tracing import setup_tracing
from app.services.polling_orchestrator import (
    poll_all_cash_registers_local,
    poll_all_media_players_local,
    poll_all_printers_local,
    poll_all_switches_local,
    poll_cash_register_local,
    poll_switch_local,
)


def _verify_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not settings.INTERNAL_SERVICE_TOKEN:
        return
    if x_internal_token != settings.INTERNAL_SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="invalid internal token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(title="InfraScope Polling Service", lifespan=lifespan)
setup_tracing(app, service_name="polling-service")
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


@app.post("/poll/printers", response_model=PrintersPublic, dependencies=[Depends(_verify_internal_token)])
async def poll_printers(printer_type: str = "laser") -> PrintersPublic:
    with Session(engine) as session:
        return await poll_all_printers_local(session=session, printer_type=printer_type)


@app.post("/poll/media-players", response_model=MediaPlayersPublic, dependencies=[Depends(_verify_internal_token)])
async def poll_media(device_type: str | None = None) -> MediaPlayersPublic:
    with Session(engine) as session:
        return await poll_all_media_players_local(session=session, device_type=device_type)


@app.post("/poll/switches", response_model=Message, dependencies=[Depends(_verify_internal_token)])
async def poll_switches() -> Message:
    with Session(engine) as session:
        return await poll_all_switches_local(session=session)


@app.post(
    "/poll/switches/{switch_id}", response_model=NetworkSwitchPublic, dependencies=[Depends(_verify_internal_token)]
)
async def poll_switch(switch_id: str) -> NetworkSwitchPublic:
    with Session(engine) as session:
        return await poll_switch_local(switch_id=uuid.UUID(switch_id), session=session)


@app.post("/poll/cash-registers", response_model=CashRegistersPublic, dependencies=[Depends(_verify_internal_token)])
async def poll_cash_registers() -> CashRegistersPublic:
    with Session(engine) as session:
        return await poll_all_cash_registers_local(session=session)


@app.post(
    "/poll/cash-registers/{cash_id}",
    response_model=CashRegisterPublic,
    dependencies=[Depends(_verify_internal_token)],
)
async def poll_cash_register(cash_id: str) -> CashRegisterPublic:
    with Session(engine) as session:
        return await poll_cash_register_local(cash_id=uuid.UUID(cash_id), session=session)


@app.get("/summary/printers", dependencies=[Depends(_verify_internal_token)])
def printer_summary(printer_type: str = "laser") -> dict[str, int]:
    with Session(engine) as session:
        all_printers = session.exec(select(Printer).where(Printer.printer_type == printer_type)).all()
    return {"total": len(all_printers), "online": sum(1 for p in all_printers if p.is_online)}


@app.get("/summary/media-players", dependencies=[Depends(_verify_internal_token)])
def media_summary(device_type: str | None = None) -> dict[str, int]:
    with Session(engine) as session:
        statement = select(MediaPlayer)
        if device_type:
            statement = statement.where(MediaPlayer.device_type == device_type)
        players = session.exec(statement).all()
    return {"total": len(players), "online": sum(1 for p in players if p.is_online)}


@app.get("/summary/switches", dependencies=[Depends(_verify_internal_token)])
def switch_summary() -> dict[str, int]:
    with Session(engine) as session:
        all_switches = session.exec(select(NetworkSwitch)).all()
    return {"total": len(all_switches), "online": sum(1 for s in all_switches if s.is_online)}


@app.get("/summary/cash-registers", dependencies=[Depends(_verify_internal_token)])
def cash_register_summary() -> dict[str, int]:
    with Session(engine) as session:
        items = session.exec(select(CashRegister)).all()
    return {"total": len(items), "online": sum(1 for item in items if item.is_online)}

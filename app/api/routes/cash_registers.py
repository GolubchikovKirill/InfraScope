import csv
import uuid
from datetime import UTC, datetime
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.domains.operations.cash_register_polling import (
    CashRegisterNotFoundError,
    cash_register_offline_reason_ru,
    poll_all_cash_registers_local,
    poll_single_cash_register_local,
)
from app.domains.operations.models import CashRegister
from app.domains.operations.schemas import (
    CashRegisterCreate,
    CashRegisterPublic,
    CashRegistersPublic,
    CashRegisterUpdate,
)
from app.domains.shared.schemas import Message
from app.services.cache import get_cached_model, invalidate_entity_cache, set_cached_model
from app.services.internal_services import _proxy_request
from app.services.smart_search import build_ilike_filter

CACHE_TTL = 30


async def _invalidate_cache() -> None:
    await invalidate_entity_cache("cash_registers")


router = APIRouter(tags=["cash-registers"])


@router.get("/", response_model=CashRegistersPublic)
async def read_cash_registers(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    q: str | None = Query(default=None),
) -> CashRegistersPublic:
    cache_key = f"cash_registers:{q or ''}:{skip}:{limit}"
    if cached := await get_cached_model(cache_key, CashRegistersPublic):
        return cached

    del current_user
    statement = select(CashRegister)
    count_stmt = select(func.count()).select_from(CashRegister)
    if q:
        flt = build_ilike_filter(
            [
                CashRegister.kkm_number,
                CashRegister.store_number,
                CashRegister.hostname,
                CashRegister.store_code,
                CashRegister.serial_number,
                CashRegister.inventory_number,
            ],
            q,
        )
        if flt is not None:
            statement = statement.where(flt)
            count_stmt = count_stmt.where(flt)
    count = session.exec(count_stmt).one()
    rows = session.exec(statement.order_by(CashRegister.kkm_number).offset(skip).limit(limit)).all()
    result = CashRegistersPublic(data=rows, count=count)

    await set_cached_model(cache_key, result, ttl=CACHE_TTL)

    return result


@router.post("/", response_model=CashRegisterPublic, dependencies=[Depends(get_current_active_superuser)])
async def create_cash_register(session: SessionDep, payload: CashRegisterCreate) -> CashRegister:
    cash = CashRegister(**payload.model_dump())
    session.add(cash)
    session.commit()
    session.refresh(cash)
    await _invalidate_cache()
    return cash


@router.patch("/{cash_id}", response_model=CashRegisterPublic, dependencies=[Depends(get_current_active_superuser)])
async def update_cash_register(session: SessionDep, cash_id: uuid.UUID, payload: CashRegisterUpdate) -> CashRegister:
    cash = session.get(CashRegister, cash_id)
    if not cash:
        raise HTTPException(status_code=404, detail="Cash register not found")
    cash.sqlmodel_update(payload.model_dump(exclude_unset=True))
    cash.updated_at = datetime.now(UTC)
    session.add(cash)
    session.commit()
    session.refresh(cash)
    await _invalidate_cache()
    return cash


@router.delete("/{cash_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_cash_register(session: SessionDep, cash_id: uuid.UUID) -> Message:
    cash = session.get(CashRegister, cash_id)
    if not cash:
        raise HTTPException(status_code=404, detail="Cash register not found")
    session.delete(cash)
    session.commit()
    await _invalidate_cache()
    return Message(message="Cash register deleted")


@router.post("/{cash_id}/poll", response_model=CashRegisterPublic)
async def poll_cash_register(
    cash_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> CashRegister | CashRegisterPublic:
    del current_user
    if settings.POLLING_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.POLLING_SERVICE_URL,
            method="POST",
            path=f"/poll/cash-registers/{cash_id}",
        )
        return CashRegisterPublic.model_validate(payload)

    try:
        return await poll_single_cash_register_local(session=session, cash_id=cash_id)
    except CashRegisterNotFoundError:
        raise HTTPException(status_code=404, detail="Cash register not found")


@router.post("/poll-all", response_model=CashRegistersPublic)
async def poll_all_cash_registers(session: SessionDep, current_user: CurrentUser) -> CashRegistersPublic:
    del current_user
    if settings.POLLING_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.POLLING_SERVICE_URL,
            method="POST",
            path="/poll/cash-registers",
        )
        return CashRegistersPublic.model_validate(payload)

    return await poll_all_cash_registers_local(session=session)


@router.get("/export")
def export_cash_registers_csv(
    session: SessionDep,
    current_user: CurrentUser,
    q: str | None = Query(default=None),
) -> Response:
    del current_user
    statement = select(CashRegister).order_by(CashRegister.kkm_number)
    if q:
        flt = build_ilike_filter(
            [
                CashRegister.kkm_number,
                CashRegister.store_number,
                CashRegister.hostname,
                CashRegister.store_code,
                CashRegister.serial_number,
                CashRegister.inventory_number,
            ],
            q,
        )
        if flt is not None:
            statement = statement.where(flt)
    rows = session.exec(statement).all()

    output = StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "№ ККМ",
            "Номер магазина",
            "Код ТТ",
            "Серийный номер",
            "Инвентаризационный №",
            "ID терминала РС",
            "ID терминала Сбер",
            "Версия Windows",
            "Тип ККМ",
            "Номер кассы",
            "Hostname",
            "Комментарий",
            "Online",
            "Причина оффлайна",
            "Последний опрос",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.kkm_number,
                row.store_number or "",
                row.store_code or "",
                row.serial_number or "",
                row.inventory_number or "",
                row.terminal_id_rs or "",
                row.terminal_id_sber or "",
                row.windows_version or "",
                "РИТЕЙЛ" if row.kkm_type == "retail" else "ШТРИХ",
                row.cash_number or "",
                row.hostname,
                row.comment or "",
                "online" if row.is_online else "offline",
                cash_register_offline_reason_ru(row.reachability_reason) if row.is_online is False else "",
                row.last_polled_at.isoformat() if row.last_polled_at else "",
            ]
        )

    content = output.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cash-registers.csv"'},
    )

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.domains.operations.models import EventLog
from app.domains.operations.schemas import EventLogsPublic
from app.services.cache import get_cached_model, set_cached_model
from app.services.smart_search import build_ilike_filter

router = APIRouter(tags=["logs"])
CACHE_TTL = 10


def _query_logs_page(
    session: SessionDep,
    severity: str | None,
    device_kind: str | None,
    q: str | None,
    skip: int,
    limit: int,
) -> tuple[list[EventLog], int]:
    statement = select(EventLog)
    count_stmt = select(func.count()).select_from(EventLog)

    if severity:
        statement = statement.where(EventLog.severity == severity.lower())
        count_stmt = count_stmt.where(EventLog.severity == severity.lower())
    if device_kind:
        statement = statement.where(EventLog.device_kind == device_kind.lower())
        count_stmt = count_stmt.where(EventLog.device_kind == device_kind.lower())
    if q:
        flt = build_ilike_filter(
            [
                EventLog.message,
                EventLog.device_name,
                EventLog.ip_address,
                EventLog.event_type,
                EventLog.category,
            ],
            q,
        )
        if flt is not None:
            statement = statement.where(flt)
            count_stmt = count_stmt.where(flt)

    count = session.exec(count_stmt).one()
    logs = session.exec(statement.order_by(EventLog.created_at.desc()).offset(skip).limit(limit)).all()
    return logs, count


@router.get("/", response_model=EventLogsPublic)
async def read_logs(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=300),
    severity: str | None = Query(default=None),
    device_kind: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> EventLogsPublic:
    del current_user
    cache_key = f"logs:{severity or ''}:{device_kind or ''}:{q or ''}:{skip}:{limit}"
    if cached := await get_cached_model(cache_key, EventLogsPublic):
        return cached

    logs, count = await run_in_threadpool(
        _query_logs_page, session, severity, device_kind, q, skip, limit
    )
    result = EventLogsPublic(data=logs, count=count)
    await set_cached_model(cache_key, result, ttl=CACHE_TTL)
    return result

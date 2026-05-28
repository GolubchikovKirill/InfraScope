from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep
from app.domains.operations.schemas import ServiceFlowMapPublic, ServiceFlowTimeseriesPublic
from app.services.service_flow import build_service_flow_map, build_service_flow_timeseries

router = APIRouter(tags=["observability"])


@router.get("/service-map", response_model=ServiceFlowMapPublic)
def get_service_map(session: SessionDep, current_user: CurrentUser) -> ServiceFlowMapPublic:
    del current_user
    return build_service_flow_map(session)


@router.get("/service-map/timeseries", response_model=ServiceFlowTimeseriesPublic)
def get_service_map_timeseries(
    current_user: CurrentUser,
    service: str | None = Query(default=None),
    source: str | None = Query(default=None),
    target: str | None = Query(default=None),
    minutes: int = Query(default=60, ge=5, le=24 * 60),
    step_seconds: int = Query(default=30, ge=5, le=600),
) -> ServiceFlowTimeseriesPublic:
    del current_user
    return build_service_flow_timeseries(
        service=service,
        source=source,
        target=target,
        minutes=minutes,
        step_seconds=step_seconds,
    )

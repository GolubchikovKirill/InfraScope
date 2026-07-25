from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.domains.integrations.schemas import (
    HonestSignInitializePublic,
    HonestSignStatusesPublic,
    HonestSignStatusPublic,
    HonestSignTargetIpUpdate,
    HonestSignTargetPublic,
    HonestSignTargetsPublic,
)
from app.services.event_log import write_event_log
from app.services.honest_sign import (
    HonestSignConfigurationError,
    check_all_honest_sign_targets,
    check_honest_sign_target,
    configured_targets,
    get_configured_target,
    initialization_configuration_ready,
    initialize_honest_sign_target,
    set_target_ip_override,
    status_configuration_ready,
)

router = APIRouter(tags=["honest-sign"])


def _target_or_404(session: SessionDep, host: str):
    try:
        return get_configured_target(session, host)
    except KeyError:
        raise HTTPException(status_code=404, detail="Honest Sign target not found")


def _configuration_error(exc: HonestSignConfigurationError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/targets", response_model=HonestSignTargetsPublic)
def read_targets(session: SessionDep, current_user: CurrentUser) -> HonestSignTargetsPublic:
    del current_user
    rows = [
        HonestSignTargetPublic(
            host=target.host, label=target.label, hostname=target.hostname, original_host=target.original_host
        )
        for target in configured_targets(session=session)
    ]
    return HonestSignTargetsPublic(
        data=rows,
        count=len(rows),
        status_configured=status_configuration_ready(),
        initialization_configured=initialization_configuration_ready(),
    )


@router.post("/check-all", response_model=HonestSignStatusesPublic)
async def check_all_targets(session: SessionDep, current_user: CurrentUser) -> HonestSignStatusesPublic:
    del current_user
    try:
        rows = await check_all_honest_sign_targets(session=session)
    except HonestSignConfigurationError as exc:
        raise _configuration_error(exc)
    return HonestSignStatusesPublic(data=rows, count=len(rows))


@router.post("/{host}/check", response_model=HonestSignStatusPublic)
async def check_target(host: str, session: SessionDep, current_user: CurrentUser) -> HonestSignStatusPublic:
    del current_user
    try:
        return await check_honest_sign_target(_target_or_404(session, host))
    except HonestSignConfigurationError as exc:
        raise _configuration_error(exc)


@router.post(
    "/{host}/initialize",
    response_model=HonestSignInitializePublic,
    dependencies=[Depends(get_current_active_superuser)],
)
async def initialize_target(
    host: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> HonestSignInitializePublic:
    target = _target_or_404(session, host)
    try:
        result = await initialize_honest_sign_target(target)
    except HonestSignConfigurationError as exc:
        raise _configuration_error(exc)
    severity = "info" if result.result in {"READY", "ALREADY_READY", "INITIALIZING", "REQUEST_ACCEPTED"} else "error"
    write_event_log(
        session,
        event_type="honest_sign_initialize",
        category="honest_sign",
        severity=severity,
        message=f"{current_user.email}: {result.result}; {result.message}",
        device_kind="cash_register",
        device_name=target.label,
        ip_address=target.host,
    )
    session.commit()
    return result


@router.patch(
    "/{original_host}/ip",
    response_model=HonestSignTargetPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def update_target_ip(
    original_host: str,
    body: HonestSignTargetIpUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> HonestSignTargetPublic:
    try:
        target = set_target_ip_override(session, original_host, body.new_ip)
    except KeyError:
        raise HTTPException(status_code=404, detail="Honest Sign target not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    write_event_log(
        session,
        event_type="honest_sign_ip_changed",
        category="honest_sign",
        severity="warning",
        device_kind="cash_register",
        device_name=target.label,
        ip_address=target.host,
        message=f"{current_user.email}: Honest Sign target '{target.label}' IP changed: {original_host} -> {target.host}",
    )
    session.commit()
    return HonestSignTargetPublic(
        host=target.host, label=target.label, hostname=target.hostname, original_host=target.original_host
    )

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.domains.identity.models import User
from app.domains.integrations.schemas import (
    HonestSignInitializePublic,
    HonestSignStatusesPublic,
    HonestSignStatusPublic,
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
    is_honest_sign_operator,
    status_configuration_ready,
)

router = APIRouter(tags=["honest-sign"])


def require_honest_sign_operator(current_user: CurrentUser) -> User:
    if not is_honest_sign_operator(current_user.email):
        raise HTTPException(status_code=403, detail="Honest Sign access is restricted")
    return current_user


HonestSignOperator = Annotated[User, Depends(require_honest_sign_operator)]


def _target_or_404(host: str):
    try:
        return get_configured_target(host)
    except KeyError:
        raise HTTPException(status_code=404, detail="Honest Sign target not found")


def _configuration_error(exc: HonestSignConfigurationError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/targets", response_model=HonestSignTargetsPublic)
def read_targets(operator: HonestSignOperator) -> HonestSignTargetsPublic:
    del operator
    rows = [
        HonestSignTargetPublic(host=target.host, label=target.label, hostname=target.hostname)
        for target in configured_targets()
    ]
    return HonestSignTargetsPublic(
        data=rows,
        count=len(rows),
        status_configured=status_configuration_ready(),
        initialization_configured=initialization_configuration_ready(),
    )


@router.post("/check-all", response_model=HonestSignStatusesPublic)
async def check_all_targets(operator: HonestSignOperator) -> HonestSignStatusesPublic:
    del operator
    try:
        rows = await check_all_honest_sign_targets()
    except HonestSignConfigurationError as exc:
        raise _configuration_error(exc)
    return HonestSignStatusesPublic(data=rows, count=len(rows))


@router.post("/{host}/check", response_model=HonestSignStatusPublic)
async def check_target(host: str, operator: HonestSignOperator) -> HonestSignStatusPublic:
    del operator
    try:
        return await check_honest_sign_target(_target_or_404(host))
    except HonestSignConfigurationError as exc:
        raise _configuration_error(exc)


@router.post("/{host}/initialize", response_model=HonestSignInitializePublic)
async def initialize_target(
    host: str,
    session: SessionDep,
    operator: HonestSignOperator,
) -> HonestSignInitializePublic:
    target = _target_or_404(host)
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
        message=f"{operator.email}: {result.result}; {result.message}",
        device_kind="cash_register",
        device_name=target.label,
        ip_address=target.host,
    )
    session.commit()
    return result

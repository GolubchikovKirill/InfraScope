from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.schemas import NetworkSwitchPublic
from app.domains.inventory.switch_polling import (
    SwitchNotFoundError,
    poll_all_switches_local,
    poll_single_switch_local,
)
from app.domains.shared.schemas import Message
from app.services.internal_services import _proxy_request

router = APIRouter(tags=["switches"])


@router.post("/{switch_id}/poll", response_model=NetworkSwitchPublic)
async def poll_switch(
    switch_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> NetworkSwitch | NetworkSwitchPublic:
    del current_user
    if settings.POLLING_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.POLLING_SERVICE_URL,
            method="POST",
            path=f"/poll/switches/{switch_id}",
        )
        return NetworkSwitchPublic.model_validate(payload)

    try:
        return await poll_single_switch_local(session=session, switch_id=switch_id)
    except SwitchNotFoundError:
        raise HTTPException(status_code=404, detail="Switch not found")


@router.post("/poll-all", response_model=Message)
async def poll_all_switches(
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    del current_user
    if settings.POLLING_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.POLLING_SERVICE_URL,
            method="POST",
            path="/poll/switches",
        )
        return Message.model_validate(payload)

    return await poll_all_switches_local(session=session)

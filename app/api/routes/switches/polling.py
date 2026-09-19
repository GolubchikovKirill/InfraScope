from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.schemas import NetworkSwitchPublic
from app.domains.inventory.switch_polling import (
    SwitchNotFoundError,
    poll_all_switches_local,
    poll_single_switch_local,
)
from app.domains.shared.schemas import Message

router = APIRouter(tags=["switches"])


@router.post("/{switch_id}/poll", response_model=NetworkSwitchPublic)
async def poll_switch(
    switch_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> NetworkSwitch | NetworkSwitchPublic:
    del current_user
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
    return await poll_all_switches_local(session=session)

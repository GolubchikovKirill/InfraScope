from __future__ import annotations

import uuid

from app.api.deps import SessionDep
from app.domains.inventory.media_polling import poll_all_media_players_local as poll_all_media_players_domain
from app.domains.inventory.printer_polling import poll_all_printers_local as poll_all_printers_domain
from app.domains.inventory.schemas import MediaPlayersPublic, NetworkSwitchPublic, PrintersPublic
from app.domains.inventory.switch_polling import (
    poll_all_switches_local as poll_all_switches_domain,
)
from app.domains.inventory.switch_polling import (
    poll_single_switch_local as poll_switch_domain,
)
from app.domains.operations.cash_register_polling import (
    poll_all_cash_registers_local as poll_all_cash_registers_domain,
)
from app.domains.operations.cash_register_polling import (
    poll_single_cash_register_local as poll_cash_register_domain,
)
from app.domains.operations.schemas import CashRegisterPublic, CashRegistersPublic
from app.domains.shared.schemas import Message


async def poll_all_printers_local(*, session: SessionDep, printer_type: str = "laser") -> PrintersPublic:
    return await poll_all_printers_domain(session=session, printer_type=printer_type)


async def poll_all_media_players_local(
    *,
    session: SessionDep,
    device_type: str | None = None,
) -> MediaPlayersPublic:
    return await poll_all_media_players_domain(session=session, device_type=device_type)


async def poll_all_switches_local(*, session: SessionDep) -> Message:
    return await poll_all_switches_domain(session=session)


async def poll_switch_local(*, session: SessionDep, switch_id: uuid.UUID) -> NetworkSwitchPublic:
    switch = await poll_switch_domain(switch_id=switch_id, session=session)
    return NetworkSwitchPublic.model_validate(switch)


async def poll_all_cash_registers_local(*, session: SessionDep) -> CashRegistersPublic:
    return await poll_all_cash_registers_domain(session=session)


async def poll_cash_register_local(*, session: SessionDep, cash_id: uuid.UUID) -> CashRegisterPublic:
    item = await poll_cash_register_domain(cash_id=cash_id, session=session)
    return CashRegisterPublic.model_validate(item)

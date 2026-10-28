"""Computers that no longer exist, judged against the RustDesk console.

The inventory of computers was filled from Active Directory, and AD keeps accounts of
machines long gone. The RustDesk console, on the other hand, only knows machines whose
client actually connected - so "not in the console and not answering a ping" is a good
sign that the record is a leftover.

Two guards keep that from becoming a mass deletion by mistake:

* if the console cannot be read, or lists nothing at all, nothing is reported - every
  computer would look stale and the list would be an outage, not a finding;
* laptops (NB / NOTE / LPT / N01 in the name) are reported but flagged: a laptop that is
  simply off the office network never answers a ping either.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlmodel import Session, select

from app.domains.inventory.models import Computer
from app.domains.remote_access import rustdesk_client
from app.domains.remote_access.models import RemoteAccessDevice

logger = logging.getLogger(__name__)

# tokens of a hostname that mean "a portable machine": VNK-TAM-NB01, VNK-DIR-NOTE, VNK-HR-N02, VNK-LPT-01
_LAPTOP_TOKEN = re.compile(r"^(NB\d*|NOTE\w*|N\d+|LPT)$")

REASON = "нет в консоли RustDesk и не отвечает на пинг"


def is_laptop_like(hostname: str) -> bool:
    return any(_LAPTOP_TOKEN.match(token) for token in hostname.upper().split("-")[1:])


@dataclass
class StaleComputer:
    computer: Computer
    reason: str
    laptop_like: bool
    in_remote_access: bool


@dataclass
class StaleReport:
    console_reachable: bool
    items: list[StaleComputer]


async def find_stale_computers(session: Session) -> StaleReport:
    if not rustdesk_client.enabled():
        return StaleReport(console_reachable=False, items=[])
    try:
        peers = await rustdesk_client.list_admin_peers()
    except Exception as exc:
        logger.warning("Stale computers: RustDesk console unreadable: %s", exc)
        return StaleReport(console_reachable=False, items=[])
    if not peers:
        logger.warning("Stale computers: the console lists no machines at all, not judging anything")
        return StaleReport(console_reachable=False, items=[])

    known = {(p.get("hostname") or "").strip().lower() for p in peers if p.get("hostname")}
    linked = {
        computer_id
        for computer_id in session.exec(select(RemoteAccessDevice.computer_id).where(RemoteAccessDevice.managed == True)).all()  # noqa: E712
        if computer_id
    }

    items = [
        StaleComputer(
            computer=computer,
            reason=REASON,
            laptop_like=is_laptop_like(computer.hostname),
            in_remote_access=computer.id in linked,
        )
        for computer in session.exec(select(Computer)).all()
        if computer.hostname.strip().lower() not in known and computer.is_online is not True
    ]
    items.sort(key=lambda i: (i.laptop_like, i.computer.hostname.lower()))
    return StaleReport(console_reachable=True, items=items)

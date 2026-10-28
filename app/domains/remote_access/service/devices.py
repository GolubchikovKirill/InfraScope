"""The RemoteAccessDevice row itself: identity, password, deploy profile and the
readiness chip the UI shows. Everything else in the package builds on this."""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import settings
from app.domains.remote_access import rustdesk_client
from app.domains.remote_access.models import RemoteAccessDevice

logger = logging.getLogger("app.domains.remote_access.service")


# only nettop media players are Windows boxes; iconbit/twix are Android sticks
_NETTOP = "nettop"


# a host can sit in two inventory tables (a till also tracked as a computer);
# the higher-ranked source owns its source_kind label
_SOURCE_RANK = {"cash_register": 3, "computer": 2, "media_player": 1}


_PW_ALPHABET = string.ascii_letters + string.digits  # no symbols: avoids shell/TOML quoting traps


# rollout states. The endpoint script only ever reports pending/installed/
# configured/failed (DeployReport.state is validated to that set); "stale" is
# InfraScope's own marker - set locally when a fully-configured device's
# desired config changes (e.g. rotate_password) so the UI can say "needs a
# redeploy" instead of quietly leaving the machine on the old password.
DEPLOY_STATES = ("unknown", "pending", "installed", "configured", "failed", "stale")


_DEPLOYED_STATES = ("configured",)


# what the UI shows as one chip; see readiness()
READINESS = (
    "ready",
    "installed_offline",
    "deploying",
    "waiting_host",
    "stalled",
    "stale",
    "failed",
    "unreachable",
    "not_deployed",
)


# a requested rollout that has not reported back after this long is not "in progress"
DEPLOY_STALLED_AFTER = timedelta(hours=24)


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def _now() -> datetime:
    return datetime.now(UTC)


def _hostname_to_rid(hostname: str) -> str:
    # RustDesk custom IDs allow only [A-Za-z0-9_]
    rid = "".join(c if c.isalnum() else "_" for c in hostname)
    return rid[:32]


def mark_config_stale(dev: RemoteAccessDevice) -> None:
    """Drop an already-configured device to "stale" - called wherever the
    desired config (id, password, hidden/block_outgoing/unattended) changes.
    A no-op for a device that was never fully deployed: "unknown"/"pending"/
    "installed"/"failed" already say plainly that the config isn't live yet."""
    if dev.deploy_state in _DEPLOYED_STATES:
        dev.deploy_state = "stale"
        dev.deploy_detail = None


# Two presets for the three flags the rollout script actually reads. Found
# live: seeding an engineer's own workstation (VNK-ITD-SA05) with the same
# "client" defaults as a store kiosk would have hidden the tray icon, blocked
# them from launching RustDesk themselves via AppLocker, and switched them to
# password-only unattended approval - exactly backwards for a machine they sit
# at and use to connect *out* to the fleet.
DEPLOY_PROFILES: dict[str, dict[str, bool]] = {
    # store kiosk / kassa / any endpoint an ordinary employee sits at: no tray
    # icon, no shortcuts, AppLocker blocks them opening it themselves, service
    # only accepts the permanent password - purely an inbound-connect target.
    "client": {"desired_hidden": True, "desired_block_outgoing": True, "desired_unattended": True},
    # an engineer's own workstation: full normal RustDesk - visible, they can
    # launch it and connect out, and an incoming connection to *them* prompts
    # for a click rather than auto-accepting on the permanent password alone.
    "admin": {"desired_hidden": False, "desired_block_outgoing": False, "desired_unattended": False},
}


def apply_deploy_profile(session: Session, dev: RemoteAccessDevice, profile: str) -> RemoteAccessDevice:
    """Set the three flags from a named preset. Marks the device stale if
    anything actually changed and it was already configured - the machine
    keeps its old settings until the next redeploy applies the new ones."""
    if profile not in DEPLOY_PROFILES:
        raise ValueError(f"unknown deploy profile {profile!r}")
    preset = DEPLOY_PROFILES[profile]
    changed = dev.deploy_profile != profile or any(getattr(dev, k) != v for k, v in preset.items())
    dev.deploy_profile = profile
    for field, value in preset.items():
        setattr(dev, field, value)
    if changed:
        mark_config_stale(dev)
    dev.updated_at = _now()
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev


# Registry EditionID prefixes (HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion)
# that AppLocker enforcement never works on - Home-family SKUs. Locale-independent,
# unlike the OS caption ("Домашняя" vs "Home"). Since KB5024351 (Sept 2022),
# Windows 10 2004+/20H2/21H1 and all Windows 11 enforce AppLocker on every other
# edition (Pro included, not just Enterprise/Education as before) - the one edge
# case this can't see from the edition string alone is a Windows 10 Pro machine
# still unpatched from before that update, which is not expected on a fleet this
# far past Windows 10 end of mainstream support.
_APPLOCKER_UNSUPPORTED_EDITION_PREFIXES = ("Core",)  # Core, CoreN, CoreSingleLanguage, CoreCountrySpecific


def classify_applocker_support(edition_id: str | None) -> bool | None:
    """Whether AppLocker enforcement works on a machine, from its self-reported
    registry EditionID. None means we don't know yet (machine hasn't reported)."""
    if not edition_id:
        return None
    edition_id = edition_id.strip()
    if not edition_id:
        return None
    return not edition_id.startswith(_APPLOCKER_UNSUPPORTED_EDITION_PREFIXES)


def default_password() -> str:
    """Fleet-wide permanent password, or a generated one if it was left unset."""
    return settings.RUSTDESK_DEFAULT_PASSWORD.strip() or generate_password()


def _find_device(session: Session, hostname: str) -> RemoteAccessDevice | None:
    """Case-insensitive lookup, no creation. Windows hostnames are
    case-insensitive - VNA-MGR-101 and vna-mgr-101 are the same machine,
    whether InfraScope's own inventory or a RustDesk client's self-reported
    hostname (sync_from_console) spells it. Matching case-sensitively here
    used to mint a second, permanently "pending" row for every device whose
    console-reported casing didn't exactly match inventory's - caught live:
    22 such duplicates on one sync pass."""
    host = hostname.strip()
    return session.exec(
        select(RemoteAccessDevice).where(func.lower(RemoteAccessDevice.hostname) == host.lower())
    ).first()


def _get_or_create_device(session: Session, hostname: str) -> RemoteAccessDevice:
    """Keeps whichever casing was seen first - see _find_device."""
    host = hostname.strip()
    dev = _find_device(session, host)
    if dev:
        return dev
    dev = RemoteAccessDevice(
        hostname=host, rustdesk_id=_hostname_to_rid(host), permanent_password=default_password()
    )
    session.add(dev)
    session.flush()
    return dev


def rotate_password(session: Session, dev: RemoteAccessDevice) -> RemoteAccessDevice:
    """Generate a fresh per-machine password.

    The machine keeps the old one until the rollout script runs again, and the
    address-book row is marked stale so the next sync re-pushes it. If the
    device was already fully configured, its state drops to "stale" so the UI
    says so instead of quietly implying the new password already works -
    "Развернуть" (now labelled "Передеплоить" for a stale device) clears it by
    re-running the same idempotent script, which always reapplies the full
    desired config, not just the password.
    """
    dev.permanent_password = generate_password()
    dev.password_rotated_at = _now()
    dev.ab_password_pushed = False
    mark_config_stale(dev)
    dev.updated_at = _now()
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev


async def delete_device(session: Session, dev: RemoteAccessDevice) -> None:
    """Take a device off remote-access management.

    Soft delete (managed = False), not a row delete - the row used to be
    dropped outright, and the very next `remote_access_sync` beat tick
    (seed_from_inventory, every 2 min) recreated it from its still-live
    inventory row: caught live re-adding HPI2E8F25 within a minute, with a
    fresh password and its rollout status reset. seed_from_inventory and
    sync_from_console only touch `managed` on a row they create themselves,
    never on one that already exists, so this actually sticks. Explicitly
    re-adding the same hostname (ensure_device) still turns managed back on -
    that one's a deliberate operator action, not a passive reseed.

    Also: only actually removes the shared-book row when no *other* device
    row still points at the same rustdesk_id (case-duplicate hostnames used
    to share one console row - deleting the duplicate deleted the row both
    pointed at, and the survivor kept claiming in_address_book=True for a
    book entry that no longer existed).
    """
    if dev.ab_row_id and dev.rustdesk_id:
        shared_by_another = session.exec(
            select(RemoteAccessDevice).where(
                RemoteAccessDevice.id != dev.id,
                RemoteAccessDevice.rustdesk_id == dev.rustdesk_id,
            )
        ).first()
        if shared_by_another is None:
            try:
                await rustdesk_client.delete_address_book_row(row_id=dev.ab_row_id, peer_id=dev.rustdesk_id)
            except Exception:
                logger.warning("could not remove %s from the shared address book", dev.hostname, exc_info=True)
        else:
            logger.info(
                "%s: kept its shared-book row - %s still points at the same rustdesk_id",
                dev.hostname,
                shared_by_another.hostname,
            )
    dev.managed = False
    dev.in_address_book = False
    dev.ab_row_id = None
    dev.ab_password_pushed = False
    dev.updated_at = _now()
    session.add(dev)
    session.commit()


def readiness(dev: RemoteAccessDevice) -> str:
    """One word for "can I connect to this right now?".

    Deliberately conservative: `ready` needs both the endpoint's own "I applied
    the config" report *and* the console seeing the client. Either alone is not
    enough to promise an engineer a working session.
    """
    if dev.deploy_state == "failed":
        return "failed"
    if dev.deploy_state == "stale":
        # still connectable on the machine's *old* password - surfaced
        # separately from "ready" so the operator notices the drift instead
        # of assuming a password rotation already took effect
        return "stale"
    if dev.deploy_state in _DEPLOYED_STATES:
        return "ready" if dev.online is True else "installed_offline"
    if dev.deploy_state == "pending":
        # a rollout is only "in progress" while something can still happen: the
        # script runs when the machine is on, and nothing runs on a machine that
        # is off. Four rows once sat on a spinning "deploying" chip for 16 days.
        if dev.host_online is False:
            return "waiting_host"
        requested = dev.deploy_requested_at
        if requested is not None:
            if requested.tzinfo is None:
                requested = requested.replace(tzinfo=UTC)
            if _now() - requested > DEPLOY_STALLED_AFTER:
                return "stalled"
        return "deploying"
    # never reported, but the console knows the client - a machine deployed
    # before InfraScope owned the rollout (or by hand)
    if dev.online is not None:
        return "ready" if dev.online else "installed_offline"
    # no client has ever registered: "not deployed" only says something about a
    # machine that is up. When it does not answer, that is the finding - there is
    # nothing to roll out to right now.
    if dev.host_online is False:
        return "unreachable"
    return "not_deployed"


def suggested_profile(hostname: str) -> str:
    """"admin" for an engineer workstation (VNK-ITD-*), "client" otherwise - see
    DEPLOY_PROFILES for what each preset does to the machine."""
    return "admin" if hostname_type_tag(hostname) == "ITD" else "client"


def hostname_type_tag(hostname: str) -> str | None:
    """The role token out of a `<SITE>-<TYPE>-<NUM>` hostname, e.g.
    VNA-KKM-1506 -> "KKM", VNK-MGR-D01 -> "MGR", VNA-SRV-LMG01 -> "SRV".

    This is finer-grained than `source_kind` (TV and MUZ nettops are both
    "media_player" there) and needs no per-device maintenance - it rides on
    the naming convention the fleet already uses, so the shared address book
    can be filtered by role in the console's own tag view. Names that don't
    fit (fewer than three '-'-separated parts, e.g. a bare serial like
    HPI2E8F25) are left untagged rather than guessed at.
    """
    parts = hostname.split("-")
    if len(parts) < 3:
        return None
    token = parts[1].strip().upper()
    return token or None


def resolve_scope(
    session: Session,
    *,
    device_ids: list[uuid.UUID] | None,
    location: str | None,
    all_managed: bool,
    source_kind: str | None = None,
) -> list[RemoteAccessDevice]:
    stmt = select(RemoteAccessDevice)
    if device_ids:
        stmt = stmt.where(RemoteAccessDevice.id.in_(device_ids))  # type: ignore[attr-defined]
    elif location or source_kind or all_managed:
        stmt = stmt.where(RemoteAccessDevice.managed == True)  # noqa: E712
        if location:
            stmt = stmt.where(RemoteAccessDevice.location == location)
        if source_kind:
            stmt = stmt.where(RemoteAccessDevice.source_kind == source_kind)
    else:
        return []
    return list(session.exec(stmt).all())

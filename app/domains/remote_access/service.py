"""Reconciliation between the RustDesk console, InfraScope inventory and the fleet.

Four jobs live here:

* **Inventory mirror.** Every cash register, computer and nettop media player
  becomes a `RemoteAccessDevice` row carrying the config that machine should end
  up with (id, password, lockdown switches).
* **Console accounts.** Engineers get their own RustDesk login, in a console
  group that the shared address book is shared with, so each of them sees the
  whole fleet without a per-user push.
* **Shared address book.** One console collection holds every managed device
  *with its password*, so connecting is one click and nobody types a secret.
* **Rollout state.** The endpoint script reports what it actually did; we store
  that verbatim and never infer it.

InfraScope does not remote-execute anything: the endpoint pulls its installer
and config (see `deploy_script`). What lands here is the report.
"""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.inventory.models import Computer, MediaPlayer
from app.domains.operations.models import CashRegister
from app.domains.remote_access import deploy_script, rustdesk_client
from app.domains.remote_access.models import RemoteAccessConsoleAccount, RemoteAccessDevice

logger = logging.getLogger(__name__)

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
READINESS = ("ready", "installed_offline", "deploying", "stale", "failed", "not_deployed")


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


# --------------------------------------------------------------------------- #
# device inventory sync                                                       #
# --------------------------------------------------------------------------- #
def _get_or_create_device(session: Session, hostname: str) -> RemoteAccessDevice:
    host = hostname.strip()
    dev = session.exec(select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == host)).first()
    if dev:
        return dev
    dev = RemoteAccessDevice(
        hostname=host, rustdesk_id=_hostname_to_rid(host), permanent_password=default_password()
    )
    session.add(dev)
    session.flush()
    return dev


def _cr_location(cr: CashRegister) -> str | None:
    return cr.store_number or cr.store_code or None


def _link_inventory(session: Session, dev: RemoteAccessDevice) -> None:
    """(Re)bind a device row to every inventory row that shares its hostname."""
    host = dev.hostname
    if dev.computer_id is None:
        comp = session.exec(select(Computer).where(Computer.hostname == host)).first()
        if comp:
            dev.computer_id = comp.id
            dev.location = dev.location or comp.location
    if dev.cash_register_id is None:
        cr = session.exec(select(CashRegister).where(CashRegister.hostname == host)).first()
        if cr:
            dev.cash_register_id = cr.id
            dev.location = dev.location or _cr_location(cr)
    if dev.media_player_id is None:
        mp = session.exec(
            select(MediaPlayer).where(
                MediaPlayer.hostname == host, MediaPlayer.device_type == _NETTOP
            )
        ).first()
        if mp:
            dev.media_player_id = mp.id
    # label by the strongest source that actually linked (cash_register > computer > media_player)
    linked_kind = (
        "cash_register" if dev.cash_register_id
        else "computer" if dev.computer_id
        else "media_player" if dev.media_player_id
        else None
    )
    if linked_kind:
        dev.source_kind = linked_kind


def _inventory_rows(session: Session) -> list[tuple[str, str, str | None]]:
    """(hostname, source_kind, location) for every RustDesk-capable inventory endpoint.

    Cash registers and computers are Windows by definition; of the media players
    only nettops are (iconbit/twix run Android).
    """
    rows: list[tuple[str, str, str | None]] = []
    for cr in session.exec(select(CashRegister)).all():
        if cr.hostname and cr.hostname.strip():
            rows.append((cr.hostname.strip(), "cash_register", _cr_location(cr)))
    for host, loc in session.exec(select(Computer.hostname, Computer.location)).all():
        if host and host.strip():
            rows.append((host.strip(), "computer", loc))
    for host, name in session.exec(
        select(MediaPlayer.hostname, MediaPlayer.name).where(MediaPlayer.device_type == _NETTOP)
    ).all():
        if host and host.strip():
            rows.append((host.strip(), "media_player", None))
    return rows


def seed_from_inventory(session: Session) -> int:
    """Mirror the InfraScope endpoint inventory into RemoteAccessDevice rows.

    Sources: every CashRegister, every Computer, and MediaPlayers of type 'nettop'.
    Idempotent - an existing row only gets its inventory links, source_kind and
    (if still blank) location refreshed; its desired config and password are never
    touched here.
    """
    existing = {d.hostname: d for d in session.exec(select(RemoteAccessDevice)).all()}
    created = 0
    for hostname, kind, location in _inventory_rows(session):
        dev = existing.get(hostname)
        if dev is None:
            dev = RemoteAccessDevice(
                hostname=hostname,
                rustdesk_id=_hostname_to_rid(hostname),
                source_kind=kind,
                location=location,
                permanent_password=default_password(),
            )
            existing[hostname] = dev
            session.add(dev)
            created += 1
        else:
            if _SOURCE_RANK.get(kind, 0) > _SOURCE_RANK.get(dev.source_kind, 0):
                dev.source_kind = kind
            if not dev.location and location:
                dev.location = location
            if not dev.permanent_password:
                dev.permanent_password = default_password()
        _link_inventory(session, dev)
    session.commit()
    return created


def refresh_status_from_inventory(session: Session) -> int:
    """Copy InfraScope's own reachability result onto the device as `host_online`.

    This is a *separate* signal from `online` (which is RustDesk-console truth):
    the host answering a ping tells you nothing about whether the RustDesk client
    is running or connected. The UI shows the two side by side.
    """
    updated = 0
    for dev in session.exec(select(RemoteAccessDevice)).all():
        inv_online, inv_polled = _inventory_status(session, dev)
        if inv_online is None:
            continue
        if dev.host_online != inv_online or dev.host_last_seen_at != inv_polled:
            dev.host_online = inv_online
            dev.host_last_seen_at = inv_polled
            dev.updated_at = _now()
            updated += 1
    if updated:
        session.commit()
    return updated


def _inventory_status(session: Session, dev: RemoteAccessDevice) -> tuple[bool | None, datetime | None]:
    for model, fk in (
        (Computer, dev.computer_id),
        (CashRegister, dev.cash_register_id),
        (MediaPlayer, dev.media_player_id),
    ):
        if fk is None:
            continue
        row = session.get(model, fk)
        if row is not None:
            return row.is_online, row.last_polled_at
    return None, None


def _peer_online(peer: dict[str, Any], now: datetime) -> bool:
    """The admin peer list has no boolean - derive it from `last_online_time`."""
    last = peer.get("last_online_time")
    try:
        last_ts = int(last)
    except (TypeError, ValueError):
        return False
    if last_ts <= 0:
        return False
    return (now.timestamp() - last_ts) <= settings.RUSTDESK_DEVICE_STALE_SECONDS


async def sync_from_console(session: Session) -> dict[str, int]:
    """Fold live RustDesk-console status into RemoteAccessDevice rows.

    The admin peer list (`/api/admin/peer/list`) is the richer source: it carries
    the installed client `version`, `os`, `hostname` and `last_online_time`,
    none of which the client API's `/api/peers` returns. The shared address book
    is not consulted for status - it caches an `online` flag that goes stale.
    """
    now = _now()
    status: dict[str, bool] = {}
    peers = await rustdesk_client.list_admin_peers()
    seen = 0
    for peer in peers:
        rid = str(peer.get("id") or "").strip()
        hostname = (peer.get("hostname") or "").strip()
        if not rid and not hostname:
            continue
        seen += 1
        dev = _get_or_create_device(session, hostname or rid)
        _link_inventory(session, dev)
        if rid:
            dev.rustdesk_id = rid
            status[rid] = _peer_online(peer, now)
        dev.installed_version = (peer.get("version") or None) or dev.installed_version
        dev.logged_in_user = (peer.get("username") or None) or dev.logged_in_user
        dev.last_ip = (peer.get("last_online_ip") or None) or dev.last_ip
        dev.updated_at = now

    # one pass over every tracked device: online == exactly what the console says,
    # None for anything the console has never registered (no client yet)
    for dev in session.exec(select(RemoteAccessDevice)):
        want = status.get(dev.rustdesk_id or "")  # True / False / None
        changed = dev.online != want
        if want:
            dev.last_seen_at = now
        elif want is None and dev.last_seen_at is not None:
            dev.last_seen_at = None
            changed = True
        if changed:
            dev.online = want
            dev.updated_at = now
    session.commit()
    return {"peers_seen": seen}


# --------------------------------------------------------------------------- #
# desired config                                                              #
# --------------------------------------------------------------------------- #
def ensure_device(
    session: Session,
    *,
    hostname: str,
    rustdesk_id: str | None = None,
    permanent_password: str | None = None,
) -> RemoteAccessDevice:
    """Create/link a device row and stamp its desired id + password.

    Used by the RustDesk buttons on the device cards. Does not touch any machine -
    the config it records is what the next rollout run will apply.
    """
    dev = _get_or_create_device(session, hostname)
    _link_inventory(session, dev)
    was_rid, was_pw = dev.rustdesk_id, dev.permanent_password
    if rustdesk_id:
        dev.rustdesk_id = rustdesk_id
    elif not dev.rustdesk_id:
        dev.rustdesk_id = _hostname_to_rid(hostname)
    if permanent_password:
        dev.permanent_password = permanent_password
        dev.password_rotated_at = _now()
        dev.ab_password_pushed = False
    elif not dev.permanent_password:
        dev.permanent_password = default_password()
        dev.password_rotated_at = _now()
    # a manual id/password edit on an already-configured device is just as
    # stale as a rotate_password() call - the machine keeps the old values
    # until the next redeploy run
    if dev.rustdesk_id != was_rid or dev.permanent_password != was_pw:
        mark_config_stale(dev)
    dev.managed = True
    dev.updated_at = _now()
    session.add(dev)
    session.commit()
    session.refresh(dev)
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


def package_config(dev: RemoteAccessDevice) -> dict:
    """Everything an offline KSC package needs for this machine.

    `rustdesk-ksc/configure.ps1` consumes exactly these keys. The online path
    (`deployment_config`) is richer and should be preferred.
    """
    return {
        "hostname": dev.hostname,
        "rustdesk_id": dev.rustdesk_id or _hostname_to_rid(dev.hostname),
        "id_server": settings.RUSTDESK_ID_SERVER,
        "relay_server": settings.RUSTDESK_RELAY_SERVER,
        "api_server": settings.RUSTDESK_API_URL,
        "key": settings.RUSTDESK_KEY,
        "permanent_password": dev.permanent_password or default_password(),
        "installer_version": settings.RUSTDESK_INSTALLER_VERSION,
        "hidden": dev.desired_hidden,
        "block_outgoing": dev.desired_block_outgoing,
        "unattended": dev.desired_unattended,
    }


# --------------------------------------------------------------------------- #
# rollout                                                                     #
# --------------------------------------------------------------------------- #
def deployment_config(dev: RemoteAccessDevice) -> dict:
    """What the endpoint script fetches for itself at run time.

    `options` is applied before the password is set; `lock_options` afterwards,
    because `disable-change-permanent-password` makes `--password` a no-op.
    """
    return {
        "hostname": dev.hostname,
        "rustdesk_id": dev.rustdesk_id or _hostname_to_rid(dev.hostname),
        "id_server": settings.RUSTDESK_ID_SERVER,
        "relay_server": settings.RUSTDESK_RELAY_SERVER,
        "api_server": settings.RUSTDESK_API_URL,
        "key": settings.RUSTDESK_KEY,
        "permanent_password": dev.permanent_password or default_password(),
        "installer_filename": settings.RUSTDESK_INSTALLER_FILENAME,
        "installer_version": settings.RUSTDESK_INSTALLER_VERSION,
        "installer_sha256": settings.RUSTDESK_INSTALLER_SHA256,
        "hidden": dev.desired_hidden,
        "block_outgoing": dev.desired_block_outgoing,
        "unattended": dev.desired_unattended,
        "options": deploy_script.client_options(
            hidden=dev.desired_hidden, unattended=dev.desired_unattended
        ),
        "lock_options": dict(deploy_script.LOCK_OPTIONS) if dev.desired_unattended else {},
    }


def mark_deploy_requested(session: Session, dev: RemoteAccessDevice) -> RemoteAccessDevice:
    """Operator asked for a rollout. Nothing runs yet - the machine still has to
    be reached by KSC / GPO / schtasks; this only makes the wait visible."""
    dev.deploy_state = "pending"
    dev.deploy_detail = None
    dev.deploy_requested_at = _now()
    dev.updated_at = _now()
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev


def apply_deploy_report(
    session: Session,
    *,
    hostname: str,
    state: str,
    rustdesk_id: str | None = None,
    version: str | None = None,
    detail: str | None = None,
    os_edition: str | None = None,
    os_caption: str | None = None,
) -> RemoteAccessDevice | None:
    """Record what the endpoint script says it did. Unknown hosts are ignored -
    we never invent a device row from an unauthenticated-ish report."""
    dev = session.exec(
        select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == hostname.strip())
    ).first()
    if dev is None:
        logger.warning("rustdesk deploy report from unknown host %s", hostname)
        return None
    dev.deploy_state = state if state in DEPLOY_STATES else "failed"
    dev.deploy_detail = (detail or None) and detail[:512]
    dev.deploy_reported_at = _now()
    if rustdesk_id:
        dev.rustdesk_id = rustdesk_id
    if version:
        dev.installed_version = version
    if os_edition:
        dev.os_edition = os_edition
        dev.applocker_supported = classify_applocker_support(os_edition)
    if os_caption:
        dev.os_caption = os_caption
    dev.updated_at = _now()
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev


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
        return "deploying"
    # never reported, but the console knows the client - a machine deployed
    # before InfraScope owned the rollout (or by hand)
    if dev.online is not None:
        return "ready" if dev.online else "installed_offline"
    return "not_deployed"


# --------------------------------------------------------------------------- #
# console accounts                                                            #
# --------------------------------------------------------------------------- #
async def ensure_console_group() -> int:
    """The console group every InfraScope-managed engineer account joins."""
    name = settings.RUSTDESK_ADMIN_GROUP_NAME.strip()
    for group in await rustdesk_client.list_groups():
        if str(group.get("name") or "").strip() == name:
            return int(group["id"])
    await rustdesk_client.create_group(name, rustdesk_client.GROUP_TYPE_SHARED)
    for group in await rustdesk_client.list_groups():
        if str(group.get("name") or "").strip() == name:
            return int(group["id"])
    raise RuntimeError(f"console group {name!r} was created but does not list")


async def ensure_shared_book() -> tuple[int, int]:
    """Ensure the shared address book exists and the engineer group can read it.

    Returns (collection_id, owner_user_id). The collection is owned by whichever
    console account our token belongs to; everyone else reaches it through the
    group share rule, so adding an engineer needs no address-book work at all.
    """
    owner_id = await rustdesk_client.current_console_user_id()
    if not owner_id:
        raise RuntimeError("console did not identify the account behind the API token")

    name = settings.RUSTDESK_SHARED_BOOK_NAME.strip()
    collection_id = 0
    for col in await rustdesk_client.list_collections():
        if str(col.get("name") or "").strip() == name:
            collection_id = int(col["id"])
            break
    if not collection_id:
        await rustdesk_client.create_collection(name, owner_id)
        for col in await rustdesk_client.list_collections():
            if str(col.get("name") or "").strip() == name:
                collection_id = int(col["id"])
                break
    if not collection_id:
        raise RuntimeError(f"shared address book {name!r} was created but does not list")

    group_id = await ensure_console_group()
    rules = await rustdesk_client.list_collection_rules(collection_id)
    shared = any(
        int(r.get("type") or 0) == rustdesk_client.RULE_TYPE_GROUP
        and int(r.get("to_id") or 0) == group_id
        for r in rules
    )
    if not shared:
        await rustdesk_client.create_collection_rule(
            collection_id=collection_id,
            owner_id=owner_id,
            to_id=group_id,
            rule_type=rustdesk_client.RULE_TYPE_GROUP,
            rule=rustdesk_client.RULE_READ,
        )
    return collection_id, owner_id


async def provision_account(
    session: Session,
    *,
    username: str,
    display_name: str | None = None,
    email: str | None = None,
    is_admin: bool = False,
    password: str | None = None,
    infrascope_user_id: uuid.UUID | None = None,
) -> tuple[RemoteAccessConsoleAccount, str]:
    """Create a console login for an engineer and hand back its password once.

    The password is never persisted here - the caller shows it and it is gone.
    """
    username = username.strip()
    group_id = await ensure_console_group()
    secret = (password or "").strip() or generate_password(16)

    existing_console = {
        str(u.get("username") or "").strip(): u for u in await rustdesk_client.list_console_users()
    }
    if username not in existing_console:
        await rustdesk_client.create_console_user(
            username=username,
            group_id=group_id,
            is_admin=is_admin,
            email=(email or "").strip(),
            nickname=(display_name or "").strip(),
        )
        existing_console = {
            str(u.get("username") or "").strip(): u for u in await rustdesk_client.list_console_users()
        }
    console_user = existing_console.get(username)
    if not console_user:
        raise RuntimeError(f"console account {username!r} was created but does not list")
    console_user_id = int(console_user["id"])
    await rustdesk_client.set_console_user_password(console_user_id, secret)

    # already in the group -> already sees the shared book
    await ensure_shared_book()

    row = session.exec(
        select(RemoteAccessConsoleAccount).where(RemoteAccessConsoleAccount.username == username)
    ).first()
    if row is None:
        row = RemoteAccessConsoleAccount(username=username)
        session.add(row)
    row.console_user_id = console_user_id
    row.display_name = (display_name or "").strip() or None
    row.email = (email or "").strip() or None
    row.is_admin = is_admin
    row.infrascope_user_id = infrascope_user_id
    row.active = True
    row.book_shared = True
    row.last_synced_at = _now()
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    return row, secret


async def reset_account_password(
    session: Session, account: RemoteAccessConsoleAccount, password: str | None = None
) -> str:
    if not account.console_user_id:
        raise RuntimeError("account has no console user id - run an account sync first")
    secret = (password or "").strip() or generate_password(16)
    await rustdesk_client.set_console_user_password(account.console_user_id, secret)
    account.updated_at = _now()
    session.add(account)
    session.commit()
    return secret


async def set_account_active(
    session: Session, account: RemoteAccessConsoleAccount, active: bool
) -> RemoteAccessConsoleAccount:
    """Enable/disable the console login.

    Disabling rather than deleting: the console refuses to delete its last admin
    and its delete payload is undocumented, while `status` is a plain toggle.
    """
    if not account.console_user_id:
        raise RuntimeError("account has no console user id - run an account sync first")
    group_id = await ensure_console_group()
    await rustdesk_client.update_console_user(
        user_id=account.console_user_id,
        username=account.username,
        group_id=group_id,
        is_admin=account.is_admin,
        status=rustdesk_client.STATUS_ENABLED if active else rustdesk_client.STATUS_DISABLED,
        email=account.email or "",
        nickname=account.display_name or "",
    )
    account.active = active
    account.updated_at = _now()
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


async def sync_accounts(session: Session) -> dict[str, int]:
    """Pull the console's user list into our account rows.

    Accounts created directly in the console show up here too, so the page is a
    true picture of who can connect - not just of what InfraScope created.
    """
    rows = {
        r.username: r
        for r in session.exec(select(RemoteAccessConsoleAccount)).all()
    }
    now = _now()
    seen = 0
    for user in await rustdesk_client.list_console_users():
        username = str(user.get("username") or "").strip()
        if not username:
            continue
        seen += 1
        row = rows.get(username)
        if row is None:
            row = RemoteAccessConsoleAccount(username=username)
            session.add(row)
            rows[username] = row
        row.console_user_id = int(user.get("id") or 0) or None
        row.is_admin = bool(user.get("is_admin"))
        row.email = (user.get("email") or None) or row.email
        row.display_name = (user.get("nickname") or None) or row.display_name
        row.active = int(user.get("status") or rustdesk_client.STATUS_ENABLED) == rustdesk_client.STATUS_ENABLED
        row.last_synced_at = now
        row.updated_at = now
    session.commit()
    return {"accounts_seen": seen}


# --------------------------------------------------------------------------- #
# shared address book                                                         #
# --------------------------------------------------------------------------- #
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


def _ab_payload(dev: RemoteAccessDevice, *, collection_id: int, owner_id: int) -> dict:
    tags = [dev.source_kind]
    if dev.location:
        tags.append(dev.location)
    type_tag = hostname_type_tag(dev.hostname)
    if type_tag and type_tag not in tags:
        tags.append(type_tag)
    return {
        "id": dev.rustdesk_id or _hostname_to_rid(dev.hostname),
        "alias": dev.hostname,
        "hostname": dev.hostname,
        "platform": "Windows",
        "tags": tags,
        # a shared-book row stores the peer password in `password` (the personal
        # book uses `hash`) - this is what makes connecting one click
        "password": dev.permanent_password or default_password(),
        "user_id": owner_id,
        "collection_id": collection_id,
    }


async def push_shared_address_book(
    session: Session, devices: list[RemoteAccessDevice]
) -> dict[str, int]:
    """Upsert managed devices into the shared console address book.

    Existing rows are updated in place (matched by the console's `row_id`, which
    we cache) so tags and passwords stay current instead of piling up duplicates.
    """
    targets = [d for d in devices if d.managed and d.rustdesk_id]
    if not targets:
        return {"pushed": 0, "created": 0, "updated": 0, "failed": 0}

    collection_id, owner_id = await ensure_shared_book()
    existing = {
        str(r.get("id") or ""): r
        for r in await rustdesk_client.list_address_book_rows(
            user_id=owner_id, collection_id=collection_id
        )
    }

    now = _now()
    created = updated = failed = 0
    for dev in targets:
        payload = _ab_payload(dev, collection_id=collection_id, owner_id=owner_id)
        current = existing.get(payload["id"])
        row_id = int(current["row_id"]) if current and current.get("row_id") else dev.ab_row_id
        try:
            if row_id:
                await rustdesk_client.update_address_book_row({**payload, "row_id": row_id})
                updated += 1
            else:
                await rustdesk_client.create_address_book_row(payload)
                created += 1
        except Exception as exc:  # noqa: BLE001 - one bad row must not sink the push
            logger.warning("address-book push failed for %s: %s", dev.hostname, exc)
            failed += 1
            continue
        dev.ab_row_id = row_id or dev.ab_row_id
        dev.in_address_book = True
        dev.ab_password_pushed = True
        dev.updated_at = now
        session.add(dev)
    session.commit()

    # a row created just now has no row_id yet; pick it up so the next push updates
    if created:
        fresh = {
            str(r.get("id") or ""): r
            for r in await rustdesk_client.list_address_book_rows(
                user_id=owner_id, collection_id=collection_id
            )
        }
        for dev in targets:
            row = fresh.get(dev.rustdesk_id or "")
            if row and row.get("row_id") and not dev.ab_row_id:
                dev.ab_row_id = int(row["row_id"])
                session.add(dev)
        session.commit()

    return {"pushed": created + updated, "created": created, "updated": updated, "failed": failed}


async def sync_address_book(session: Session) -> dict[str, int]:
    devices = list(
        session.exec(select(RemoteAccessDevice).where(RemoteAccessDevice.managed == True))  # noqa: E712
    )
    return await push_shared_address_book(session, devices)


async def sync_stale_address_book(session: Session) -> dict[str, int]:
    """Push only the devices whose book row is missing or carries an old password."""
    devices = list(
        session.exec(
            select(RemoteAccessDevice).where(
                RemoteAccessDevice.managed == True,  # noqa: E712
                (RemoteAccessDevice.in_address_book == False)  # noqa: E712
                | (RemoteAccessDevice.ab_password_pushed == False),  # noqa: E712
            )
        )
    )
    if not devices:
        return {"pushed": 0, "created": 0, "updated": 0, "failed": 0}
    return await push_shared_address_book(session, devices)


async def address_book_status(session: Session) -> dict[str, Any]:
    """What the page shows above the device grid: which book, how big, who sees it."""
    collection_id, owner_id = await ensure_shared_book()
    rows = await rustdesk_client.list_address_book_rows(
        user_id=owner_id, collection_id=collection_id
    )
    accounts = session.exec(
        select(RemoteAccessConsoleAccount).where(RemoteAccessConsoleAccount.active == True)  # noqa: E712
    ).all()
    return {
        "name": settings.RUSTDESK_SHARED_BOOK_NAME,
        "collection_id": collection_id,
        "owner_user_id": owner_id,
        "entries": len(rows),
        "shared_with_group": settings.RUSTDESK_ADMIN_GROUP_NAME,
        "accounts": len(accounts),
    }


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

"""Rollout: the config an endpoint pulls, the check that the right machine is
asking for it, and the report it sends back - stored verbatim, never inferred."""

from __future__ import annotations

import logging
import socket

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import settings
from app.domains.remote_access import deploy_script
from app.domains.remote_access.models import RemoteAccessDevice

from .devices import DEPLOY_STATES, _hostname_to_rid, _now, classify_applocker_support, default_password

logger = logging.getLogger("app.domains.remote_access.service")


def package_config(dev: RemoteAccessDevice) -> dict:
    """Everything an offline package needs for this machine.

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


def _resolve_hostname_ip(hostname: str) -> str | None:
    """Best-effort forward DNS lookup. None on any failure (NXDOMAIN, no DNS
    reachable, ...) - the caller treats that as "no signal", not as a pass."""
    try:
        return socket.gethostbyname(hostname)
    except OSError:
        return None


def verify_deploy_source(dev: RemoteAccessDevice, client_ip: str | None) -> bool:
    """Is this /deploy/config request coming from the machine it claims to be?

    The deploy token is one shared secret handed to every endpoint - anything
    holding it (a leftover bootstrap script, say) can otherwise ask for *any*
    managed device's row and walk off with its permanent_password. Caught
    live: a stale trigger script left behind after a rollout could fetch a
    different machine's password with a plain curl.

    Two independent signals, either is enough: `last_ip` (what the RustDesk
    console actually saw this device connect from - not available before its
    very first successful config fetch) or a forward DNS lookup of its own
    hostname (works for the first fetch too, on a domain with working DNS).
    No signal at all is refused, not waved through - a device this fleet has
    literally never observed and can't resolve is exactly the case a stolen
    token would produce.
    """
    if not client_ip:
        return False
    if dev.last_ip and client_ip == dev.last_ip:
        return True
    resolved = _resolve_hostname_ip(dev.hostname)
    return bool(resolved and resolved == client_ip)


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
    be reached by the push kit / GPO / schtasks; this only makes the wait visible."""
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
    we never invent a device row from an unauthenticated-ish report.

    Case-insensitive, same as _get_or_create_device: the script reports
    $env:COMPUTERNAME, whose casing doesn't always match what inventory or an
    earlier console sync stored - a mismatch here used to 404 deploy/config
    (see the routes.py lookup) or silently drop the report right after.
    """
    dev = session.exec(
        select(RemoteAccessDevice).where(func.lower(RemoteAccessDevice.hostname) == hostname.strip().lower())
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

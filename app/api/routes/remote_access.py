"""Remote access (self-hosted RustDesk) - devices, console accounts, rollout.

Three groups of routes, with different callers and different auth:

* **Operator routes** (`/devices`, `/accounts`, `/address-book`) sit behind
  normal InfraScope auth; the write ones require a superuser.
* **Console passthrough** (`/console/*`) puts InfraScope's auth in front of the
  RustDesk console so engineers need no second login.
* **Rollout routes** (`/deploy/*`) are called by the endpoint script itself,
  which has no InfraScope session - they are gated on the shared
  `RUSTDESK_DEPLOY_TOKEN` and are inert until it is set.
"""

from __future__ import annotations

import hmac
import logging
import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import not_found
from app.core.config import settings
from app.domains.remote_access import deploy_script, rustdesk_client, service
from app.domains.remote_access.models import RemoteAccessConsoleAccount, RemoteAccessDevice
from app.domains.remote_access.schemas import (
    AddressBookStatus,
    AddressBookSyncRequest,
    ConsoleAccountCreate,
    ConsoleAccountPasswordReset,
    ConsoleAccountPublic,
    ConsoleAccountSecret,
    ConsoleAccountsPublic,
    DeployCommand,
    DeployConfigRequest,
    DeploymentConfig,
    DeployReport,
    DeviceDesiredUpdate,
    DeviceEnsureRequest,
    DeviceProfileUpdate,
    DevicePublic,
    DevicesPublic,
    PackageConfig,
)
from app.domains.shared.schemas import Message

router = APIRouter(tags=["remote-access"])
logger = logging.getLogger(__name__)


def _to_public(dev: RemoteAccessDevice) -> DevicePublic:
    data = DevicePublic.model_validate(dev)
    data.has_password = bool(dev.permanent_password)
    data.type_tag = service.hostname_type_tag(dev.hostname)
    data.readiness = service.readiness(dev)
    # only flag a real mismatch: we asked for the lockdown AND know (not
    # "maybe") that this edition can't enforce it
    data.applocker_mismatch = dev.desired_block_outgoing and dev.applocker_supported is False
    return data


# --------------------------------------------------------------------------- #
# managed devices                                                            #
# --------------------------------------------------------------------------- #
@router.get("/devices", response_model=DevicesPublic)
def list_devices(
    session: SessionDep,
    current_user: CurrentUser,
    q: str | None = Query(default=None),
    location: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    hostnames: str | None = Query(default=None, description="comma-separated exact hostnames"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> DevicesPublic:
    del current_user
    stmt = select(RemoteAccessDevice)
    count_stmt = select(func.count()).select_from(RemoteAccessDevice)
    if hostnames:
        names = [h.strip() for h in hostnames.split(",") if h.strip()]
        if not names:
            return DevicesPublic(data=[], count=0)
        cond = RemoteAccessDevice.hostname.in_(names)  # type: ignore[attr-defined]
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if q:
        like = f"%{q.strip()}%"
        cond = RemoteAccessDevice.hostname.ilike(like) | RemoteAccessDevice.rustdesk_id.ilike(like)  # type: ignore[attr-defined]
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if location:
        stmt, count_stmt = stmt.where(RemoteAccessDevice.location == location), count_stmt.where(
            RemoteAccessDevice.location == location
        )
    if source_kind:
        stmt, count_stmt = stmt.where(RemoteAccessDevice.source_kind == source_kind), count_stmt.where(
            RemoteAccessDevice.source_kind == source_kind
        )
    rows = session.exec(stmt.order_by(RemoteAccessDevice.hostname).offset(skip).limit(limit)).all()
    return DevicesPublic(data=[_to_public(r) for r in rows], count=session.exec(count_stmt).one())


@router.patch("/devices/{device_id}", response_model=DevicePublic, dependencies=[Depends(get_current_active_superuser)])
def update_device(device_id: uuid.UUID, payload: DeviceDesiredUpdate, session: SessionDep) -> DevicePublic:
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    # only these actually change what the rollout script writes to the
    # machine - managed/location changing does not make the live config stale
    changes = payload.model_dump(exclude_unset=True)
    stale_fields = {"desired_hidden", "desired_block_outgoing", "desired_unattended", "rustdesk_id"}
    for field, value in changes.items():
        setattr(dev, field, value)
    if stale_fields & changes.keys():
        service.mark_config_stale(dev)
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return _to_public(dev)


@router.post(
    "/devices/{device_id}/profile",
    response_model=DevicePublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def set_device_profile(device_id: uuid.UUID, payload: DeviceProfileUpdate, session: SessionDep) -> DevicePublic:
    """"client" (default - store kiosk, AppLocker-blocked, hidden) or "admin"
    (an engineer's own workstation - full normal RustDesk, visible, usable)."""
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    dev = service.apply_deploy_profile(session, dev, payload.profile)
    return _to_public(dev)


@router.post(
    "/devices/ensure", response_model=DevicePublic, dependencies=[Depends(get_current_active_superuser)]
)
def ensure_device(payload: DeviceEnsureRequest, session: SessionDep) -> DevicePublic:
    dev = service.ensure_device(
        session,
        hostname=payload.hostname,
        rustdesk_id=payload.rustdesk_id,
        permanent_password=payload.permanent_password,
    )
    return _to_public(dev)


@router.post(
    "/devices/{device_id}/rotate-password",
    response_model=DevicePublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def rotate_password(device_id: uuid.UUID, session: SessionDep) -> DevicePublic:
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    dev = service.rotate_password(session, dev)
    return _to_public(dev)


@router.get(
    "/devices/{device_id}/package",
    response_model=PackageConfig,
    dependencies=[Depends(get_current_active_superuser)],
)
def device_package(device_id: uuid.UUID, session: SessionDep) -> PackageConfig:
    """Config for an offline KSC package (no network path back to InfraScope)."""
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    return PackageConfig(**service.package_config(dev))


@router.post("/sync", response_model=Message, dependencies=[Depends(get_current_active_superuser)])
async def sync(session: SessionDep) -> Message:
    created = await run_in_threadpool(service.seed_from_inventory, session)
    result = await service.sync_from_console(session) if rustdesk_client.enabled() else {"peers_seen": 0}
    touched = await run_in_threadpool(service.refresh_status_from_inventory, session)
    return Message(
        message=(
            f"seeded {created} devices from inventory, saw {result['peers_seen']} console peers, "
            f"{touched} statuses from InfraScope polling"
        )
    )


# --------------------------------------------------------------------------- #
# console accounts                                                            #
# --------------------------------------------------------------------------- #
@router.get("/accounts", response_model=ConsoleAccountsPublic)
def list_accounts(session: SessionDep, current_user: CurrentUser) -> ConsoleAccountsPublic:
    del current_user
    rows = session.exec(
        select(RemoteAccessConsoleAccount).order_by(RemoteAccessConsoleAccount.username)
    ).all()
    return ConsoleAccountsPublic(
        data=[ConsoleAccountPublic.model_validate(r) for r in rows], count=len(rows)
    )


@router.post(
    "/accounts", response_model=ConsoleAccountSecret, dependencies=[Depends(get_current_active_superuser)]
)
async def create_account(payload: ConsoleAccountCreate, session: SessionDep) -> ConsoleAccountSecret:
    """Create a RustDesk console login for an engineer.

    The account joins the console group the shared address book is shared with,
    so the whole fleet appears in their client on first login. The password comes
    back once in this response and is not stored anywhere.
    """
    account, secret = await service.provision_account(
        session,
        username=payload.username,
        display_name=payload.display_name,
        email=payload.email,
        is_admin=payload.is_admin,
        password=payload.password,
        infrascope_user_id=payload.infrascope_user_id,
    )
    return ConsoleAccountSecret(
        account=ConsoleAccountPublic.model_validate(account), password=secret
    )


@router.post(
    "/accounts/{account_id}/reset-password",
    response_model=ConsoleAccountSecret,
    dependencies=[Depends(get_current_active_superuser)],
)
async def reset_account_password(
    account_id: uuid.UUID, payload: ConsoleAccountPasswordReset, session: SessionDep
) -> ConsoleAccountSecret:
    account = session.get(RemoteAccessConsoleAccount, account_id)
    if not account:
        raise not_found("Account not found")
    secret = await service.reset_account_password(session, account, payload.password)
    return ConsoleAccountSecret(
        account=ConsoleAccountPublic.model_validate(account), password=secret
    )


@router.post(
    "/accounts/{account_id}/active",
    response_model=ConsoleAccountPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
async def set_account_active(
    account_id: uuid.UUID, session: SessionDep, active: bool = Query(...)
) -> ConsoleAccountPublic:
    """Enable/disable a console login. Disabling rather than deleting: the console
    refuses to delete its last admin and its delete payload is undocumented."""
    account = session.get(RemoteAccessConsoleAccount, account_id)
    if not account:
        raise not_found("Account not found")
    account = await service.set_account_active(session, account, active)
    return ConsoleAccountPublic.model_validate(account)


@router.post(
    "/accounts/sync", response_model=Message, dependencies=[Depends(get_current_active_superuser)]
)
async def sync_accounts(session: SessionDep) -> Message:
    result = await service.sync_accounts(session)
    return Message(message=f"console accounts synced: {result['accounts_seen']}")


# --------------------------------------------------------------------------- #
# shared address book                                                         #
# --------------------------------------------------------------------------- #
@router.post("/address-book/sync", response_model=Message, dependencies=[Depends(get_current_active_superuser)])
async def address_book_sync(payload: AddressBookSyncRequest, session: SessionDep) -> Message:
    devices = service.resolve_scope(
        session,
        device_ids=payload.device_ids,
        location=payload.location,
        source_kind=payload.source_kind,
        all_managed=payload.device_ids is None,
    )
    if not devices:
        raise HTTPException(status_code=400, detail="address-book sync scope resolved to no devices")
    res = await service.push_shared_address_book(session, devices)
    return Message(
        message=(
            f"общая книга: добавлено {res['created']}, обновлено {res['updated']}, "
            f"ошибок {res['failed']}"
        )
    )


@router.get("/address-book/status", response_model=AddressBookStatus)
async def address_book_status(session: SessionDep, current_user: CurrentUser) -> AddressBookStatus:
    del current_user
    return AddressBookStatus(**await service.address_book_status(session))


# --------------------------------------------------------------------------- #
# console passthrough (InfraScope auth in front of the RustDesk console)      #
# --------------------------------------------------------------------------- #
@router.get("/console/connections")
async def console_connections(current_user: CurrentUser, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict]:
    del current_user
    return await rustdesk_client.list_connections(limit=limit)


@router.get("/console/users")
async def console_users(current_user: CurrentUser) -> list[dict]:
    del current_user
    return await rustdesk_client.list_users()


@router.get("/console/address-book")
async def console_address_book(current_user: CurrentUser) -> list[dict]:
    """The token account's *personal* book. The fleet lives in the shared book -
    see /address-book/status."""
    del current_user
    return await rustdesk_client.get_address_book()


# --------------------------------------------------------------------------- #
# rollout                                                                     #
# --------------------------------------------------------------------------- #
def _deploy_ready() -> bool:
    return bool(settings.RUSTDESK_DEPLOY_TOKEN.strip() and settings.RUSTDESK_PUBLIC_URL.strip())


def require_deploy_token(
    request: Request,
    x_infrascope_deploy_token: str | None = Header(default=None),
) -> None:
    """Auth for the endpoint script, which has no InfraScope session.

    A compare_digest check on a shared secret, and nothing at all when the secret
    is unset - an unconfigured install must not serve fleet passwords.
    """
    expected = settings.RUSTDESK_DEPLOY_TOKEN.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="rollout is not configured (RUSTDESK_DEPLOY_TOKEN)")
    if not x_infrascope_deploy_token or not hmac.compare_digest(x_infrascope_deploy_token, expected):
        logger.warning("rustdesk deploy call with a bad token from %s", request.client.host if request.client else "?")
        raise HTTPException(status_code=401, detail="invalid deploy token")


@router.get("/deploy/command", response_model=DeployCommand, dependencies=[Depends(get_current_active_superuser)])
def deploy_command() -> DeployCommand:
    """The line to paste into a KSC "run script" task, a GPO startup script, or a
    one-off `schtasks /S <host> /RU SYSTEM`."""
    return DeployCommand(
        command=deploy_script.deploy_command() if _deploy_ready() else "",
        bootstrap_url=f"{deploy_script.public_url()}/api/v1/remote-access/deploy/bootstrap.ps1",
        installer_filename=settings.RUSTDESK_INSTALLER_FILENAME,
        installer_version=settings.RUSTDESK_INSTALLER_VERSION,
        configured=_deploy_ready(),
    )


@router.post(
    "/devices/{device_id}/deploy",
    response_model=DevicePublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def request_deploy(device_id: uuid.UUID, session: SessionDep) -> DevicePublic:
    """Mark a device as awaiting rollout.

    Nothing is executed here: InfraScope never remote-executes on the fleet. The
    machine still has to run the bootstrap (KSC / GPO / schtasks); this only
    makes the wait visible and resets any previous failure.
    """
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    if not dev.permanent_password:
        dev.permanent_password = service.default_password()
    return _to_public(service.mark_deploy_requested(session, dev))


@router.get(
    "/deploy/bootstrap.ps1",
    response_class=PlainTextResponse,
    dependencies=[Depends(require_deploy_token)],
)
def deploy_bootstrap() -> PlainTextResponse:
    return PlainTextResponse(deploy_script.render_bootstrap(), media_type="text/plain; charset=utf-8")


@router.post(
    "/deploy/config", response_model=DeploymentConfig, dependencies=[Depends(require_deploy_token)]
)
def deploy_config(payload: DeployConfigRequest, session: SessionDep, request: Request) -> DeploymentConfig:
    """The endpoint asks what it should become.

    Only a known, managed device gets an answer - an unknown hostname must not be
    able to fish the fleet password out of an unconfigured row.
    """
    dev = session.exec(
        select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == payload.hostname.strip())
    ).first()
    if dev is None or not dev.managed:
        logger.warning(
            "rustdesk deploy config for unknown/unmanaged host %s from %s",
            payload.hostname,
            request.client.host if request.client else "?",
        )
        raise not_found("Device not found")
    logger.info(
        "rustdesk deploy config served for %s to %s",
        dev.hostname,
        request.client.host if request.client else "?",
    )
    return DeploymentConfig(**service.deployment_config(dev))


@router.get("/deploy/installer", dependencies=[Depends(require_deploy_token)])
def deploy_installer() -> FileResponse:
    """Serve the pinned installer from the server so endpoints need no internet."""
    name = os.path.basename(settings.RUSTDESK_INSTALLER_FILENAME)
    path = os.path.join(settings.RUSTDESK_PACKAGE_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=503,
            detail=f"installer {name} is not present in RUSTDESK_PACKAGE_DIR",
        )
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post("/deploy/report", response_model=Message, dependencies=[Depends(require_deploy_token)])
def deploy_report(payload: DeployReport, session: SessionDep) -> Message:
    """The endpoint says what it actually did. Stored verbatim, never inferred."""
    dev = service.apply_deploy_report(
        session,
        hostname=payload.hostname,
        state=payload.state,
        rustdesk_id=payload.rustdesk_id,
        version=payload.version,
        detail=payload.detail,
        os_edition=payload.os_edition,
        os_caption=payload.os_caption,
    )
    if dev is None:
        raise not_found("Device not found")
    return Message(message=f"{dev.hostname}: {dev.deploy_state}")

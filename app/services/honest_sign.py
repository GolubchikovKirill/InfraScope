from __future__ import annotations

import asyncio
import ipaddress
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.domains.integrations.schemas import HonestSignInitializePublic, HonestSignStatusPublic


@dataclass(frozen=True, slots=True)
class HonestSignTarget:
    host: str
    label: str


class HonestSignConfigurationError(RuntimeError):
    pass


def allowed_operator_emails() -> set[str]:
    return {
        item.strip().casefold()
        for item in settings.HONEST_SIGN_ALLOWED_EMAILS.split(",")
        if item.strip()
    }


def is_honest_sign_operator(email: str | None) -> bool:
    return bool(email) and email.strip().casefold() in allowed_operator_emails()


def configured_targets(raw: str | None = None) -> list[HonestSignTarget]:
    value = settings.HONEST_SIGN_TARGETS if raw is None else raw
    items = value.replace("\r", "\n").replace("\n", ",").split(",")
    targets: list[HonestSignTarget] = []
    seen: set[str] = set()
    for item in items:
        entry = item.strip()
        if not entry:
            continue
        host_text, separator, label_text = entry.partition("|")
        try:
            host = str(ipaddress.IPv4Address(host_text.strip()))
        except ipaddress.AddressValueError:
            continue
        if host in seen:
            continue
        seen.add(host)
        label = label_text.strip() if separator and label_text.strip() else "Касса"
        targets.append(HonestSignTarget(host=host, label=label[:128]))
    return targets


def get_configured_target(host: str) -> HonestSignTarget:
    try:
        normalized = str(ipaddress.IPv4Address(host.strip()))
    except ipaddress.AddressValueError as exc:
        raise KeyError(host) from exc
    for target in configured_targets():
        if target.host == normalized:
            return target
    raise KeyError(host)


def status_configuration_ready() -> bool:
    return bool(
        configured_targets()
        and settings.HONEST_SIGN_API_LOGIN.strip()
        and settings.HONEST_SIGN_API_PASSWORD.strip()
    )


def initialization_configuration_ready() -> bool:
    if not status_configuration_ready():
        return False
    try:
        uuid.UUID(settings.HONEST_SIGN_TOKEN.strip())
    except (ValueError, AttributeError):
        return False
    return True


def _require_status_configuration() -> None:
    if not configured_targets():
        raise HonestSignConfigurationError("Список касс Честного знака не настроен")
    if not settings.HONEST_SIGN_API_LOGIN.strip() or not settings.HONEST_SIGN_API_PASSWORD.strip():
        raise HonestSignConfigurationError("Логин или пароль Local Module не настроен")


def _require_initialization_configuration() -> None:
    _require_status_configuration()
    try:
        uuid.UUID(settings.HONEST_SIGN_TOKEN.strip())
    except (ValueError, AttributeError) as exc:
        raise HonestSignConfigurationError("Токен инициализации Local Module не настроен") from exc


def _checked_at() -> str:
    return datetime.now(UTC).isoformat()


def _client() -> httpx.AsyncClient:
    timeout = max(1.0, min(float(settings.HONEST_SIGN_TIMEOUT_SECONDS), 60.0))
    return httpx.AsyncClient(
        auth=httpx.BasicAuth(settings.HONEST_SIGN_API_LOGIN, settings.HONEST_SIGN_API_PASSWORD),
        timeout=httpx.Timeout(timeout),
        trust_env=False,
    )


async def _check_target(client: httpx.AsyncClient, target: HonestSignTarget) -> HonestSignStatusPublic:
    try:
        response = await client.get(f"http://{target.host}:{settings.HONEST_SIGN_PORT}/api/v2/status")
        if response.status_code != 200:
            return HonestSignStatusPublic(
                host=target.host,
                label=target.label,
                reachable=True,
                status=f"HTTP_{response.status_code}",
                ready=False,
                message=f"Local Module вернул HTTP {response.status_code}",
                checked_at=_checked_at(),
            )
        try:
            payload = response.json()
        except ValueError:
            return HonestSignStatusPublic(
                host=target.host,
                label=target.label,
                reachable=True,
                status="INVALID_RESPONSE",
                ready=False,
                message="Local Module вернул некорректный JSON",
                checked_at=_checked_at(),
            )
        status = str(payload.get("status") or "unknown")[:64]
        version_value = payload.get("version")
        version = str(version_value)[:64] if version_value is not None else None
        return HonestSignStatusPublic(
            host=target.host,
            label=target.label,
            reachable=True,
            status=status,
            version=version,
            ready=status.casefold() == "ready",
            checked_at=_checked_at(),
        )
    except httpx.TimeoutException:
        message = "Превышено время ожидания Local Module"
    except httpx.HTTPError:
        message = "Нет соединения с Local Module"
    return HonestSignStatusPublic(
        host=target.host,
        label=target.label,
        reachable=False,
        status="ERROR",
        ready=False,
        message=message,
        checked_at=_checked_at(),
    )


async def check_honest_sign_target(target: HonestSignTarget) -> HonestSignStatusPublic:
    _require_status_configuration()
    async with _client() as client:
        return await _check_target(client, target)


async def check_all_honest_sign_targets() -> list[HonestSignStatusPublic]:
    _require_status_configuration()
    targets = configured_targets()
    semaphore = asyncio.Semaphore(max(1, min(settings.HONEST_SIGN_MAX_CONCURRENCY, 32)))
    async with _client() as client:
        async def check_one(target: HonestSignTarget) -> HonestSignStatusPublic:
            async with semaphore:
                return await _check_target(client, target)

        return list(await asyncio.gather(*(check_one(target) for target in targets)))


async def initialize_honest_sign_target(target: HonestSignTarget) -> HonestSignInitializePublic:
    _require_initialization_configuration()
    async with _client() as client:
        initial = await _check_target(client, target)
        if not initial.reachable:
            return HonestSignInitializePublic(
                host=target.host,
                label=target.label,
                initial_status=initial.status,
                final_status=initial.status,
                result="ERROR",
                message=initial.message,
                checked_at=_checked_at(),
            )
        if initial.ready:
            return HonestSignInitializePublic(
                host=target.host,
                label=target.label,
                initial_status=initial.status,
                final_status=initial.status,
                result="ALREADY_READY",
                message="Модуль уже готов; повторная инициализация не выполнялась",
                checked_at=_checked_at(),
            )
        try:
            response = await client.post(
                f"http://{target.host}:{settings.HONEST_SIGN_PORT}/api/v2/init",
                json={"token": settings.HONEST_SIGN_TOKEN.strip()},
            )
        except httpx.TimeoutException:
            result, message = "INIT_FAILED", "Превышено время ожидания запроса инициализации"
        except httpx.HTTPError:
            result, message = "INIT_FAILED", "Нет соединения при запросе инициализации"
        else:
            if response.status_code != 200:
                message = (
                    "Local Module отклонил логин или пароль"
                    if response.status_code == 401
                    else f"Local Module вернул HTTP {response.status_code}"
                )
                result = "INIT_FAILED"
            else:
                wait_seconds = max(0.0, min(float(settings.HONEST_SIGN_STATUS_WAIT_SECONDS), 30.0))
                if wait_seconds:
                    await asyncio.sleep(wait_seconds)
                final = await _check_target(client, target)
                if final.ready:
                    result = "READY"
                elif final.status.casefold() == "initialization":
                    result = "INITIALIZING"
                else:
                    result = "REQUEST_ACCEPTED"
                return HonestSignInitializePublic(
                    host=target.host,
                    label=target.label,
                    initial_status=initial.status,
                    final_status=final.status,
                    result=result,
                    message=final.message or f"Статус после запроса: {final.status}",
                    checked_at=_checked_at(),
                )
        return HonestSignInitializePublic(
            host=target.host,
            label=target.label,
            initial_status=initial.status,
            final_status=initial.status,
            result=result,
            message=message,
            checked_at=_checked_at(),
        )

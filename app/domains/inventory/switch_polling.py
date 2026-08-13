from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from time import perf_counter

from sqlmodel import Session, select

from app.core.config import settings
from app.core.redis import get_redis
from app.domains.inventory.models import NetworkSwitch
from app.domains.shared.schemas import Message
from app.observability.metrics import (
    network_bulk_operation_duration_seconds,
    network_bulk_processed_total,
    set_device_counts,
    switch_ops_total,
)
from app.services.event_log import write_event_log
from app.services.mac_rediscovery import MacRediscoveryTarget, resolve_devices_by_mac
from app.services.ml_snapshots import write_switch_snapshot
from app.services.poll_resilience import apply_poll_outcome, is_circuit_open, poll_jitter_async
from app.services.snmp import get_snmp_mac
from app.services.switches import resolve_switch_provider
from app.services.switches.base import SwitchPollInfo

logger = logging.getLogger(__name__)

class SwitchNotFoundError(LookupError):
    pass


_REASON_LABELS = {
    "auth_rejected": "неверные учётные данные",
    "dns_failure": "не резолвится имя хоста",
    "timeout": "нет ответа (таймаут)",
    "connection_refused": "соединение отклонено",
    "network_unreachable": "путь до устройства недоступен",
    "no_response": "нет ответа по SNMP",
    "protocol_error": "ошибка протокола SSH",
    "other": "неизвестная причина",
}


def record_switch_status_change(session: Session, switch: NetworkSwitch, was_online: bool | None) -> None:
    if was_online is None or was_online == switch.is_online:
        return
    reason_suffix = ""
    if not switch.is_online and switch.reachability_reason:
        label = _REASON_LABELS.get(switch.reachability_reason, switch.reachability_reason)
        reason_suffix = f" ({label})"
    write_event_log(
        session,
        category="device",
        event_type="device_online" if switch.is_online else "device_offline",
        severity="info" if switch.is_online else "warning",
        device_kind="switch",
        device_name=switch.name,
        ip_address=switch.ip_address,
        message=f"Network device '{switch.name}' is now {'online' if switch.is_online else 'offline'}{reason_suffix}",
    )


def _subnet_of(ip: str) -> str:
    return ip.rsplit(".", 1)[0]


def _subnets_with_total_failure(
    results: list[tuple[NetworkSwitch, SwitchPollInfo | None, str | None, Exception | None]],
) -> set[str]:
    """Subnets where practically every switch stopped answering in one cycle.

    Same heuristic as printer_polling._subnets_with_total_failure, and the
    same motivation: a store's worth of switches does not go dark in the
    same poll cycle - the route to them does. This exact blind spot is what
    turned a Docker network misconfiguration into 32 individual "device
    offline" records instead of one "path to this subnet is down" warning,
    and cost three days to diagnose. When this fires, the cycle leaves those
    switches' state alone rather than guessing on evidence it doesn't have.
    """
    min_devices = max(settings.POLL_PATH_FAILURE_MIN_DEVICES, 2)
    ratio = min(max(settings.POLL_PATH_FAILURE_RATIO, 0.0), 1.0)

    by_subnet: dict[str, list[bool]] = {}
    for switch, info, _mac, exc in results:
        online = bool(info is not None and info.is_online and exc is None)
        by_subnet.setdefault(_subnet_of(switch.ip_address), []).append(online)

    suspect: set[str] = set()
    for subnet, outcomes in by_subnet.items():
        if len(outcomes) < min_devices:
            continue
        failed = sum(1 for online in outcomes if not online)
        if failed / len(outcomes) >= ratio:
            suspect.add(subnet)
    return suspect


def verify_switch_mac(switch: NetworkSwitch, current_mac: str | None) -> str | None:
    """Same convention as printer/media MAC verification: records the first
    MAC seen, flags a change as a mismatch worth a human look, and lets a
    None result (SNMP unreachable) pass through without overwriting a
    previously-known MAC.
    """
    if current_mac is None:
        return "unavailable"
    if not switch.mac_address:
        switch.mac_address = current_mac
        return "verified"
    if switch.mac_address.lower() == current_mac.lower():
        return "verified"
    return "mismatch"


def apply_switch_poll_info(
    switch: NetworkSwitch,
    info: SwitchPollInfo,
    *,
    effective_online: bool | None = None,
) -> None:
    switch.is_online = info.is_online if effective_online is None else effective_online
    switch.reachability_reason = None if switch.is_online else info.offline_reason
    switch.hostname = info.hostname or switch.hostname
    switch.model_info = info.model_info or switch.model_info
    switch.ios_version = info.ios_version or switch.ios_version
    switch.uptime = info.uptime or switch.uptime
    switch.last_polled_at = datetime.now(UTC)


def _fetch_switch_mac(switch: NetworkSwitch) -> str | None:
    try:
        return get_snmp_mac(switch.ip_address, switch.snmp_community_ro)
    except Exception as exc:
        logger.debug("SNMP MAC fetch failed for %s: %s", switch.name, exc)
        return None


async def poll_one_switch(
    switch: NetworkSwitch,
) -> tuple[NetworkSwitch, SwitchPollInfo | None, str | None, Exception | None]:
    try:
        await poll_jitter_async()
        provider = resolve_switch_provider(switch)
        info = await asyncio.to_thread(provider.poll_switch, switch)
        # MAC only matters while the switch is reachable enough to ask - and
        # only bother asking (extra SNMP round trip) when it is.
        mac = await asyncio.to_thread(_fetch_switch_mac, switch) if info.is_online else None
        return switch, info, mac, None
    except Exception as exc:
        return switch, None, None, exc


async def find_switch_ip_by_mac(session: Session, switch: NetworkSwitch) -> str | None:
    if not switch.mac_address:
        return None
    matches = await resolve_devices_by_mac(
        [
            MacRediscoveryTarget(
                device_kind="switch",
                entity_id=str(switch.id),
                name=switch.name,
                current_ip=switch.ip_address,
                mac_address=switch.mac_address,
            )
        ],
        session=session,
    )
    return matches[0].new_ip if matches else None


async def poll_single_switch_local(*, session: Session, switch_id: uuid.UUID) -> NetworkSwitch:
    switch = session.get(NetworkSwitch, switch_id)
    if not switch:
        raise SwitchNotFoundError("Switch not found")

    was_online = switch.is_online
    provider = resolve_switch_provider(switch)
    info = await asyncio.to_thread(provider.poll_switch, switch)

    if not info.is_online and switch.mac_address:
        new_ip = await find_switch_ip_by_mac(session, switch)
        if new_ip and new_ip != switch.ip_address:
            conflict = session.exec(
                select(NetworkSwitch).where(
                    NetworkSwitch.ip_address == new_ip,
                    NetworkSwitch.id != switch.id,
                )
            ).first()
            if not conflict:
                old_ip = switch.ip_address
                switch.ip_address = new_ip
                write_event_log(
                    session,
                    category="network",
                    event_type="ip_changed",
                    severity="warning",
                    device_kind="switch",
                    device_name=switch.name,
                    ip_address=new_ip,
                    message=f"Switch '{switch.name}' moved IP: {old_ip} -> {new_ip}",
                )
                provider = resolve_switch_provider(switch)
                info = await asyncio.to_thread(provider.poll_switch, switch)

    apply_switch_poll_info(switch, info)
    if info.is_online:
        switch.mac_status = verify_switch_mac(switch, await asyncio.to_thread(_fetch_switch_mac, switch))
    switch_ops_total.labels(operation="poll", result="online" if info.is_online else "offline").inc()
    record_switch_status_change(session, switch, was_online)
    write_switch_snapshot(session, switch, source="single_poll")
    session.add(switch)
    session.commit()
    session.refresh(switch)
    return switch


async def poll_all_switches_local(*, session: Session) -> Message:
    started = perf_counter()
    lock_key = "lock:poll-all:switches"
    lock_acquired = True
    try:
        redis = await get_redis()
        lock_acquired = bool(await redis.set(lock_key, "1", ex=320, nx=True))
    except Exception:
        lock_acquired = True

    switches = session.exec(select(NetworkSwitch)).all()
    set_device_counts(
        kind="switch",
        total=len(switches),
        online=sum(1 for switch in switches if switch.is_online),
    )
    if not lock_acquired:
        logger.info("Skipping duplicate poll-all request for switches: lock busy")
        return Message(message="Switch poll already in progress")

    try:
        poll_targets: list[NetworkSwitch] = []
        for switch in switches:
            if await is_circuit_open("switch", str(switch.id)):
                switch_ops_total.labels(operation="poll_all", result="skipped").inc()
                continue
            poll_targets.append(switch)

        semaphore = asyncio.Semaphore(max(1, settings.SWITCH_POLL_MAX_CONCURRENCY))

        async def _limited_poll(
            switch: NetworkSwitch,
        ) -> tuple[NetworkSwitch, SwitchPollInfo | None, str | None, Exception | None]:
            async with semaphore:
                return await poll_one_switch(switch)

        results = await asyncio.gather(*[_limited_poll(switch) for switch in poll_targets]) if poll_targets else []
        error_count = 0
        offline_with_mac: list[NetworkSwitch] = []

        suspect_subnets = _subnets_with_total_failure(results)
        for subnet in sorted(suspect_subnets):
            write_event_log(
                session,
                category="network",
                event_type="poll_path_suspect",
                severity="warning",
                device_kind="switch",
                device_name=f"{subnet}.0/24",
                ip_address=None,
                message=(
                    f"Опрос: почти все свитчи подсети {subnet}.0/24 перестали отвечать в одном "
                    "цикле - похоже на обрыв пути до подсети, а не на отказ каждого устройства. "
                    "Их состояние оставлено без изменений до следующего цикла."
                ),
            )
        if suspect_subnets:
            session.commit()

        for switch, info, current_mac, exc in results:
            if _subnet_of(switch.ip_address) in suspect_subnets:
                # Deliberately touch nothing - not the state, and not
                # last_polled_at either. Bumping the timestamp would make the
                # card read as freshly confirmed when this cycle actually
                # learned nothing about the switch.
                switch_ops_total.labels(operation="poll_all", result="path_suspect").inc()
                continue
            try:
                was_online = switch.is_online
                if exc:
                    raise exc
                if info is None:
                    raise RuntimeError("poll returned no data")

                effective_online = await apply_poll_outcome(
                    kind="switch",
                    entity_id=str(switch.id),
                    previous_effective_online=bool(switch.is_online),
                    probed_online=bool(info.is_online),
                    probed_error=False,
                )
                apply_switch_poll_info(switch, info, effective_online=effective_online)
                if effective_online:
                    switch.mac_status = verify_switch_mac(switch, current_mac)
                elif switch.mac_address:
                    offline_with_mac.append(switch)
                record_switch_status_change(session, switch, was_online)
                switch_ops_total.labels(operation="poll_all", result="online" if effective_online else "offline").inc()
                write_switch_snapshot(session, switch, source="bulk_poll")
                session.add(switch)
            except Exception as exc:
                logger.warning("Bulk switch poll failed for %s (%s): %s", switch.name, switch.ip_address, exc)
                write_event_log(
                    session,
                    category="system",
                    event_type="critical_poll_error",
                    severity="critical",
                    device_kind="switch",
                    device_name=switch.name,
                    ip_address=switch.ip_address,
                    message=f"Critical switch poll error for '{switch.name}': {exc}",
                )
                switch.is_online = await apply_poll_outcome(
                    kind="switch",
                    entity_id=str(switch.id),
                    previous_effective_online=bool(switch.is_online),
                    probed_online=False,
                    probed_error=True,
                )
                # "other" rather than a specific network/auth code: this branch
                # is an unexpected exception in the polling pipeline itself
                # (e.g. a bug), not a classified SSH/SNMP connection failure.
                switch.reachability_reason = None if switch.is_online else "other"
                switch.last_polled_at = datetime.now(UTC)
                write_switch_snapshot(session, switch, source="bulk_poll_error")
                session.add(switch)
                switch_ops_total.labels(operation="poll_all", result="error").inc()
                error_count += 1
                if switch.mac_address:
                    offline_with_mac.append(switch)

        await _relocate_offline_switches(session, offline_with_mac)

        session.commit()
        success_count = max(len(switches) - error_count, 0)
        network_bulk_processed_total.labels(operation="switch_poll_all", result="success").inc(success_count)
        if error_count:
            network_bulk_processed_total.labels(operation="switch_poll_all", result="error").inc(error_count)
        network_bulk_operation_duration_seconds.labels(operation="switch_poll_all").observe(
            max(perf_counter() - started, 0)
        )
        return Message(message="Switches polled")
    finally:
        if lock_acquired:
            try:
                redis = await get_redis()
                await redis.delete(lock_key)
            except Exception:
                pass


async def _relocate_offline_switches(session: Session, offline_with_mac: list[NetworkSwitch]) -> None:
    """Switches are usually statically addressed, so this fires rarely -
    but a DHCP reservation slipping or re-cabling does happen, and a switch
    stuck at a stale IP is worse than most devices going dark (it's the
    thing everything else - including AP auto-reboot - depends on).
    """
    if not offline_with_mac:
        return

    targets = [
        MacRediscoveryTarget(
            device_kind="switch",
            entity_id=str(switch.id),
            name=switch.name,
            current_ip=switch.ip_address,
            mac_address=switch.mac_address,
        )
        for switch in offline_with_mac
        if switch.mac_address
    ]
    matches = await resolve_devices_by_mac(targets, session=session)
    matches_by_id = {match.target.entity_id: match for match in matches}

    for switch in offline_with_mac:
        match = matches_by_id.get(str(switch.id))
        new_ip = match.new_ip if match else None
        if not new_ip or new_ip == switch.ip_address:
            continue

        conflict = session.exec(
            select(NetworkSwitch).where(
                NetworkSwitch.ip_address == new_ip,
                NetworkSwitch.id != switch.id,
            )
        ).first()
        if conflict:
            continue

        old_ip = switch.ip_address
        switch.ip_address = new_ip
        logger.info("Auto-relocated switch %s: %s -> %s (MAC %s)", switch.name, old_ip, new_ip, switch.mac_address)
        write_event_log(
            session,
            category="network",
            event_type="ip_changed",
            severity="warning",
            device_kind="switch",
            device_name=switch.name,
            ip_address=new_ip,
            message=f"Switch '{switch.name}' moved IP: {old_ip} -> {new_ip}",
        )
        session.add(switch)

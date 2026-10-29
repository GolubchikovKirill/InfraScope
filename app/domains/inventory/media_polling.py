from __future__ import annotations

import asyncio
import ipaddress
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import cast

from sqlmodel import Session, select

from app.core.config import settings
from app.core.redis import REDIS_ERRORS, get_redis
from app.domains.inventory.models import MediaPlayer
from app.domains.inventory.reachability import build_dns_search_suffixes, probe_tcp_endpoint_async, resolve_hostname
from app.domains.inventory.schemas import MediaPlayersPublic
from app.domains.inventory.schemas.media_players import MediaPlayerPublic
from app.observability.metrics import (
    media_player_ops_total,
    media_player_polls_total,
    network_bulk_operation_duration_seconds,
    network_bulk_processed_total,
    set_device_counts,
)
from app.services.cache import invalidate_entity_cache
from app.services.device_poll import DeviceStatus, arp_mac_for_ip, poll_device
from app.services.event_log import write_event_log
from app.services.mac_rediscovery import MacRediscoveryTarget, normalize_mac, resolve_devices_by_mac
from app.services.ml_snapshots import write_media_player_snapshot
from app.services.poll_resilience import apply_poll_outcome, is_circuit_open, poll_jitter_async

logger = logging.getLogger(__name__)

#: iconbit players expose their control API here and nothing else useful.
ICONBIT_PORT = 8081
ICONBIT_PROBE_TIMEOUT = 2.5


class MediaPlayerNotFoundError(LookupError):
    pass


@dataclass
class LightMediaPollResult:
    is_online: bool
    hostname: str | None = None
    os_info: str | None = None
    uptime: str | None = None
    open_ports: list[int] | None = None
    mac_address: str | None = None
    #: The probe never reached the player (dead name or route) rather than
    #: being refused by it. MediaPlayer has no reachability_reason column to
    #: store the full verdict, so only the bit the circuit breaker needs is
    #: carried here.
    path_failure: bool = False


def _media_player_mac_target(player: MediaPlayer) -> MacRediscoveryTarget:
    return MacRediscoveryTarget(
        device_kind="media_player",
        entity_id=str(player.id),
        name=player.name,
        current_ip=player.ip_address,
        mac_address=player.mac_address or "",
    )


async def invalidate_media_player_cache() -> None:
    await invalidate_entity_cache("media_players")


def record_media_player_status_change(session: Session, player: MediaPlayer, was_online: bool | None) -> None:
    if was_online is None or was_online == player.is_online:
        return
    write_event_log(
        session,
        category="device",
        event_type="device_online" if player.is_online else "device_offline",
        severity="info" if player.is_online else "warning",
        device_kind="media_player",
        device_name=player.name,
        ip_address=player.ip_address,
        message=f"Media player '{player.name}' is now {'online' if player.is_online else 'offline'}",
    )


async def _probe_iconbit(ip_address: str) -> LightMediaPollResult:
    probe = await probe_tcp_endpoint_async(
        ip_address,
        port=ICONBIT_PORT,
        timeout=ICONBIT_PROBE_TIMEOUT,
        probe_scope="media_players",
    )
    return LightMediaPollResult(
        is_online=probe.is_online,
        open_ports=[ICONBIT_PORT] if probe.is_online else [],
        path_failure=probe.is_path_failure,
    )


async def poll_one_media_player_async(
    player: MediaPlayer,
    *,
    port_scan_semaphore: asyncio.Semaphore,
) -> tuple[str, DeviceStatus | LightMediaPollResult | None]:
    """Poll one media player in the caller's event loop.

    The old batch wrapped this synchronous helper in many threads, each of
    which created an independent event loop.  Keeping the whole batch in one
    loop makes the shared TCP limit valid and avoids false offline results
    caused by event-loop-bound asyncio primitives.
    """
    try:
        # Was asyncio.to_thread(poll_jitter_sync): a pool thread held just to sleep
        await poll_jitter_async()
        if player.device_type == "iconbit":
            return player.ip_address, await _probe_iconbit(player.ip_address)
        result = await poll_device(player.ip_address, port_scan_semaphore=port_scan_semaphore)
        return player.ip_address, result
    except Exception as exc:
        logger.warning("Poll failed for media player %s: %s", player.ip_address, exc)
        return player.ip_address, None


def apply_media_poll_result(player: MediaPlayer, result: DeviceStatus | LightMediaPollResult | None) -> None:
    if result is None or not result.is_online:
        player.is_online = False
        return

    player.is_online = True
    if result.hostname:
        player.hostname = result.hostname
    if result.os_info:
        player.os_info = result.os_info
    if result.uptime:
        player.uptime = result.uptime
    player.open_ports = ",".join(str(port) for port in result.open_ports) if result.open_ports else None
    if result.mac_address and not player.mac_address:
        player.mac_address = result.mac_address


async def poll_single_media_player_local(*, session: Session, player_id: uuid.UUID) -> MediaPlayer:
    player = session.get(MediaPlayer, player_id)
    if not player:
        raise MediaPlayerNotFoundError("Media player not found")

    was_online = player.is_online
    _, result = await poll_one_media_player_async(player, port_scan_semaphore=asyncio.Semaphore(64))
    apply_media_poll_result(player, result)
    media_player_polls_total.labels(
        mode="single",
        device_type=player.device_type,
        result="online" if player.is_online else "offline",
    ).inc()

    if player.is_online:
        await _backfill_missing_macs([player])
    else:
        await _relocate_media_players(session, [player], mode="single", snapshot_source="single_poll_relocated")

    player.last_polled_at = datetime.now(UTC)
    record_media_player_status_change(session, player, was_online)
    write_media_player_snapshot(session, player, source="single_poll")
    session.add(player)
    session.commit()
    session.refresh(player)
    await invalidate_media_player_cache()
    return player


async def poll_all_media_players_local(*, session: Session, device_type: str | None = None) -> MediaPlayersPublic:
    started = perf_counter()
    lock_key = f"lock:poll-all:media:{device_type or 'all'}"
    lock_acquired = True
    try:
        redis = await get_redis()
        lock_acquired = bool(await redis.set(lock_key, "1", ex=320, nx=True))
    except REDIS_ERRORS as exc:
        # Fail open: a Redis outage must not stop polling; the worst case is a duplicate poll.
        logger.warning("Poll lock %s unavailable, polling without it: %s", lock_key, exc)
        lock_acquired = True

    statement = select(MediaPlayer)
    if device_type:
        statement = statement.where(MediaPlayer.device_type == device_type)
    players = session.exec(statement).all()
    set_device_counts(
        kind="media_player",
        total=len(players),
        online=sum(1 for player in players if player.is_online),
    )
    if not lock_acquired:
        logger.info("Skipping duplicate poll-all request for media players (%s): lock busy", device_type or "all")
        return MediaPlayersPublic(data=cast(list[MediaPlayerPublic], players), count=len(players))
    if not players:
        return MediaPlayersPublic(data=[], count=0)

    try:
        poll_targets: list[MediaPlayer] = []
        skipped_ids: set[uuid.UUID] = set()
        for player in players:
            if await is_circuit_open("media_player", str(player.id)):
                media_player_polls_total.labels(mode="all", device_type=player.device_type, result="skipped").inc()
                skipped_ids.add(player.id)
                continue
            poll_targets.append(player)

        results = await poll_media_player_batch(poll_targets) if poll_targets else {}
        offline: list[MediaPlayer] = []
        for player in players:
            if player.id in skipped_ids:
                # An open circuit stops probing the old address, not looking
                # for the new one - a player that took a new lease is exactly
                # what trips the breaker, and would otherwise stay lost for as
                # long as the breaker keeps reopening.
                if not player.is_online:
                    offline.append(player)
                session.add(player)
                continue

            result = results.get(player.ip_address)
            previous_online = bool(player.is_online)
            raw_online = bool(result and result.is_online)
            effective_online = await apply_poll_outcome(
                kind="media_player",
                entity_id=str(player.id),
                previous_effective_online=previous_online,
                probed_online=raw_online,
                probed_error=result is None or getattr(result, "path_failure", False),
            )
            apply_media_poll_result(player, result)
            player.is_online = effective_online
            media_player_polls_total.labels(
                mode="all",
                device_type=player.device_type,
                result="online" if effective_online else "offline",
            ).inc()
            if not effective_online:
                offline.append(player)
            player.last_polled_at = datetime.now(UTC)
            record_media_player_status_change(session, player, previous_online)
            write_media_player_snapshot(session, player, source="bulk_poll")
            session.add(player)

        await _backfill_missing_macs([player for player in players if player.is_online])
        await _relocate_media_players(session, offline, mode="all", snapshot_source="bulk_poll_relocated")

        session.commit()
        success_count = sum(1 for player in players if player.is_online)
        network_bulk_processed_total.labels(operation="media_poll_all", result="success").inc(success_count)
        network_bulk_processed_total.labels(operation="media_poll_all", result="offline").inc(
            max(len(players) - success_count, 0)
        )
        network_bulk_operation_duration_seconds.labels(operation="media_poll_all").observe(
            max(perf_counter() - started, 0)
        )

        result_statement = select(MediaPlayer)
        if device_type:
            result_statement = result_statement.where(MediaPlayer.device_type == device_type)
        all_players = session.exec(result_statement).all()
        set_device_counts(
            kind="media_player",
            total=len(all_players),
            online=sum(1 for player in all_players if player.is_online),
        )

        await invalidate_media_player_cache()
        return MediaPlayersPublic(data=cast(list[MediaPlayerPublic], all_players), count=len(all_players))
    finally:
        if lock_acquired:
            try:
                redis = await get_redis()
                await redis.delete(lock_key)
            except REDIS_ERRORS as exc:
                # The lock expires on its own (ex=320); nothing else to do.
                logger.debug("Could not release poll lock %s: %s", lock_key, exc)


async def poll_media_player_batch(
    players: list[MediaPlayer],
) -> dict[str, DeviceStatus | LightMediaPollResult | None]:
    """Poll a fleet in one event loop with bounded device and TCP concurrency."""
    if not players:
        return {}

    device_semaphore = asyncio.Semaphore(max(1, min(settings.MEDIA_POLL_MAX_WORKERS, len(players))))
    port_scan_semaphore = asyncio.Semaphore(64)

    async def _poll(player: MediaPlayer) -> tuple[str, DeviceStatus | LightMediaPollResult | None]:
        async with device_semaphore:
            return await poll_one_media_player_async(player, port_scan_semaphore=port_scan_semaphore)

    pairs = await asyncio.gather(*(_poll(player) for player in players))
    return dict(pairs)


async def rediscover_media_players_local(*, session: Session) -> MediaPlayersPublic:
    started = perf_counter()
    # A player answering at its address has not moved; looking for it anyway
    # would only buy a ping sweep of every subnet.
    players = [
        player
        for player in session.exec(select(MediaPlayer)).all()
        if not player.is_online and (player.mac_address or _dns_name(player))
    ]
    updated = await _relocate_media_players(session, players, mode="rediscover", snapshot_source="rediscover")
    if updated:
        session.commit()
        await invalidate_media_player_cache()

    logger.info("Rediscovery complete: %d/%d devices updated", updated, len(players))
    media_player_ops_total.labels(operation="rediscover", result="success").inc()
    network_bulk_processed_total.labels(operation="media_rediscover", result="success").inc(updated)
    network_bulk_processed_total.labels(operation="media_rediscover", result="unchanged").inc(
        max(len(players) - updated, 0)
    )
    network_bulk_operation_duration_seconds.labels(operation="media_rediscover").observe(
        max(perf_counter() - started, 0)
    )
    all_players = session.exec(select(MediaPlayer)).all()
    return MediaPlayersPublic(data=cast(list[MediaPlayerPublic], all_players), count=len(all_players))


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _dns_name(player: MediaPlayer) -> str | None:
    """The name the player registers in DNS. Nettops are Windows machines that
    update their own record on every new lease (VNA-MUZ-901); iconbit/twix run
    Android and register none. Some rows were entered with that name typed
    into the IP field, which counts too."""
    if player.hostname and player.hostname.strip():
        return player.hostname.strip()
    if player.ip_address and not _is_ip_address(player.ip_address):
        return player.ip_address
    return None


def _ip_taken(session: Session, player: MediaPlayer, ip_address: str) -> bool:
    other = session.exec(
        select(MediaPlayer).where(MediaPlayer.ip_address == ip_address, MediaPlayer.id != player.id)
    ).first()
    return other is not None


def _record_move(session: Session, player: MediaPlayer, old_ip: str, new_ip: str, how: str) -> None:
    logger.info("Media player %s moved: %s -> %s (%s)", player.name, old_ip, new_ip, how)
    write_event_log(
        session,
        category="network",
        event_type="ip_changed",
        severity="warning",
        device_kind="media_player",
        device_name=player.name,
        ip_address=new_ip,
        message=f"Media player '{player.name}' moved IP: {old_ip} -> {new_ip} ({how})",
    )


async def _backfill_missing_macs(players: list[MediaPlayer]) -> None:
    """Fill in the MAC of reachable players that have none on record.

    A poll that just reached a player leaves it in the ARP table, so this costs
    no extra traffic. Without a MAC an iconbit could never be found again after
    a new lease, and a nettop only by its DNS name.
    """
    for player in players:
        if player.mac_address or not _is_ip_address(player.ip_address):
            continue
        if mac := normalize_mac(await asyncio.to_thread(arp_mac_for_ip, player.ip_address)):
            player.mac_address = mac


async def _relocate_by_dns(session: Session, player: MediaPlayer, *, mode: str, snapshot_source: str) -> bool:
    name = _dns_name(player)
    if not name:
        return False
    new_ip = await asyncio.to_thread(
        resolve_hostname,
        name,
        dns_search_suffixes=build_dns_search_suffixes(settings.DNS_SEARCH_SUFFIXES, settings.DOMAIN),
        dns_server=settings.DNS_SERVER,
    )
    if not new_ip or new_ip == player.ip_address or _ip_taken(session, player, new_ip):
        return False

    # A DNS record can outlive the lease it was made for: move only once the
    # player actually answers at the new address.
    old_ip = player.ip_address
    player.ip_address = new_ip
    _, result = await poll_one_media_player_async(player, port_scan_semaphore=asyncio.Semaphore(64))
    if result is None or not result.is_online:
        player.ip_address = old_ip
        return False

    apply_media_poll_result(player, result)
    # Found by name, so the MAC answering there is this player's own; the one
    # on record may be wrong (and is then why the MAC search kept missing it).
    if mac := normalize_mac(await asyncio.to_thread(arp_mac_for_ip, new_ip)):
        player.mac_address = mac
    _record_move(session, player, old_ip, new_ip, f"DNS {name}")
    media_player_polls_total.labels(mode=mode, device_type=player.device_type, result="online").inc()
    player.last_polled_at = datetime.now(UTC)
    write_media_player_snapshot(session, player, source=snapshot_source)
    session.add(player)
    return True


async def _relocate_media_players(
    session: Session, players: list[MediaPlayer], *, mode: str, snapshot_source: str
) -> int:
    """Look for players that are no longer at their recorded address.

    By DNS name first (nettops), then by MAC for the rest - the switches' ARP
    tables, then the host's own after a ping sweep. Returns how many moved.
    """
    if not players:
        return 0
    logger.info("Looking for %d media players at a new address...", len(players))

    moved = 0
    by_mac: list[MediaPlayer] = []
    for player in players:
        if await _relocate_by_dns(session, player, mode=mode, snapshot_source=snapshot_source):
            moved += 1
        elif player.mac_address:
            by_mac.append(player)
    if not by_mac:
        return moved

    matches = await resolve_devices_by_mac([_media_player_mac_target(player) for player in by_mac], session=session)
    matches_by_id = {match.target.entity_id: match for match in matches}
    for player in by_mac:
        match = matches_by_id.get(str(player.id))
        new_ip = match.new_ip if match else None
        if not new_ip or new_ip == player.ip_address or _ip_taken(session, player, new_ip):
            continue

        old_ip = player.ip_address
        player.ip_address = new_ip
        _record_move(session, player, old_ip, new_ip, f"MAC {player.mac_address}")
        moved += 1
        _, result = await poll_one_media_player_async(player, port_scan_semaphore=asyncio.Semaphore(64))
        apply_media_poll_result(player, result)
        media_player_polls_total.labels(
            mode=mode,
            device_type=player.device_type,
            result="online" if player.is_online else "offline",
        ).inc()
        player.last_polled_at = datetime.now(UTC)
        write_media_player_snapshot(session, player, source=snapshot_source)
        session.add(player)
    return moved

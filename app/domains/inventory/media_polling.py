from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from sqlmodel import Session, select

from app.core.config import settings
from app.core.redis import get_redis
from app.domains.inventory.models import MediaPlayer
from app.domains.inventory.schemas import MediaPlayersPublic
from app.observability.metrics import (
    media_player_ops_total,
    media_player_polls_total,
    network_bulk_operation_duration_seconds,
    network_bulk_processed_total,
    set_device_counts,
)
from app.services.cache import invalidate_entity_cache
from app.services.device_poll import poll_device_sync
from app.services.event_log import write_event_log
from app.services.mac_rediscovery import MacRediscoveryTarget, resolve_devices_by_mac
from app.services.ml_snapshots import write_media_player_snapshot
from app.services.ping import check_port
from app.services.poll_resilience import apply_poll_outcome, is_circuit_open, poll_jitter_sync

logger = logging.getLogger(__name__)

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


def poll_one_media_player(player: MediaPlayer) -> tuple[str, object | None]:
    try:
        poll_jitter_sync()
        if player.device_type == "iconbit":
            is_online = check_port(player.ip_address, port=8081, timeout=2.5)
            return player.ip_address, LightMediaPollResult(is_online=is_online, open_ports=[8081] if is_online else [])
        result = poll_device_sync(player.ip_address)
        return player.ip_address, result
    except Exception as exc:
        logger.warning("Poll failed for media player %s: %s", player.ip_address, exc)
        return player.ip_address, None


def apply_media_poll_result(player: MediaPlayer, result) -> None:
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
    _, result = await asyncio.to_thread(poll_one_media_player, player)
    apply_media_poll_result(player, result)
    media_player_polls_total.labels(
        mode="single",
        device_type=player.device_type,
        result="online" if player.is_online else "offline",
    ).inc()

    if not player.is_online and player.mac_address:
        matches = await resolve_devices_by_mac([_media_player_mac_target(player)], session=session)
        new_ip = matches[0].new_ip if matches else None
        if new_ip and new_ip != player.ip_address:
            conflict = session.exec(
                select(MediaPlayer).where(
                    MediaPlayer.ip_address == new_ip,
                    MediaPlayer.id != player.id,
                )
            ).first()
            if conflict:
                new_ip = None
        if new_ip and new_ip != player.ip_address:
            logger.info(
                "Device %s moved: %s -> %s (MAC %s)",
                player.name,
                player.ip_address,
                new_ip,
                player.mac_address,
            )
            old_ip = player.ip_address
            player.ip_address = new_ip
            write_event_log(
                session,
                category="network",
                event_type="ip_changed",
                severity="warning",
                device_kind="media_player",
                device_name=player.name,
                ip_address=new_ip,
                message=f"Media player '{player.name}' moved IP: {old_ip} -> {new_ip}",
            )
            _, result = await asyncio.to_thread(poll_one_media_player, player)
            apply_media_poll_result(player, result)
            media_player_polls_total.labels(
                mode="single",
                device_type=player.device_type,
                result="online" if player.is_online else "offline",
            ).inc()

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
        lock_acquired = bool(await redis.set(lock_key, "1", ex=45, nx=True))
    except Exception:
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
        return MediaPlayersPublic(data=players, count=len(players))
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

        results = poll_media_player_batch(poll_targets) if poll_targets else {}
        offline_with_mac: list[MediaPlayer] = []
        for player in players:
            if player.id in skipped_ids:
                session.add(player)
                continue

            result = results.get(player.ip_address)
            previous_online = player.is_online
            raw_online = bool(result and result.is_online)
            effective_online = await apply_poll_outcome(
                kind="media_player",
                entity_id=str(player.id),
                previous_effective_online=previous_online,
                probed_online=raw_online,
                probed_error=result is None,
            )
            apply_media_poll_result(player, result)
            player.is_online = effective_online
            media_player_polls_total.labels(
                mode="all",
                device_type=player.device_type,
                result="online" if effective_online else "offline",
            ).inc()
            if (not effective_online) and player.mac_address:
                offline_with_mac.append(player)
            player.last_polled_at = datetime.now(UTC)
            record_media_player_status_change(session, player, previous_online)
            write_media_player_snapshot(session, player, source="bulk_poll")
            session.add(player)

        await _relocate_offline_media_players(session, offline_with_mac)

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
        return MediaPlayersPublic(data=all_players, count=len(all_players))
    finally:
        if lock_acquired:
            try:
                redis = await get_redis()
                await redis.delete(lock_key)
            except Exception:
                pass


def poll_media_player_batch(players: list[MediaPlayer]) -> dict[str, object | None]:
    results: dict[str, object | None] = {}
    max_workers = max(1, min(settings.MEDIA_POLL_MAX_WORKERS, len(players)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(poll_one_media_player, player): player.ip_address for player in players}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                _, result = future.result()
            except Exception as exc:
                logger.warning("Poll failed for %s: %s", ip, exc)
                result = None
            results[ip] = result
    return results


async def rediscover_media_players_local(*, session: Session) -> MediaPlayersPublic:
    started = perf_counter()
    players = session.exec(select(MediaPlayer).where(MediaPlayer.mac_address.isnot(None))).all()
    if not players:
        return MediaPlayersPublic(data=[], count=0)

    updated = 0
    matches = await resolve_devices_by_mac(
        [_media_player_mac_target(player) for player in players], session=session
    )
    matches_by_id = {match.target.entity_id: match for match in matches}
    for player in players:
        match = matches_by_id.get(str(player.id))
        new_ip = match.new_ip if match else None
        if new_ip and new_ip != player.ip_address:
            conflict = session.exec(
                select(MediaPlayer).where(
                    MediaPlayer.ip_address == new_ip,
                    MediaPlayer.id != player.id,
                )
            ).first()
            if conflict:
                continue
            logger.info(
                "Rediscovery: %s moved %s -> %s (MAC %s)",
                player.name,
                player.ip_address,
                new_ip,
                player.mac_address,
            )
            old_ip = player.ip_address
            player.ip_address = new_ip
            updated += 1
            write_event_log(
                session,
                category="network",
                event_type="ip_changed",
                severity="warning",
                device_kind="media_player",
                device_name=player.name,
                ip_address=new_ip,
                message=f"Media player '{player.name}' moved IP: {old_ip} -> {new_ip}",
            )
            _, result = await asyncio.to_thread(poll_one_media_player, player)
            apply_media_poll_result(player, result)
            player.last_polled_at = datetime.now(UTC)
            write_media_player_snapshot(session, player, source="rediscover")
            session.add(player)

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
    return MediaPlayersPublic(data=all_players, count=len(all_players))


async def _relocate_offline_media_players(session: Session, offline_with_mac: list[MediaPlayer]) -> None:
    if not offline_with_mac:
        return

    logger.info("Trying MAC rediscovery for %d offline devices...", len(offline_with_mac))
    matches = await resolve_devices_by_mac(
        [_media_player_mac_target(player) for player in offline_with_mac], session=session
    )
    matches_by_id = {match.target.entity_id: match for match in matches}
    for player in offline_with_mac:
        match = matches_by_id.get(str(player.id))
        new_ip = match.new_ip if match else None
        if not new_ip or new_ip == player.ip_address:
            continue
        conflict = session.exec(
            select(MediaPlayer).where(
                MediaPlayer.ip_address == new_ip,
                MediaPlayer.id != player.id,
            )
        ).first()
        if conflict:
            continue

        logger.info(
            "Device %s moved: %s -> %s (MAC %s)",
            player.name,
            player.ip_address,
            new_ip,
            player.mac_address,
        )
        old_ip = player.ip_address
        player.ip_address = new_ip
        write_event_log(
            session,
            category="network",
            event_type="ip_changed",
            severity="warning",
            device_kind="media_player",
            device_name=player.name,
            ip_address=new_ip,
            message=f"Media player '{player.name}' moved IP: {old_ip} -> {new_ip}",
        )
        _, result = await asyncio.to_thread(poll_one_media_player, player)
        apply_media_poll_result(player, result)
        media_player_polls_total.labels(
            mode="all",
            device_type=player.device_type,
            result="online" if player.is_online else "offline",
        ).inc()
        player.last_polled_at = datetime.now(UTC)
        write_media_player_snapshot(session, player, source="bulk_poll_relocated")
        session.add(player)

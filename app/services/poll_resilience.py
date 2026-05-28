import asyncio
import random
import time
from dataclasses import dataclass

from app.core.config import settings
from app.core.redis import get_redis
from app.observability.metrics import poll_resilience_events_total


@dataclass
class PollDecision:
    effective_online: bool
    event: str
    failures: int
    circuit_failures: int


def _to_int(value: str | bytes | None, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def decide_poll_state(
    *,
    previous_effective_online: bool,
    probed_online: bool,
    probed_error: bool,
    failures: int,
    circuit_failures: int,
    offline_confirmations: int,
    circuit_failure_threshold: int,
) -> PollDecision:
    if probed_online:
        event = "recovered" if failures > 0 or circuit_failures > 0 else "online"
        return PollDecision(effective_online=True, event=event, failures=0, circuit_failures=0)

    next_failures = failures + 1
    next_circuit_failures = circuit_failures + (1 if probed_error else 0)
    if not probed_error and next_circuit_failures > 0:
        next_circuit_failures -= 1

    if previous_effective_online and next_failures < max(offline_confirmations, 1):
        return PollDecision(
            effective_online=True,
            event="offline_pending_confirmation",
            failures=next_failures,
            circuit_failures=next_circuit_failures,
        )

    event = "offline_confirmed"
    if next_circuit_failures >= max(circuit_failure_threshold, 1):
        event = "circuit_opened"
    return PollDecision(
        effective_online=False,
        event=event,
        failures=next_failures,
        circuit_failures=next_circuit_failures,
    )


async def poll_jitter_async() -> None:
    jitter_max_ms = max(settings.POLL_JITTER_MAX_MS, 0)
    if jitter_max_ms <= 0:
        return
    await asyncio.sleep(random.uniform(0.0, jitter_max_ms / 1000.0))


def poll_jitter_sync() -> None:
    jitter_max_ms = max(settings.POLL_JITTER_MAX_MS, 0)
    if jitter_max_ms <= 0:
        return
    time.sleep(random.uniform(0.0, jitter_max_ms / 1000.0))


async def is_circuit_open(kind: str, entity_id: str) -> bool:
    key = f"poll:resilience:{kind}:{entity_id}"
    try:
        r = await get_redis()
        open_until = _to_int(await r.hget(key, "circuit_open_until"), 0)
        if open_until > int(time.time()):
            poll_resilience_events_total.labels(kind=kind, event="circuit_skip").inc()
            return True
    except Exception:
        return False
    return False


async def apply_poll_outcome(
    *,
    kind: str,
    entity_id: str,
    previous_effective_online: bool,
    probed_online: bool,
    probed_error: bool,
) -> bool:
    key = f"poll:resilience:{kind}:{entity_id}"
    ttl = max(settings.POLL_RESILIENCE_STATE_TTL_SECONDS, 300)
    now_ts = int(time.time())

    failures = 0
    circuit_failures = 0
    try:
        r = await get_redis()
        state = await r.hgetall(key)
        failures = _to_int(state.get(b"failures") or state.get("failures"), 0)
        circuit_failures = _to_int(state.get(b"circuit_failures") or state.get("circuit_failures"), 0)
    except Exception:
        r = None

    decision = decide_poll_state(
        previous_effective_online=previous_effective_online,
        probed_online=probed_online,
        probed_error=probed_error,
        failures=failures,
        circuit_failures=circuit_failures,
        offline_confirmations=settings.POLL_OFFLINE_CONFIRMATIONS,
        circuit_failure_threshold=settings.POLL_CIRCUIT_FAILURE_THRESHOLD,
    )
    poll_resilience_events_total.labels(kind=kind, event=decision.event).inc()

    if r is not None:
        payload: dict[str, str | int] = {
            "failures": decision.failures,
            "circuit_failures": decision.circuit_failures,
            "effective_online": 1 if decision.effective_online else 0,
            "updated_at": now_ts,
        }
        if decision.event == "circuit_opened":
            payload["circuit_open_until"] = now_ts + max(settings.POLL_CIRCUIT_OPEN_SECONDS, 5)
        elif probed_online:
            payload["circuit_open_until"] = 0
        try:
            await r.hset(key, mapping=payload)
            await r.expire(key, ttl)
        except Exception:
            pass

    return decision.effective_online

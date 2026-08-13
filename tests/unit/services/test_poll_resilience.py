import pytest

from app.services.poll_resilience import _circuit_open_seconds, apply_poll_outcome, decide_poll_state


def test_circuit_open_seconds_doubles_per_failure_past_threshold():
    """The bug this exists to prevent: a flat window is a no-op against a
    15-minute poll cadence, since it always expires long before the next
    cycle even runs."""
    assert _circuit_open_seconds(circuit_failures=4, threshold=4, base_seconds=45, max_seconds=3600) == 45
    assert _circuit_open_seconds(circuit_failures=5, threshold=4, base_seconds=45, max_seconds=3600) == 90
    assert _circuit_open_seconds(circuit_failures=6, threshold=4, base_seconds=45, max_seconds=3600) == 180
    assert _circuit_open_seconds(circuit_failures=7, threshold=4, base_seconds=45, max_seconds=3600) == 360


def test_circuit_open_seconds_caps_at_max():
    assert _circuit_open_seconds(circuit_failures=50, threshold=4, base_seconds=45, max_seconds=3600) == 3600


def test_circuit_open_seconds_never_below_base():
    """A device right at the threshold (not yet overshooting it) still gets
    at least the base window, not zero."""
    assert _circuit_open_seconds(circuit_failures=1, threshold=4, base_seconds=45, max_seconds=3600) == 45


def test_offline_requires_confirmation_when_previously_online():
    decision = decide_poll_state(
        previous_effective_online=True,
        probed_online=False,
        probed_error=True,
        failures=0,
        circuit_failures=0,
        offline_confirmations=2,
        circuit_failure_threshold=4,
    )
    assert decision.effective_online is True
    assert decision.event == "offline_pending_confirmation"
    assert decision.failures == 1


def test_offline_confirmed_after_threshold():
    decision = decide_poll_state(
        previous_effective_online=True,
        probed_online=False,
        probed_error=True,
        failures=1,
        circuit_failures=1,
        offline_confirmations=2,
        circuit_failure_threshold=4,
    )
    assert decision.effective_online is False
    assert decision.event == "offline_confirmed"
    assert decision.failures == 2


def test_circuit_opens_after_consecutive_errors():
    decision = decide_poll_state(
        previous_effective_online=False,
        probed_online=False,
        probed_error=True,
        failures=4,
        circuit_failures=3,
        offline_confirmations=2,
        circuit_failure_threshold=4,
    )
    assert decision.effective_online is False
    assert decision.event == "circuit_opened"
    assert decision.circuit_failures == 4


def test_recovery_resets_counters():
    decision = decide_poll_state(
        previous_effective_online=False,
        probed_online=True,
        probed_error=False,
        failures=3,
        circuit_failures=2,
        offline_confirmations=2,
        circuit_failure_threshold=4,
    )
    assert decision.effective_online is True
    assert decision.event == "recovered"
    assert decision.failures == 0
    assert decision.circuit_failures == 0


class _FakeRedis:
    """Just enough of the async redis API for apply_poll_outcome: an in-memory
    hash store with a per-key TTL tracked but not actually enforced (nothing
    here needs real expiry, only to observe what TTL was requested)."""

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

    async def expire(self, key, ttl):
        self.ttls[key] = ttl


@pytest.mark.asyncio
async def test_apply_poll_outcome_grows_the_open_window_across_repeated_failures(monkeypatch):
    """This is the actual regression test for the incident: a device stuck
    down must be attempted less and less often over time, not hammered on
    every single scheduled cycle forever."""
    fake = _FakeRedis()
    async def _fake_get_redis():
        return fake

    monkeypatch.setattr("app.services.poll_resilience.get_redis", _fake_get_redis)
    monkeypatch.setattr("app.services.poll_resilience.settings.POLL_OFFLINE_CONFIRMATIONS", 1)
    monkeypatch.setattr("app.services.poll_resilience.settings.POLL_CIRCUIT_FAILURE_THRESHOLD", 2)
    monkeypatch.setattr("app.services.poll_resilience.settings.POLL_CIRCUIT_OPEN_SECONDS", 10)
    monkeypatch.setattr("app.services.poll_resilience.settings.POLL_CIRCUIT_MAX_OPEN_SECONDS", 1000)

    open_windows = []
    online = False
    for _ in range(5):
        online = await apply_poll_outcome(
            kind="switch",
            entity_id="sw-1",
            previous_effective_online=online,
            probed_online=False,
            probed_error=True,
        )
        state = fake.hashes["poll:resilience:switch:sw-1"]
        if "circuit_open_until" in state and int(state["circuit_open_until"]) > 0:
            open_windows.append(int(state["circuit_open_until"]))

    assert online is False
    # Each successive circuit-opened cycle must produce a further-out (or
    # equal, if it hasn't crossed a new doubling yet) deadline than the last -
    # never the same flat 10s window every time.
    assert len(open_windows) >= 2
    assert open_windows[-1] > open_windows[0]


@pytest.mark.asyncio
async def test_apply_poll_outcome_clears_open_window_on_recovery(monkeypatch):
    fake = _FakeRedis()
    fake.hashes["poll:resilience:switch:sw-2"] = {
        "failures": "6",
        "circuit_failures": "5",
        "circuit_open_until": str(9_999_999_999),
    }
    async def _fake_get_redis():
        return fake

    monkeypatch.setattr("app.services.poll_resilience.get_redis", _fake_get_redis)

    online = await apply_poll_outcome(
        kind="switch",
        entity_id="sw-2",
        previous_effective_online=False,
        probed_online=True,
        probed_error=False,
    )

    assert online is True
    assert fake.hashes["poll:resilience:switch:sw-2"]["circuit_open_until"] == "0"

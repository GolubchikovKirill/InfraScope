from app.services.poll_resilience import decide_poll_state


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

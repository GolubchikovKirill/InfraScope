from __future__ import annotations

from app.services.cisco_ssh import poe_cycle_ap, poe_cycle_ports_bulk, reboot_ap


class _FakeSSH:
    """Simulates one transient failure on a specific execute() call, then
    behaves normally - lets tests exercise 'something failed right after we
    powered the port off/shut it down' without the whole session dying."""

    def __init__(self, *, connect_ok: bool = True, fail_at_call: int | None = None) -> None:
        self._connect_ok = connect_ok
        self._fail_at_call = fail_at_call
        self._call_count = 0
        self._already_failed = False
        self.calls: list[str] = []
        self.closed = False

    def connect(self) -> bool:
        return self._connect_ok

    def execute(self, cmd: str) -> str:
        self._call_count += 1
        self.calls.append(cmd)
        if self._fail_at_call and self._call_count == self._fail_at_call and not self._already_failed:
            self._already_failed = True
            raise RuntimeError("simulated transient SSH failure")
        return ""

    def close(self) -> None:
        self.closed = True


def test_poe_cycle_ap_restores_power_when_failure_happens_after_power_off(monkeypatch) -> None:
    # Sequence: "configure terminal", "interface X", "power inline never", "end" (power-off,
    # calls 1-4), then call 5 ("configure terminal" for the power-on phase) fails.
    fake = _FakeSSH(fail_at_call=5)
    monkeypatch.setattr("app.services.cisco_ssh.CiscoSSH", lambda *a, **kw: fake)

    result = poe_cycle_ap("10.0.0.1", "admin", "pass", "", 22, "Gi1/0/1")

    assert result is False
    # Recovery must still have attempted "power inline auto" after the failure.
    assert "power inline auto" in fake.calls
    assert fake.calls.index("power inline never") < fake.calls.index("power inline auto")
    assert fake.closed is True


def test_poe_cycle_ap_succeeds_normally_without_any_failure(monkeypatch) -> None:
    fake = _FakeSSH()
    monkeypatch.setattr("app.services.cisco_ssh.CiscoSSH", lambda *a, **kw: fake)

    result = poe_cycle_ap("10.0.0.1", "admin", "pass", "", 22, "Gi1/0/1")

    assert result is True
    assert fake.calls.count("power inline auto") == 1


def test_poe_cycle_ap_logs_critical_when_recovery_itself_fails(monkeypatch, caplog) -> None:
    # Every call after the power-off phase fails, including the recovery attempt.
    class _AlwaysFailsAfterPowerOff(_FakeSSH):
        def execute(self, cmd: str) -> str:
            self._call_count += 1
            self.calls.append(cmd)
            if self._call_count > 4:
                raise RuntimeError("switch unreachable")
            return ""

    fake = _AlwaysFailsAfterPowerOff()
    monkeypatch.setattr("app.services.cisco_ssh.CiscoSSH", lambda *a, **kw: fake)

    with caplog.at_level("ERROR"):
        result = poe_cycle_ap("10.0.0.1", "admin", "pass", "", 22, "Gi1/0/1")

    assert result is False
    assert any("CRITICAL" in record.message for record in caplog.records)


def test_reboot_ap_restores_admin_up_when_failure_happens_after_shutdown(monkeypatch) -> None:
    # "configure terminal", "interface X", "shutdown" (calls 1-3), then call 4
    # ("no shutdown") fails.
    fake = _FakeSSH(fail_at_call=4)
    monkeypatch.setattr("app.services.cisco_ssh.CiscoSSH", lambda *a, **kw: fake)

    result = reboot_ap("10.0.0.1", "admin", "pass", "", 22, "Gi1/0/1")

    assert result is False
    assert "no shutdown" in fake.calls
    assert fake.calls.index("shutdown") < fake.calls.index("no shutdown")


def test_poe_cycle_ports_bulk_restores_power_on_every_port_when_failure_happens_after_power_off(
    monkeypatch,
) -> None:
    interfaces = ["Gi1/0/10", "Gi1/0/11", "Gi1/0/12"]
    # calls: "configure terminal"(1), then 2x per interface for power-off (2-7),
    # "end"(8), then "configure terminal"(9) for power-on phase fails.
    fake = _FakeSSH(fail_at_call=9)
    monkeypatch.setattr("app.services.cisco_ssh.CiscoSSH", lambda *a, **kw: fake)

    result = poe_cycle_ports_bulk("10.0.0.1", "admin", "pass", "", 22, interfaces)

    assert result is False
    assert fake.calls.count("power inline auto") == len(interfaces)
    assert fake.calls.count("power inline never") == len(interfaces)


def test_poe_cycle_ports_bulk_succeeds_normally_without_any_failure(monkeypatch) -> None:
    interfaces = ["Gi1/0/10", "Gi1/0/11"]
    fake = _FakeSSH()
    monkeypatch.setattr("app.services.cisco_ssh.CiscoSSH", lambda *a, **kw: fake)

    result = poe_cycle_ports_bulk("10.0.0.1", "admin", "pass", "", 22, interfaces)

    assert result is True
    assert fake.calls.count("power inline auto") == len(interfaces)

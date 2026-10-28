from __future__ import annotations

import pytest

from app.services import cisco_dhcp
from app.services.cisco_dhcp import (
    ROLE_EXTERNAL,
    ROLE_LOCAL_SERVER,
    ROLE_RELAY,
    DhcpBinding,
    DhcpDiagnostics,
    DhcpPool,
    classify_role,
    parse_dhcp_bindings,
    parse_dhcp_conflicts,
    parse_dhcp_pools,
    parse_protection_config,
    parse_snooping,
    parse_svi_config,
    plan_clear,
    run_dhcp_clear,
    run_dhcp_diagnostics,
    select_ap_bindings,
)

POOL_OUTPUT = """sw#show ip dhcp pool

Pool VLAN20 :
 Utilization mark (high/low)    : 100 / 0
 Subnet size (first/next)       : 0 / 0
 Total addresses                : 254
 Leased addresses               : 3
 Pending event                  : none
 1 subnet is currently in the pool :
 Current index        IP address range                    Leased addresses
 10.20.0.4            10.20.0.1        - 10.20.0.254       3
sw#"""

BINDING_OUTPUT = """sw#show ip dhcp binding
Bindings from all pools not associated with VRF:
IP address      Client-ID/              Lease expiration        Type       State      Interface
                Hardware address/
                User name
10.20.0.4       0100.1122.3344.55       Oct 29 2026 10:00 AM    Automatic  Active     Vlan20
10.20.0.5       0100.1122.3344.56       Oct 29 2026 11:30 AM    Automatic  Active     Vlan20
10.30.0.9       0100.aabb.ccdd.ee       Oct 29 2026 11:30 AM    Automatic  Active     Vlan30
10.20.0.200     0100.1122.3344.99       Infinite                Manual     Active     Vlan20
sw#"""

CONFLICT_OUTPUT = """sw#show ip dhcp conflict
IP address        Detection method   Detection time          VRF
10.20.0.7         Ping               Oct 28 2026 10:00 AM
10.20.0.8         Gratuitous ARP     Oct 28 2026 10:05 AM
sw#"""

SNOOPING_OUTPUT = """Switch DHCP snooping is enabled
DHCP snooping is configured on following VLANs:
20,30-31
Insertion of option 82 is enabled
"""

SVI_OUTPUT = """sw#show running-config interface vlan 20
Building configuration...

interface Vlan20
 ip address 10.20.0.1 255.255.255.0
 ip helper-address 10.1.1.5
end
sw#"""


def test_parse_pools() -> None:
    (pool,) = parse_dhcp_pools(POOL_OUTPUT)
    assert pool.name == "VLAN20"
    assert pool.total_addresses == 254
    assert pool.leased_addresses == 3
    assert pool.ranges == [("10.20.0.1", "10.20.0.254")]


def test_parse_bindings_reads_type_state_and_interface() -> None:
    bindings = parse_dhcp_bindings(BINDING_OUTPUT)
    assert [b.ip_address for b in bindings] == ["10.20.0.4", "10.20.0.5", "10.30.0.9", "10.20.0.200"]
    first = bindings[0]
    assert (first.binding_type, first.state, first.interface) == ("Automatic", "Active", "Vlan20")
    assert first.lease_expiration == "Oct 29 2026 10:00 AM"
    assert bindings[3].binding_type == "Manual"


def test_parse_bindings_ignores_header_and_prompt_lines() -> None:
    assert parse_dhcp_bindings("sw#show ip dhcp binding\nBindings from all pools not associated with VRF:\nsw#") == []


def test_parse_conflicts() -> None:
    assert parse_dhcp_conflicts(CONFLICT_OUTPUT) == ["10.20.0.7", "10.20.0.8"]


def test_parse_snooping_and_vlan_ranges() -> None:
    enabled, vlans = parse_snooping(SNOOPING_OUTPUT)
    assert enabled is True
    assert vlans == [20, 30, 31]
    assert parse_snooping("Switch DHCP snooping is disabled\n")[0] is False
    assert parse_snooping("garbage")[0] is None


def test_parse_protection_config_ignores_the_echoed_command() -> None:
    out = (
        "sw#show running-config | include arp inspection|verify source\n"
        "ip arp inspection vlan 20,30\n"
        " ip verify source\n"
        "sw#"
    )
    assert parse_protection_config(out) == ([20, 30], True)
    assert parse_protection_config("sw#show running-config | include x\nsw#") == ([], False)


def test_parse_svi_config() -> None:
    assert parse_svi_config(SVI_OUTPUT) == ("10.20.0.1", "255.255.255.0", ["10.1.1.5"])


def test_classify_role() -> None:
    pools = [DhcpPool(name="VLAN20", ranges=[("10.20.0.1", "10.20.0.254")])]
    assert classify_role(svi_ip="10.20.0.1", helpers=[], pools=pools) == ROLE_LOCAL_SERVER
    # A pool exists but is for another subnet, and the SVI relays: not local.
    assert classify_role(svi_ip="10.99.0.1", helpers=["10.1.1.5"], pools=pools) == ROLE_RELAY
    assert classify_role(svi_ip="10.99.0.1", helpers=[], pools=pools) == ROLE_EXTERNAL
    # L2-only switch: no SVI for the VLAN at all.
    assert classify_role(svi_ip=None, helpers=[], pools=pools) == ROLE_EXTERNAL


def test_select_ap_bindings_only_returns_provable_members() -> None:
    bindings = parse_dhcp_bindings(BINDING_OUTPUT)
    selected = select_ap_bindings(bindings, vlan=20, svi_ip="10.20.0.1", svi_mask="255.255.255.0")
    assert [b.ip_address for b in selected] == ["10.20.0.4", "10.20.0.5", "10.20.0.200"]

    # Without an SVI subnet, only the interface tag counts - never "everything".
    by_tag = select_ap_bindings(bindings, vlan=30, svi_ip=None, svi_mask=None)
    assert [b.ip_address for b in by_tag] == ["10.30.0.9"]
    assert select_ap_bindings(bindings, vlan=99, svi_ip=None, svi_mask=None) == []


def _diag(**overrides) -> DhcpDiagnostics:
    bindings = parse_dhcp_bindings(BINDING_OUTPUT)
    diag = DhcpDiagnostics(
        vlan=20,
        role=ROLE_LOCAL_SERVER,
        bindings=bindings,
        conflicts=["10.20.0.7"],
        svi_ip="10.20.0.1",
        svi_mask="255.255.255.0",
    )
    diag.ap_bindings = select_ap_bindings(bindings, vlan=20, svi_ip=diag.svi_ip, svi_mask=diag.svi_mask)
    for key, value in overrides.items():
        setattr(diag, key, value)
    return diag


def test_plan_clears_conflicts_and_only_automatic_ap_bindings() -> None:
    plan = plan_clear(_diag(), actions={"conflict", "binding"}, max_bindings=300)
    assert plan.commands == [
        "clear ip dhcp conflict *",
        "clear ip dhcp binding 10.20.0.4",
        "clear ip dhcp binding 10.20.0.5",
    ]
    assert (plan.conflicts_to_clear, plan.bindings_to_clear) == (1, 2)


@pytest.mark.parametrize("role", [ROLE_RELAY, ROLE_EXTERNAL])
def test_plan_refuses_when_switch_is_not_the_dhcp_server(role: str) -> None:
    plan = plan_clear(_diag(role=role), actions={"conflict", "binding"}, max_bindings=300)
    assert plan.commands == []
    assert "not the DHCP server" in plan.skipped[0]


def test_plan_respects_the_binding_safety_cap() -> None:
    plan = plan_clear(_diag(), actions={"binding"}, max_bindings=1)
    assert plan.commands == []
    assert "safety cap" in plan.skipped[0]


def test_plan_ignores_unknown_actions() -> None:
    plan = plan_clear(_diag(), actions={"snooping_binding", "reload"}, max_bindings=300)
    assert plan.commands == []
    assert any("unknown actions" in s for s in plan.skipped)


def test_plan_skips_conflict_clear_when_list_is_empty() -> None:
    plan = plan_clear(_diag(conflicts=[]), actions={"conflict"}, max_bindings=300)
    assert plan.commands == []


class _FakeSSH:
    """Answers show commands from a table and records every command sent."""

    def __init__(self, responses: dict[str, str], *, cleared_state: dict[str, str] | None = None) -> None:
        self.responses = responses
        self.cleared_state = cleared_state or {}
        self.calls: list[str] = []
        self.closed = False
        self._cleared = False

    def connect(self) -> bool:
        return True

    def is_alive(self) -> bool:
        return True

    def ensure_connected(self) -> bool:
        return True

    def execute(self, cmd: str) -> str:
        self.calls.append(cmd)
        if cmd.startswith("clear "):
            self._cleared = True
            return f"sw#{cmd}\nsw#"
        table = self.cleared_state if self._cleared and cmd in self.cleared_state else self.responses
        return table.get(cmd, "% Invalid input detected at '^' marker.\n")

    def close(self) -> None:
        self.closed = True


def _local_server_ssh(**kw) -> _FakeSSH:
    return _FakeSSH(
        {
            "show ip dhcp pool": POOL_OUTPUT,
            "show ip dhcp binding": BINDING_OUTPUT,
            "show ip dhcp conflict": CONFLICT_OUTPUT,
            "show ip dhcp snooping": SNOOPING_OUTPUT,
            "show running-config | include arp inspection|verify source": "sw#\n",
            "show running-config interface vlan 20": SVI_OUTPUT,
        },
        **kw,
    )


def _args() -> tuple:
    return ("10.0.0.1", "admin", "pw", "", 22, 20)


def test_diagnostics_reports_unsupported_commands_instead_of_zeroes() -> None:
    ssh = _FakeSSH({})  # every show command is rejected
    diag = run_dhcp_diagnostics(*_args(), session=ssh)
    assert diag is not None
    assert diag.role == ROLE_EXTERNAL
    assert "show ip dhcp pool" in diag.unsupported
    assert all(not c.startswith("clear") for c in ssh.calls)


def test_diagnostics_never_sends_a_write_command() -> None:
    ssh = _local_server_ssh()
    diag = run_dhcp_diagnostics(*_args(), session=ssh)
    assert diag is not None and diag.role == ROLE_LOCAL_SERVER
    assert all(c.startswith("show ") for c in ssh.calls)


def test_dry_run_plans_but_sends_nothing() -> None:
    ssh = _local_server_ssh()
    result = run_dhcp_clear(*_args(), actions={"conflict", "binding"}, max_bindings=300, dry_run=True, session=ssh)
    assert result is not None
    assert len(result.plan.commands) == 3
    assert not any(c.startswith("clear") for c in ssh.calls)


def test_live_run_sends_planned_commands_and_reports_after_state() -> None:
    ssh = _local_server_ssh(
        cleared_state={"show ip dhcp binding": "sw#\n", "show ip dhcp conflict": "sw#\n"},
    )
    result = run_dhcp_clear(*_args(), actions={"conflict", "binding"}, max_bindings=300, dry_run=False, session=ssh)
    assert result is not None
    assert [c for c in ssh.calls if c.startswith("clear")] == [
        "clear ip dhcp conflict *",
        "clear ip dhcp binding 10.20.0.4",
        "clear ip dhcp binding 10.20.0.5",
    ]
    assert (result.conflicts_cleared, result.bindings_cleared) == (2, 2)
    assert result.errors == []
    assert (result.bindings_before, result.bindings_after) == (3, 0)
    assert result.conflicts_after == 0


def test_live_run_on_a_relay_switch_sends_no_clear_command() -> None:
    ssh = _local_server_ssh()
    ssh.responses["show ip dhcp pool"] = "sw#\n"  # no local pool -> relay
    result = run_dhcp_clear(*_args(), actions={"conflict", "binding"}, max_bindings=300, dry_run=False, session=ssh)
    assert result is not None and result.role == ROLE_RELAY
    assert not any(c.startswith("clear") for c in ssh.calls)


def test_rejected_clear_command_is_reported_as_an_error() -> None:
    ssh = _local_server_ssh()
    original = ssh.execute

    def _execute(cmd: str) -> str:
        if cmd == "clear ip dhcp binding 10.20.0.5":
            return "sw#clear ...\n% Invalid input detected at '^' marker.\nsw#"
        return original(cmd)

    ssh.execute = _execute  # type: ignore[method-assign]
    result = run_dhcp_clear(*_args(), actions={"binding"}, max_bindings=300, dry_run=False, session=ssh)
    assert result is not None
    assert result.bindings_cleared == 1
    assert len(result.errors) == 1 and "10.20.0.5" in result.errors[0]


def test_connection_failure_returns_none_not_an_empty_result(monkeypatch) -> None:
    monkeypatch.setattr(cisco_dhcp, "_session_for", lambda *a, **kw: (None, True))
    assert run_dhcp_diagnostics(*_args()) is None
    assert run_dhcp_clear(*_args(), actions={"conflict"}, max_bindings=300, dry_run=False) is None


def test_binding_dataclass_roundtrip_fields() -> None:
    b = DhcpBinding("10.0.0.1", "0100.0000.0000.01", "Infinite", "Manual")
    assert vars(b)["ip_address"] == "10.0.0.1"

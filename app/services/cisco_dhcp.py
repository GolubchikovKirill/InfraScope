"""DHCP diagnostics and cleanup over SSH for Cisco IOS switches.

Diagnostics are strictly read-only (`show ...`). Cleanup only ever sends two
fixed command shapes - `clear ip dhcp conflict *` and
`clear ip dhcp binding <ip>` for one IPv4 address parsed out of the switch's own
binding table - so nothing an operator or a settings value types can reach the
switch's CLI.

The first question a diagnostic answers is *who actually serves DHCP for the AP
VLAN*, because that decides whether clearing anything on this switch can help:

  local_server  the switch itself holds a pool covering its VLAN interface, so
                its binding/conflict tables are the ones the APs are leasing from
  relay         the VLAN interface forwards DHCP to another server
                (`ip helper-address`); the tables that matter live there
  external      no VLAN interface (an L2-only access switch) - DHCP is answered
                somewhere upstream and there is nothing to clear here

Cleanup refuses to touch anything unless the role is `local_server`.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass, field

from app.observability.metrics import switch_ops_total
from app.services.cisco_ssh import CiscoSSH, _session_for

logger = logging.getLogger(__name__)

ROLE_LOCAL_SERVER = "local_server"
ROLE_RELAY = "relay"
ROLE_EXTERNAL = "external"

ACTION_CONFLICT = "conflict"
ACTION_BINDING = "binding"
VALID_ACTIONS = frozenset({ACTION_CONFLICT, ACTION_BINDING})

_IPV4 = r"\d{1,3}(?:\.\d{1,3}){3}"
_CLI_ERROR_MARKERS = ("% Invalid input", "% Incomplete command", "% Ambiguous command", "% Unrecognized")


@dataclass
class DhcpPool:
    name: str
    total_addresses: int | None = None
    leased_addresses: int | None = None
    ranges: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class DhcpBinding:
    ip_address: str
    client_id: str
    lease_expiration: str
    binding_type: str
    state: str | None = None
    interface: str | None = None


@dataclass
class DhcpDiagnostics:
    vlan: int
    role: str = ROLE_EXTERNAL
    pools: list[DhcpPool] = field(default_factory=list)
    bindings: list[DhcpBinding] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    helper_addresses: list[str] = field(default_factory=list)
    svi_ip: str | None = None
    svi_mask: str | None = None
    snooping_enabled: bool | None = None
    snooping_vlans: list[int] = field(default_factory=list)
    arp_inspection_vlans: list[int] = field(default_factory=list)
    ip_source_guard: bool = False
    # Show commands this switch rejected (e.g. no DHCP server feature), so the
    # UI can say "not supported" instead of showing a misleading zero.
    unsupported: list[str] = field(default_factory=list)
    # Bindings that belong to the AP VLAN - the only ones cleanup will touch.
    ap_bindings: list[DhcpBinding] = field(default_factory=list)


@dataclass
class DhcpClearPlan:
    commands: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    conflicts_to_clear: int = 0
    bindings_to_clear: int = 0


@dataclass
class DhcpClearResult:
    dry_run: bool
    role: str
    plan: DhcpClearPlan
    conflicts_cleared: int = 0
    bindings_cleared: int = 0
    errors: list[str] = field(default_factory=list)
    bindings_before: int = 0
    bindings_after: int | None = None
    conflicts_before: int = 0
    conflicts_after: int | None = None


def _is_cli_error(output: str) -> bool:
    return any(marker in output for marker in _CLI_ERROR_MARKERS)


def _parse_vlan_list(text: str) -> list[int]:
    """'20,30-32' -> [20, 30, 31, 32]. Junk tokens are ignored."""
    vlans: set[int] = set()
    for token in text.replace(" ", "").split(","):
        if re.fullmatch(r"\d+", token):
            vlans.add(int(token))
        elif m := re.fullmatch(r"(\d+)-(\d+)", token):
            low, high = int(m.group(1)), int(m.group(2))
            if 0 < low <= high <= 4094:
                vlans.update(range(low, high + 1))
    return sorted(v for v in vlans if 1 <= v <= 4094)


def parse_dhcp_pools(output: str) -> list[DhcpPool]:
    pools: list[DhcpPool] = []
    current: DhcpPool | None = None
    for line in output.splitlines():
        if m := re.match(r"\s*Pool\s+(\S+)\s*:", line):
            current = DhcpPool(name=m.group(1))
            pools.append(current)
            continue
        if current is None:
            continue
        if m := re.search(r"Total addresses\s*:\s*(\d+)", line):
            current.total_addresses = int(m.group(1))
        elif m := re.search(r"Leased addresses\s*:\s*(\d+)", line):
            current.leased_addresses = int(m.group(1))
        elif m := re.match(rf"\s*{_IPV4}\s+({_IPV4})\s+-\s+({_IPV4})\s+\d+", line):
            current.ranges.append((m.group(1), m.group(2)))
    return pools


_BINDING_TYPES = ("Automatic", "Manual", "On-demand", "Relay")


def parse_dhcp_bindings(output: str) -> list[DhcpBinding]:
    bindings: list[DhcpBinding] = []
    for line in output.splitlines():
        m = re.match(rf"\s*({_IPV4})\s+(\S+)\s+(.+?)\s+({'|'.join(_BINDING_TYPES)})\b(.*)$", line)
        if not m:
            continue
        tail = m.group(5).split()
        state = tail[0] if tail and tail[0] in {"Active", "Expired", "Pending", "Declined"} else None
        interface = tail[-1] if tail and re.fullmatch(r"[A-Za-z][A-Za-z-]*[\d/.]+", tail[-1]) else None
        bindings.append(
            DhcpBinding(
                ip_address=m.group(1),
                client_id=m.group(2),
                lease_expiration=m.group(3).strip(),
                binding_type=m.group(4),
                state=state,
                interface=interface,
            )
        )
    return bindings


def parse_dhcp_conflicts(output: str) -> list[str]:
    return [m.group(1) for line in output.splitlines() if (m := re.match(rf"\s*({_IPV4})\s+\S", line))]


def parse_snooping(output: str) -> tuple[bool | None, list[int]]:
    lowered = output.lower()
    if "snooping is enabled" in lowered:
        enabled: bool | None = True
    elif "snooping is disabled" in lowered:
        enabled = False
    else:
        enabled = None
    vlans: list[int] = []
    if m := re.search(r"configured on following VLANs:\s*\n?\s*([\d,\- ]+)", output, re.IGNORECASE):
        vlans = _parse_vlan_list(m.group(1).split("\n")[0])
    return enabled, vlans


def parse_protection_config(output: str) -> tuple[list[int], bool]:
    """(VLANs under dynamic ARP inspection, whether IP Source Guard is configured).

    Both break a client the moment its snooping binding disappears, so a
    diagnostic should surface them even though cleanup never touches snooping.
    """
    arp_vlans: set[int] = set()
    source_guard = False
    for line in output.splitlines():
        if m := re.match(r"\s*ip arp inspection vlan\s+([\d,\- ]+)\s*$", line):
            arp_vlans.update(_parse_vlan_list(m.group(1)))
        elif re.match(r"\s*ip verify source\b", line):
            source_guard = True
    return sorted(arp_vlans), source_guard


def parse_svi_config(output: str) -> tuple[str | None, str | None, list[str]]:
    """(ip, mask, helper-addresses) from `show running-config interface vlan N`."""
    ip = mask = None
    helpers: list[str] = []
    for line in output.splitlines():
        if m := re.match(rf"\s*ip address\s+({_IPV4})\s+({_IPV4})\s*$", line):
            ip, mask = m.group(1), m.group(2)
        elif m := re.match(rf"\s*ip helper-address\s+({_IPV4})\s*$", line):
            helpers.append(m.group(1))
    return ip, mask, helpers


def _ip_in_range(ip: ipaddress.IPv4Address, low: str, high: str) -> bool:
    try:
        return ipaddress.IPv4Address(low) <= ip <= ipaddress.IPv4Address(high)
    except ipaddress.AddressValueError:
        return False


def classify_role(*, svi_ip: str | None, helpers: list[str], pools: list[DhcpPool]) -> str:
    if svi_ip is None:
        return ROLE_EXTERNAL
    try:
        svi = ipaddress.IPv4Address(svi_ip)
    except ipaddress.AddressValueError:
        return ROLE_EXTERNAL
    if any(_ip_in_range(svi, low, high) for pool in pools for low, high in pool.ranges):
        return ROLE_LOCAL_SERVER
    return ROLE_RELAY if helpers else ROLE_EXTERNAL


def select_ap_bindings(
    bindings: list[DhcpBinding], *, vlan: int, svi_ip: str | None, svi_mask: str | None
) -> list[DhcpBinding]:
    """Bindings that provably belong to the AP VLAN, nothing more.

    A binding counts when the switch tagged it with `Vlan<N>` or when its
    address is inside the VLAN interface's own subnet. If neither can be
    established the answer is an empty list, never "everything".
    """
    network: ipaddress.IPv4Network | None = None
    if svi_ip and svi_mask:
        try:
            network = ipaddress.IPv4Network(f"{svi_ip}/{svi_mask}", strict=False)
        except ValueError:
            network = None
    wanted_interface = f"vlan{vlan}"
    selected: list[DhcpBinding] = []
    for binding in bindings:
        on_interface = (binding.interface or "").lower() == wanted_interface
        in_subnet = False
        if network is not None:
            try:
                in_subnet = ipaddress.IPv4Address(binding.ip_address) in network
            except ipaddress.AddressValueError:
                in_subnet = False
        if on_interface or in_subnet:
            selected.append(binding)
    return selected


def collect_diagnostics(ssh: CiscoSSH, vlan: int) -> DhcpDiagnostics:
    """Run the read-only show commands on an already-connected session."""
    diag = DhcpDiagnostics(vlan=vlan)

    def run(cmd: str) -> str | None:
        output = ssh.execute(cmd)
        if _is_cli_error(output):
            diag.unsupported.append(cmd)
            return None
        return output

    if (out := run("show ip dhcp pool")) is not None:
        diag.pools = parse_dhcp_pools(out)
    if (out := run("show ip dhcp binding")) is not None:
        diag.bindings = parse_dhcp_bindings(out)
    if (out := run("show ip dhcp conflict")) is not None:
        diag.conflicts = parse_dhcp_conflicts(out)
    if (out := run("show ip dhcp snooping")) is not None:
        diag.snooping_enabled, diag.snooping_vlans = parse_snooping(out)
    if (out := run("show running-config | include arp inspection|verify source")) is not None:
        diag.arp_inspection_vlans, diag.ip_source_guard = parse_protection_config(out)
    if (out := run(f"show running-config interface vlan {vlan}")) is not None:
        diag.svi_ip, diag.svi_mask, diag.helper_addresses = parse_svi_config(out)

    diag.role = classify_role(svi_ip=diag.svi_ip, helpers=diag.helper_addresses, pools=diag.pools)
    diag.ap_bindings = select_ap_bindings(diag.bindings, vlan=vlan, svi_ip=diag.svi_ip, svi_mask=diag.svi_mask)
    return diag


def plan_clear(diag: DhcpDiagnostics, *, actions: set[str], max_bindings: int) -> DhcpClearPlan:
    """Decide exactly which commands cleanup would send. Pure; no I/O."""
    plan = DhcpClearPlan()
    unknown = actions - VALID_ACTIONS
    if unknown:
        plan.skipped.append(f"unknown actions ignored: {', '.join(sorted(unknown))}")
    actions = actions & VALID_ACTIONS
    if not actions:
        plan.skipped.append("no cleanup actions enabled")
        return plan

    if diag.role != ROLE_LOCAL_SERVER:
        plan.skipped.append(
            f"switch is not the DHCP server for VLAN {diag.vlan} (role={diag.role}); "
            "its DHCP tables are not what the access points lease from"
        )
        return plan

    if ACTION_CONFLICT in actions:
        if diag.conflicts:
            plan.commands.append("clear ip dhcp conflict *")
            plan.conflicts_to_clear = len(diag.conflicts)
        else:
            plan.skipped.append("no DHCP conflicts to clear")

    if ACTION_BINDING in actions:
        # Manual bindings are static reservations - clearing them is refused by
        # IOS and would be wrong to try regardless.
        candidates = [b for b in diag.ap_bindings if b.binding_type == "Automatic"]
        if not candidates:
            plan.skipped.append(f"no automatic DHCP bindings on VLAN {diag.vlan}")
        elif len(candidates) > max_bindings:
            plan.skipped.append(
                f"{len(candidates)} bindings on VLAN {diag.vlan} exceeds the safety cap of {max_bindings}; "
                "refusing to clear them automatically"
            )
        else:
            plan.commands.extend(f"clear ip dhcp binding {b.ip_address}" for b in candidates)
            plan.bindings_to_clear = len(candidates)
    return plan


def run_dhcp_diagnostics(
    ip: str,
    username: str,
    password: str,
    enable_password: str,
    port: int,
    vlan: int,
    session: CiscoSSH | None = None,
) -> DhcpDiagnostics | None:
    """Read-only DHCP snapshot, or None if the switch could not be reached at
    all (distinct from an empty snapshot - see get_access_points)."""
    ssh, owns_session = _session_for(session, ip, username, password, enable_password, port)
    if ssh is None:
        switch_ops_total.labels(operation="dhcp_diagnostics", result="error").inc()
        return None
    try:
        diag = collect_diagnostics(ssh, vlan)
        switch_ops_total.labels(operation="dhcp_diagnostics", result="success").inc()
        return diag
    except Exception as e:  # a dead session must read as "unreachable", never as an empty snapshot
        logger.warning("DHCP diagnostics failed on %s: %s", ip, e)
        switch_ops_total.labels(operation="dhcp_diagnostics", result="error").inc()
        return None
    finally:
        if owns_session:
            ssh.close()


def run_dhcp_clear(
    ip: str,
    username: str,
    password: str,
    enable_password: str,
    port: int,
    vlan: int,
    *,
    actions: set[str],
    max_bindings: int,
    dry_run: bool,
    session: CiscoSSH | None = None,
) -> DhcpClearResult | None:
    """Plan - and unless `dry_run`, execute - DHCP cleanup on one switch.

    Returns None if the switch could not be scanned. The plan is always built
    from a fresh read on this same session, never from a cached earlier
    diagnostic, so a stale view can't drive a clear.
    """
    ssh, owns_session = _session_for(session, ip, username, password, enable_password, port)
    if ssh is None:
        switch_ops_total.labels(operation="dhcp_clear", result="error").inc()
        return None
    try:
        diag = collect_diagnostics(ssh, vlan)
        plan = plan_clear(diag, actions=actions, max_bindings=max_bindings)
        result = DhcpClearResult(
            dry_run=dry_run,
            role=diag.role,
            plan=plan,
            bindings_before=len(diag.ap_bindings),
            conflicts_before=len(diag.conflicts),
        )
        if dry_run or not plan.commands:
            switch_ops_total.labels(operation="dhcp_clear", result="success").inc()
            return result

        for cmd in plan.commands:
            try:
                output = ssh.execute(cmd)
            except Exception as e:  # commands already sent can't be undone; report a partial result instead of hiding it
                logger.warning("DHCP clear command %r failed on %s: %s", cmd, ip, e)
                result.errors.append(f"{cmd}: {e}")
                break
            if _is_cli_error(output):
                detail = next((ln.strip() for ln in output.splitlines() if "%" in ln), "rejected")
                result.errors.append(f"{cmd}: {detail}")
                continue
            if cmd.startswith("clear ip dhcp conflict"):
                result.conflicts_cleared = plan.conflicts_to_clear
            else:
                result.bindings_cleared += 1

        try:
            after = collect_diagnostics(ssh, vlan)
            result.bindings_after = len(after.ap_bindings)
            result.conflicts_after = len(after.conflicts)
        except Exception as e:  # the verification read is best effort; the clear itself already ran
            logger.warning("DHCP post-clear verification failed on %s: %s", ip, e)
        switch_ops_total.labels(operation="dhcp_clear", result="error" if result.errors else "success").inc()
        return result
    except Exception as e:  # report as unreachable/failed to the caller, which logs it as an event
        logger.warning("DHCP clear failed on %s: %s", ip, e)
        switch_ops_total.labels(operation="dhcp_clear", result="error").inc()
        return None
    finally:
        if owns_session:
            ssh.close()

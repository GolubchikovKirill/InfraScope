from __future__ import annotations

import asyncio
import logging
import warnings

warnings.filterwarnings("ignore", message=".*pysnmp-lextudio.*")

from pysnmp.hlapi.asyncio import (  # noqa: E402
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
)
from pysnmp.hlapi.asyncio.cmdgen import getCmd, setCmd, walkCmd  # noqa: E402
from pysnmp.proto.rfc1902 import Integer, OctetString  # noqa: E402

from app.domains.inventory.models import NetworkSwitch  # noqa: E402
from app.observability.metrics import snmp_operations_total  # noqa: E402
from app.services.switches.base import SwitchPollInfo, SwitchPortState  # noqa: E402

logger = logging.getLogger(__name__)

_OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
_OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
_OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
_OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
_OID_IF_SPEED = "1.3.6.1.2.1.2.2.1.5"
_OID_IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"
_OID_IF_OPER = "1.3.6.1.2.1.2.2.1.8"
_OID_IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
_OID_DOT1Q_PVID = "1.3.6.1.2.1.17.7.1.4.5.1.1"
_OID_POE_ADMIN = "1.3.6.1.2.1.105.1.1.1.3.1"
_OID_POE_POWER = "1.3.6.1.2.1.105.1.1.1.6.1"


def _uptime_ticks_to_human(raw_ticks: str | None) -> str | None:
    if not raw_ticks:
        return None
    try:
        ticks = int(raw_ticks)
    except ValueError:
        return None
    seconds = ticks // 100
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


class SnmpSwitchProvider:
    def poll_switch(self, switch: NetworkSwitch) -> SwitchPollInfo:
        result = asyncio.run(self._poll_switch_async(switch))
        return result

    async def _poll_switch_async(self, switch: NetworkSwitch) -> SwitchPollInfo:
        try:
            data = await self._fetch_basics(
                host=switch.ip_address,
                community=switch.snmp_community_ro,
            )
        except Exception as exc:
            logger.info("SNMP poll failed for %s: %s", switch.ip_address, exc)
            snmp_operations_total.labels(operation="switch_poll", result="error", reason="exception").inc()
            return SwitchPollInfo(is_online=False)

        if not data:
            snmp_operations_total.labels(operation="switch_poll", result="error", reason="no_data").inc()
            return SwitchPollInfo(is_online=False)

        snmp_operations_total.labels(operation="switch_poll", result="success", reason="ok").inc()
        return SwitchPollInfo(
            is_online=True,
            hostname=data.get("hostname"),
            model_info=data.get("model_info"),
            uptime=data.get("uptime"),
            ios_version=None,
        )

    def get_ports(self, switch: NetworkSwitch) -> list[SwitchPortState]:
        return asyncio.run(self._get_ports_async(switch))

    async def _get_ports_async(self, switch: NetworkSwitch) -> list[SwitchPortState]:
        engine = SnmpEngine()
        target = await self._create_transport_target(switch.ip_address, 161, timeout=2, retries=1)
        community = CommunityData(switch.snmp_community_ro, mpModel=1)
        descr_rows = await self._snmp_walk(engine, target, community, _OID_IF_DESCR)
        alias_rows = await self._snmp_walk(engine, target, community, _OID_IF_ALIAS)
        admin_rows = await self._snmp_walk(engine, target, community, _OID_IF_ADMIN)
        oper_rows = await self._snmp_walk(engine, target, community, _OID_IF_OPER)
        speed_rows = await self._snmp_walk(engine, target, community, _OID_IF_SPEED)
        vlan_rows = await self._snmp_walk(engine, target, community, _OID_DOT1Q_PVID)
        poe_admin_rows = await self._snmp_walk(engine, target, community, _OID_POE_ADMIN)
        poe_power_rows = await self._snmp_walk(engine, target, community, _OID_POE_POWER)

        alias_by_idx = self._to_index_map(alias_rows)
        admin_by_idx = self._to_index_map(admin_rows)
        oper_by_idx = self._to_index_map(oper_rows)
        speed_by_idx = self._to_index_map(speed_rows)
        vlan_by_idx = self._to_index_map(vlan_rows)
        poe_admin_by_idx = self._to_index_map(poe_admin_rows)
        poe_power_by_idx = self._to_index_map(poe_power_rows)

        ports: list[SwitchPortState] = []
        for oid, raw_port_name in descr_rows:
            idx = self._extract_index(oid)
            if idx is None:
                continue

            speed_raw = speed_by_idx.get(idx)
            speed_mbps: int | None = None
            if speed_raw:
                try:
                    speed_mbps = int(speed_raw) // 1_000_000
                except ValueError:
                    speed_mbps = None

            admin_status = {"1": "up", "2": "down", "3": "testing"}.get(admin_by_idx.get(idx, ""), None)
            oper_status = {
                "1": "up",
                "2": "down",
                "3": "testing",
                "4": "unknown",
                "5": "dormant",
                "6": "notPresent",
                "7": "lowerLayerDown",
            }.get(oper_by_idx.get(idx, ""), None)

            vlan: int | None = None
            vlan_raw = vlan_by_idx.get(idx)
            if vlan_raw:
                try:
                    vlan = int(vlan_raw)
                except ValueError:
                    vlan = None

            poe_enabled = None
            poe_admin_raw = poe_admin_by_idx.get(idx)
            if poe_admin_raw is not None:
                poe_enabled = poe_admin_raw == "1"

            poe_power_w = None
            poe_power_raw = poe_power_by_idx.get(idx)
            if poe_power_raw:
                try:
                    poe_power_w = round(int(poe_power_raw) / 1000.0, 2)
                except ValueError:
                    poe_power_w = None

            ports.append(
                SwitchPortState(
                    port=raw_port_name,
                    if_index=idx,
                    description=alias_by_idx.get(idx),
                    admin_status=admin_status,
                    oper_status=oper_status,
                    speed_mbps=speed_mbps,
                    duplex=None,
                    vlan=vlan,
                    poe_enabled=poe_enabled,
                    poe_power_w=poe_power_w,
                    mac_count=None,
                )
            )

        snmp_operations_total.labels(operation="switch_ports", result="success", reason="ok").inc()
        return sorted(ports, key=lambda p: p.if_index)

    async def _fetch_basics(self, host: str, community: str) -> dict[str, str] | None:
        engine = SnmpEngine()
        target = await self._create_transport_target(host, 161, timeout=2, retries=1)
        comm = CommunityData(community, mpModel=1)
        sys_name = await self._snmp_get(engine, target, comm, _OID_SYS_NAME)
        sys_descr = await self._snmp_get(engine, target, comm, _OID_SYS_DESCR)
        sys_uptime = await self._snmp_get(engine, target, comm, _OID_SYS_UPTIME)
        if not (sys_name or sys_descr):
            return None
        return {
            "hostname": sys_name or host,
            "model_info": sys_descr,
            "uptime": _uptime_ticks_to_human(sys_uptime) or sys_uptime or "",
        }

    async def _snmp_get(
        self,
        engine: SnmpEngine,
        target: UdpTransportTarget,
        community: CommunityData,
        oid: str,
    ) -> str | None:
        error_indication, error_status, _error_index, var_binds = await getCmd(
            engine,
            community,
            target,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if error_indication or error_status:
            return None
        for _oid, val in var_binds:
            return self._decode(val)
        return None

    async def _snmp_set(
        self,
        host: str,
        community: str,
        oid: str,
        value,
    ) -> None:
        engine = SnmpEngine()
        target = await self._create_transport_target(host, 161, timeout=2, retries=1)
        comm = CommunityData(community, mpModel=1)
        error_indication, error_status, _error_index, _var_binds = await setCmd(
            engine,
            comm,
            target,
            ContextData(),
            ObjectType(ObjectIdentity(oid), value),
        )
        if error_indication or error_status:
            raise RuntimeError(f"SNMP set failed for {oid}")

    async def _snmp_walk(
        self,
        engine: SnmpEngine,
        target: UdpTransportTarget,
        community: CommunityData,
        oid: str,
    ) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        async for error_indication, error_status, _error_index, var_binds in walkCmd(
            engine,
            community,
            target,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if error_indication or error_status:
                break
            for oid_result, val in var_binds:
                rows.append((str(oid_result), self._decode(val)))
        return rows

    def _extract_index(self, oid: str) -> int | None:
        try:
            return int(oid.rsplit(".", 1)[-1])
        except ValueError:
            return None

    def _to_index_map(self, rows: list[tuple[str, str]]) -> dict[int, str]:
        out: dict[int, str] = {}
        for oid, value in rows:
            idx = self._extract_index(oid)
            if idx is not None:
                out[idx] = value
        return out

    def _decode(self, val) -> str:
        if hasattr(val, "asOctets"):
            raw = val.asOctets()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
        return str(val)

    async def _create_transport_target(
        self,
        host: str,
        port: int,
        *,
        timeout: int,
        retries: int,
    ) -> UdpTransportTarget:
        """Support both modern and legacy pysnmp async transport APIs."""
        create = getattr(UdpTransportTarget, "create", None)
        if callable(create):
            return await create((host, port), timeout=timeout, retries=retries)
        return UdpTransportTarget((host, port), timeout=timeout, retries=retries)

    def set_admin_state(self, switch: NetworkSwitch, port: str, admin_state: str) -> None:
        idx = self._resolve_if_index(switch, port)
        value = Integer(1 if admin_state == "up" else 2)
        asyncio.run(self._snmp_set(switch.ip_address, self._rw_community(switch), f"{_OID_IF_ADMIN}.{idx}", value))

    def set_description(self, switch: NetworkSwitch, port: str, description: str) -> None:
        idx = self._resolve_if_index(switch, port)
        asyncio.run(
            self._snmp_set(
                switch.ip_address,
                self._rw_community(switch),
                f"{_OID_IF_ALIAS}.{idx}",
                OctetString(description),
            )
        )

    def set_vlan(self, switch: NetworkSwitch, port: str, vlan: int) -> None:
        idx = self._resolve_if_index(switch, port)
        asyncio.run(
            self._snmp_set(
                switch.ip_address,
                self._rw_community(switch),
                f"{_OID_DOT1Q_PVID}.{idx}",
                Integer(vlan),
            )
        )

    def set_mode(
        self,
        switch: NetworkSwitch,
        port: str,
        mode: str,
        access_vlan: int | None = None,
        native_vlan: int | None = None,
        allowed_vlans: str | None = None,
    ) -> None:
        raise RuntimeError("Port mode changes are currently supported only via vendor CLI providers")

    def set_poe(self, switch: NetworkSwitch, port: str, action: str) -> None:
        idx = self._resolve_if_index(switch, port)
        community = self._rw_community(switch)
        if action == "on":
            asyncio.run(self._snmp_set(switch.ip_address, community, f"{_OID_POE_ADMIN}.{idx}", Integer(1)))
            return
        if action == "off":
            asyncio.run(self._snmp_set(switch.ip_address, community, f"{_OID_POE_ADMIN}.{idx}", Integer(2)))
            return
        asyncio.run(self._snmp_set(switch.ip_address, community, f"{_OID_POE_ADMIN}.{idx}", Integer(2)))
        asyncio.run(self._snmp_set(switch.ip_address, community, f"{_OID_POE_ADMIN}.{idx}", Integer(1)))

    def _rw_community(self, switch: NetworkSwitch) -> str:
        if not switch.snmp_community_rw:
            raise RuntimeError("SNMP write community is not configured for this switch")
        return switch.snmp_community_rw

    def _resolve_if_index(self, switch: NetworkSwitch, port: str) -> int:
        ports = self.get_ports(switch)
        normalized = port.strip().lower()
        for item in ports:
            if item.port.strip().lower() == normalized:
                return item.if_index
        try:
            return int(port)
        except ValueError as exc:
            raise RuntimeError(f"Port '{port}' not found") from exc

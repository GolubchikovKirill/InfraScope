from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.crypto import EncryptedString


class Printer(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    printer_type: str = Field(default="laser", max_length=20, index=True)
    connection_type: str = Field(default="ip", max_length=10)
    store_name: str = Field(max_length=255, index=True)
    model: str = Field(max_length=255)
    ip_address: str | None = Field(default=None, max_length=45, index=True)
    mac_address: str | None = Field(default=None, max_length=17)
    mac_status: str | None = Field(default=None, max_length=20)
    snmp_community: str = Field(default="public", max_length=255)
    host_pc: str | None = Field(default=None, max_length=255)

    is_online: bool | None = Field(default=None)
    status: str | None = Field(default=None, max_length=50)
    toner_black: int | None = Field(default=None)
    toner_cyan: int | None = Field(default=None)
    toner_magenta: int | None = Field(default=None)
    toner_yellow: int | None = Field(default=None)
    toner_black_name: str | None = Field(default=None, max_length=128)
    toner_cyan_name: str | None = Field(default=None, max_length=128)
    toner_magenta_name: str | None = Field(default=None, max_length=128)
    toner_yellow_name: str | None = Field(default=None, max_length=128)
    toner_updated_at: datetime | None = Field(default=None)
    last_polled_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)


class CartridgeStock(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    cartridge_name: str = Field(max_length=128, unique=True, index=True)
    toner_color: str | None = Field(default=None, max_length=16, index=True)
    compatible_printer_models: str = Field(default="", max_length=1024)
    printer_count: int = Field(default=0)
    quantity_on_hand: int = Field(default=0, index=True)
    minimum_stock: int = Field(default=0)
    is_active: bool = Field(default=True, index=True)
    last_synced_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)


class CartridgeStockMovement(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    stock_id: uuid.UUID = Field(index=True, foreign_key="cartridgestock.id")
    delta: int
    reason: str = Field(max_length=32, index=True)
    note: str | None = Field(default=None, max_length=512)
    created_by: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class NetworkSwitch(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255, index=True)
    ip_address: str = Field(max_length=45, unique=True, index=True)
    ssh_username: str = Field(max_length=128, default="admin")
    # Stored encrypted at rest (see app.core.crypto); column is wider than the
    # plaintext max to fit the Fernet token overhead.
    ssh_password: str = Field(
        default="", sa_column=Column(EncryptedString(512), nullable=False, server_default="")
    )
    enable_password: str = Field(
        default="", sa_column=Column(EncryptedString(512), nullable=False, server_default="")
    )
    ssh_port: int = Field(default=22)
    ap_vlan: int = Field(default=20)
    vendor: str = Field(default="cisco", max_length=32, index=True)
    management_protocol: str = Field(default="snmp+ssh", max_length=32)
    snmp_version: str = Field(default="2c", max_length=10)
    snmp_community_ro: str = Field(default="public", max_length=255)
    snmp_community_rw: str | None = Field(default=None, max_length=255)

    model_info: str | None = Field(default=None, max_length=255)
    ios_version: str | None = Field(default=None, max_length=255)
    hostname: str | None = Field(default=None, max_length=255)
    uptime: str | None = Field(default=None, max_length=255)
    is_online: bool | None = Field(default=None)
    last_polled_at: datetime | None = Field(default=None)

    # A stable identifier for MAC-based rediscovery if ip_address ever
    # changes (DHCP reservation slip, re-cabling). See app.services.
    # mac_rediscovery / app.services.switch_mac_lookup.
    mac_address: str | None = Field(default=None, max_length=17, index=True)
    mac_status: str | None = Field(default=None, max_length=20)

    # Scheduled Wi-Fi AP reboot (VLAN 20 only, see app.domains.inventory.ap_auto_reboot).
    # Opt-in per switch, and still gated by a global store allowlist so
    # enabling this toggle on the wrong switch can't reboot APs it shouldn't.
    auto_reboot_aps_enabled: bool = Field(default=False)
    auto_reboot_mode: str = Field(default="dry_run", max_length=10)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)


class SwitchAccessPoint(SQLModel, table=True):
    """A Wi-Fi AP ever seen on a switch's ap_vlan via CDP.

    CDP-based discovery only sees APs that are currently responding, so a
    hung AP is invisible to a live scan - exactly the one that most needs a
    reboot. This table remembers APs seen before so the auto-reboot cycle
    can also act on ones that have since gone quiet, instead of only ever
    reaching APs healthy enough to still announce themselves.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    switch_id: uuid.UUID = Field(index=True, foreign_key="networkswitch.id")
    mac_address: str = Field(max_length=17, index=True)
    port: str = Field(max_length=64)
    cdp_name: str | None = Field(default=None, max_length=255)
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_active: bool = Field(default=True)
    exclude_from_auto_reboot: bool = Field(default=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)


class SwitchPortSnapshot(SQLModel, table=True):
    """A point-in-time capture of a switch's port configuration.

    Written by the periodic snapshot task (app.domains.inventory.
    port_snapshot) only when the config actually changed since the last
    stored row, so an operator can see when a port's VLAN/description/trunk
    setup last drifted without needing a live SSH/SNMP session to the switch.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    switch_id: uuid.UUID = Field(index=True, foreign_key="networkswitch.id")
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    ports_hash: str = Field(max_length=64, index=True)
    ports_json: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))


class MediaPlayer(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    device_type: str = Field(max_length=20, index=True)
    name: str = Field(max_length=255, index=True)
    model: str = Field(max_length=255)
    ip_address: str = Field(max_length=45, unique=True, index=True)
    mac_address: str | None = Field(default=None, max_length=17)

    is_online: bool | None = Field(default=None)
    hostname: str | None = Field(default=None, max_length=255)
    os_info: str | None = Field(default=None, max_length=255)
    uptime: str | None = Field(default=None, max_length=100)
    open_ports: str | None = Field(default=None, max_length=500)
    last_polled_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)


class Computer(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hostname: str = Field(max_length=255, index=True)
    location: str | None = Field(default=None, max_length=128, index=True)
    comment: str | None = Field(default=None, max_length=1024)
    is_online: bool | None = Field(default=None, index=True)
    reachability_reason: str | None = Field(default=None, max_length=64)
    last_polled_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)

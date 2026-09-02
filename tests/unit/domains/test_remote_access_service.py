from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.domains.inventory.models import Computer, MediaPlayer
from app.domains.operations.models import CashRegister
from app.domains.remote_access import service
from app.domains.remote_access.models import RemoteAccessDevice


def _dev(db_session, hostname: str) -> RemoteAccessDevice:
    return db_session.exec(
        select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == hostname)
    ).first()


def test_generate_password_is_long_and_alnum() -> None:
    pw = service.generate_password()
    assert len(pw) == 20
    assert pw.isalnum()
    assert service.generate_password() != service.generate_password()


def test_hostname_to_rid_replaces_disallowed_chars() -> None:
    assert service._hostname_to_rid("VNK-MGR-D1") == "VNK_MGR_D1"
    assert service._hostname_to_rid("a" * 40) == "a" * 32


def test_seed_from_inventory_covers_registers_computers_and_nettops(db_session) -> None:
    db_session.add(Computer(hostname="VNA-MGR-101", location="A1"))
    db_session.add(Computer(hostname="VNA-MGR-102", location="A1"))
    db_session.add(
        CashRegister(kkm_number="K1", hostname="VNA-POS-01", store_number="099", kkm_type="retail")
    )
    db_session.add(
        MediaPlayer(
            device_type="nettop", name="TV-hall", model="nettop",
            ip_address="10.0.0.5", hostname="VNA-TV-01",
        )
    )
    db_session.add(
        MediaPlayer(
            device_type="iconbit", name="stick", model="iconbit",
            ip_address="10.0.0.6", hostname="VNA-STICK-01",
        )
    )
    db_session.commit()

    created = service.seed_from_inventory(db_session)
    assert created == 4  # 2 computers + 1 till + 1 nettop; the iconbit stick is skipped
    assert service.seed_from_inventory(db_session) == 0  # idempotent

    comp = _dev(db_session, "VNA-MGR-101")
    assert comp.rustdesk_id == "VNA_MGR_101" and comp.location == "A1"
    assert comp.source_kind == "computer" and comp.computer_id is not None

    till = _dev(db_session, "VNA-POS-01")
    assert till.source_kind == "cash_register" and till.cash_register_id is not None
    assert till.location == "099"

    tv = _dev(db_session, "VNA-TV-01")
    assert tv.source_kind == "media_player" and tv.media_player_id is not None

    assert _dev(db_session, "VNA-STICK-01") is None


def test_seed_marks_till_that_is_also_a_computer_as_cash_register(db_session) -> None:
    db_session.add(Computer(hostname="VNA-POS-09", location="Z1"))
    db_session.add(CashRegister(kkm_number="K9", hostname="VNA-POS-09", store_number="042"))
    db_session.commit()

    service.seed_from_inventory(db_session)
    dev = _dev(db_session, "VNA-POS-09")
    assert dev.source_kind == "cash_register"  # cash_register outranks computer
    assert dev.computer_id is not None and dev.cash_register_id is not None


def test_refresh_status_writes_host_online_not_rustdesk_online(db_session) -> None:
    polled = datetime.now(UTC) - timedelta(minutes=1)
    db_session.add(Computer(hostname="VNA-MGR-77", location="A1", is_online=True, last_polled_at=polled))
    db_session.commit()
    service.seed_from_inventory(db_session)

    touched = service.refresh_status_from_inventory(db_session)
    assert touched == 1
    dev = _dev(db_session, "VNA-MGR-77")
    # inventory reachability lands on host_online; the RustDesk-console field stays untouched
    assert dev.host_online is True and dev.host_last_seen_at is not None
    assert dev.online is None and dev.last_seen_at is None


def test_ensure_device_creates_links_and_mints_id_and_password(db_session) -> None:
    db_session.add(CashRegister(kkm_number="K7", hostname="VNA-POS-07", store_number="007"))
    db_session.commit()

    dev = service.ensure_device(db_session, hostname="VNA-POS-07")
    assert dev.source_kind == "cash_register" and dev.cash_register_id is not None
    assert dev.rustdesk_id == "VNA_POS_07"
    assert dev.permanent_password and dev.permanent_password.isalnum()
    assert dev.managed is True

    # explicit id + password on a second call
    dev2 = service.ensure_device(
        db_session, hostname="VNA-POS-07", rustdesk_id="VNA_POS_07_X", permanent_password="kentdful"
    )
    assert dev2.id == dev.id
    assert dev2.rustdesk_id == "VNA_POS_07_X" and dev2.permanent_password == "kentdful"


def test_rotate_password_changes_secret_only(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNK-MGR-D1", permanent_password="old")
    dev = service.rotate_password(db_session, dev)
    assert dev.permanent_password not in ("", "old")
    assert dev.password_rotated_at is not None


def test_package_config_carries_server_key_and_flags(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNK-MGR-05", permanent_password="pw123")
    dev.desired_block_outgoing = False
    db_session.add(dev)
    db_session.commit()

    cfg = service.package_config(dev)
    assert cfg["rustdesk_id"] == "VNK_MGR_05"
    assert cfg["permanent_password"] == "pw123"
    assert cfg["id_server"] and "key" in cfg
    assert cfg["block_outgoing"] is False and cfg["hidden"] is True


def test_ab_entry_tags_by_kind_and_location(db_session) -> None:
    db_session.add(CashRegister(kkm_number="K3", hostname="VNA-POS-03", store_number="003"))
    db_session.commit()
    service.seed_from_inventory(db_session)
    dev = _dev(db_session, "VNA-POS-03")

    entry = service._ab_entry(dev)
    assert entry["id"] == "VNA_POS_03"
    assert entry["alias"] == "VNA-POS-03"
    assert entry["tags"] == ["cash_register", "003"]


def test_sync_from_console_sets_online_only_for_devices_the_console_knows(db_session, monkeypatch) -> None:
    import asyncio

    db_session.add(Computer(hostname="VNA-MGR-101", location="A1"))
    db_session.add(Computer(hostname="VNA-MGR-102", location="A1"))
    db_session.commit()
    service.seed_from_inventory(db_session)
    # pretend both were "online" from an earlier (pre-split) run
    for h in ("VNA-MGR-101", "VNA-MGR-102"):
        d = _dev(db_session, h)
        d.online = True
        db_session.add(d)
    db_session.commit()

    async def fake_peers():
        return [{"id": "VNA_MGR_101", "info": {"device_name": "VNA-MGR-101", "username": "kassir"}, "status": 1}]

    async def fake_ab():
        return [{"id": "VNA_MGR_101", "online": True, "hostname": "vna-mgr-101"}]

    monkeypatch.setattr(service.rustdesk_client, "list_peers", fake_peers)
    monkeypatch.setattr(service.rustdesk_client, "get_address_book", fake_ab)

    res = asyncio.run(service.sync_from_console(db_session))
    assert res["peers_seen"] == 1

    a = _dev(db_session, "VNA-MGR-101")
    assert a.online is True and a.logged_in_user == "kassir" and a.last_seen_at is not None
    b = _dev(db_session, "VNA-MGR-102")
    assert b.online is None  # console never saw it -> stale True cleared


def test_resolve_scope_by_ids_location_kind_and_all(db_session) -> None:
    a = RemoteAccessDevice(hostname="h-a", location="A1", source_kind="computer")
    b = RemoteAccessDevice(hostname="h-b", location="A2", source_kind="cash_register")
    c = RemoteAccessDevice(hostname="h-c", location="A1", managed=False)
    db_session.add_all([a, b, c])
    db_session.commit()

    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=[a.id], location=None, all_managed=False)} == {
        "h-a"
    }
    # bulk scopes never touch unmanaged endpoints
    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=None, location="A1", all_managed=False)} == {
        "h-a",
    }
    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=None, location=None, all_managed=True)} == {
        "h-a",
        "h-b",
    }
    assert {
        d.hostname
        for d in service.resolve_scope(
            db_session, device_ids=None, location=None, all_managed=True, source_kind="computer"
        )
    } == {"h-a"}
    assert service.resolve_scope(db_session, device_ids=None, location=None, all_managed=False) == []

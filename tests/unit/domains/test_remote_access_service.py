from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.core.config import settings
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


def test_seed_from_inventory_does_not_duplicate_an_existing_hostname_by_case(db_session) -> None:
    # a row that already exists under different casing than inventory's -
    # e.g. minted earlier by sync_from_console off the client's self-reported
    # hostname (see test_ensure_device_matches_an_existing_hostname_case_insensitively)
    pre_existing = service.ensure_device(db_session, hostname="vna-mgr-77")
    db_session.add(Computer(hostname="VNA-MGR-77", location="A1"))
    db_session.commit()

    created = service.seed_from_inventory(db_session)
    assert created == 0
    rows = db_session.exec(
        select(RemoteAccessDevice).where(func.lower(RemoteAccessDevice.hostname) == "vna-mgr-77")
    ).all()
    assert rows == [pre_existing]
    assert pre_existing.computer_id is not None  # still got linked to the inventory row


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


def test_ensure_device_matches_an_existing_hostname_case_insensitively(db_session) -> None:
    """Windows hostnames are case-insensitive; a RustDesk client self-reporting
    "vna-mgr-101" (sync_from_console) must land on the same row inventory
    already seeded as "VNA-MGR-101" - not mint a second, forever-pending one.
    Caught live: 22 such duplicate rows appeared from one console sync pass."""
    dev = service.ensure_device(db_session, hostname="VNA-MGR-101", permanent_password="kentdful")
    dev2 = service.ensure_device(db_session, hostname="vna-mgr-101")
    assert dev2.id == dev.id
    assert dev2.hostname == "VNA-MGR-101"  # first-seen casing wins, not overwritten
    assert db_session.exec(
        select(RemoteAccessDevice).where(func.lower(RemoteAccessDevice.hostname) == "vna-mgr-101")
    ).all() == [dev]


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


def test_ab_payload_carries_tags_and_the_peer_password(db_session) -> None:
    db_session.add(CashRegister(kkm_number="K3", hostname="VNA-POS-03", store_number="003"))
    db_session.commit()
    service.seed_from_inventory(db_session)
    dev = _dev(db_session, "VNA-POS-03")
    dev.permanent_password = "kentdful"
    db_session.add(dev)
    db_session.commit()

    entry = service._ab_payload(dev, collection_id=7, owner_id=1)
    assert entry["id"] == "VNA_POS_03"
    assert entry["alias"] == "VNA-POS-03"
    # source_kind, store location, then the hostname's own role token (POS)
    assert entry["tags"] == ["cash_register", "003", "POS"]
    # a shared-book row stores the password in `password` (personal books use `hash`),
    # which is what lets an engineer connect without typing anything
    assert entry["password"] == "kentdful"
    assert entry["collection_id"] == 7 and entry["user_id"] == 1


def test_hostname_type_tag_reads_the_middle_segment_of_site_type_num_names() -> None:
    assert service.hostname_type_tag("VNA-KKM-1506") == "KKM"
    assert service.hostname_type_tag("VNK-MGR-D01") == "MGR"
    assert service.hostname_type_tag("VNA-TV-1301") == "TV"
    assert service.hostname_type_tag("VNA-MUZ-2601") == "MUZ"
    assert service.hostname_type_tag("VNK-SRV-LMG01") == "SRV"
    assert service.hostname_type_tag("vna-mgr-15") == "MGR"  # case-insensitive
    # a bare serial-like name has no site/type/num shape - left untagged
    assert service.hostname_type_tag("HPI2E8F25") is None
    # two segments only ("VNK-PROJECT03") - no reliable middle token either
    assert service.hostname_type_tag("VNK-PROJECT03") is None


def test_delete_device_removes_the_row_and_best_effort_cleans_up_its_book_entry(db_session, monkeypatch) -> None:
    import asyncio

    dev = service.ensure_device(db_session, hostname="VNA-JUNK-01", permanent_password="pw")
    dev.ab_row_id = 42
    dev.in_address_book = True
    db_session.add(dev)
    db_session.commit()
    dev_id = dev.id

    calls: list[tuple[int, str]] = []

    async def fake_delete_row(*, row_id: int, peer_id: str) -> None:
        calls.append((row_id, peer_id))

    monkeypatch.setattr(service.rustdesk_client, "delete_address_book_row", fake_delete_row)

    asyncio.run(service.delete_device(db_session, dev))

    assert calls == [(42, dev.rustdesk_id)]
    assert _dev(db_session, "VNA-JUNK-01") is None
    assert db_session.get(RemoteAccessDevice, dev_id) is None


def test_delete_device_still_drops_the_row_when_the_console_call_fails(db_session, monkeypatch) -> None:
    import asyncio

    dev = service.ensure_device(db_session, hostname="VNA-JUNK-02", permanent_password="pw")
    dev.ab_row_id = 7
    db_session.add(dev)
    db_session.commit()

    async def fake_delete_row(*, row_id: int, peer_id: str) -> None:
        raise RuntimeError("console is down")

    monkeypatch.setattr(service.rustdesk_client, "delete_address_book_row", fake_delete_row)

    asyncio.run(service.delete_device(db_session, dev))  # must not raise
    assert _dev(db_session, "VNA-JUNK-02") is None


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
        return [
            {
                "id": "VNA_MGR_101",
                "hostname": "VNA-MGR-101",
                "username": "kassir",
                "version": "1.4.9",
                "last_online_ip": "10.10.99.51",
                "last_online_time": int(datetime.now(UTC).timestamp()),
            }
        ]

    monkeypatch.setattr(service.rustdesk_client, "list_admin_peers", fake_peers)

    res = asyncio.run(service.sync_from_console(db_session))
    assert res["peers_seen"] == 1

    a = _dev(db_session, "VNA-MGR-101")
    assert a.online is True and a.logged_in_user == "kassir" and a.last_seen_at is not None
    # the admin peer list is the only source that carries these
    assert a.installed_version == "1.4.9" and a.last_ip == "10.10.99.51"
    b = _dev(db_session, "VNA-MGR-102")
    assert b.online is None  # console never saw it -> stale True cleared


def test_sync_from_console_marks_a_long_silent_peer_offline(db_session, monkeypatch) -> None:
    import asyncio

    db_session.add(Computer(hostname="VNA-MGR-201", location="A1"))
    db_session.commit()
    service.seed_from_inventory(db_session)

    stale = int((datetime.now(UTC) - timedelta(hours=3)).timestamp())

    async def fake_peers():
        return [{"id": "VNA_MGR_201", "hostname": "VNA-MGR-201", "last_online_time": stale}]

    monkeypatch.setattr(service.rustdesk_client, "list_admin_peers", fake_peers)
    asyncio.run(service.sync_from_console(db_session))

    # the console knows the peer (so not None) but it has not checked in
    assert _dev(db_session, "VNA-MGR-201").online is False


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


# --------------------------------------------------------------------------- #
# rollout state                                                               #
# --------------------------------------------------------------------------- #
def test_readiness_needs_both_the_endpoint_report_and_the_console(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNK-MGR-D1")

    # nothing known at all
    assert service.readiness(dev) == "not_deployed"

    dev.deploy_state = "pending"
    assert service.readiness(dev) == "deploying"

    dev.deploy_state = "failed"
    assert service.readiness(dev) == "failed"

    # the machine applied the config but the console cannot see it -> not connectable
    dev.deploy_state = "configured"
    dev.online = False
    assert service.readiness(dev) == "installed_offline"

    dev.online = True
    assert service.readiness(dev) == "ready"


def test_readiness_trusts_the_console_for_machines_deployed_before_infrascope(db_session) -> None:
    # rolled out by hand / by the old KSC package: no report will ever arrive
    dev = service.ensure_device(db_session, hostname="VNA-MGR-901")
    dev.online = True
    assert service.readiness(dev) == "ready"
    dev.online = False
    assert service.readiness(dev) == "installed_offline"


def test_apply_deploy_report_records_what_the_endpoint_said(db_session) -> None:
    service.ensure_device(db_session, hostname="VNA-MGR-301")

    dev = service.apply_deploy_report(
        db_session,
        hostname="VNA-MGR-301",
        state="configured",
        rustdesk_id="VNA_MGR_301",
        version="1.4.9",
    )
    assert dev.deploy_state == "configured" and dev.installed_version == "1.4.9"
    assert dev.deploy_reported_at is not None

    dev = service.apply_deploy_report(
        db_session, hostname="VNA-MGR-301", state="failed", detail="msiexec exit 1603"
    )
    assert dev.deploy_state == "failed" and dev.deploy_detail == "msiexec exit 1603"


def test_apply_deploy_report_ignores_hosts_we_do_not_track(db_session) -> None:
    # a report must never conjure a device row - that would let any caller with
    # the deploy token seed the fleet inventory
    assert service.apply_deploy_report(db_session, hostname="STRANGER-01", state="configured") is None


def test_mark_deploy_requested_clears_a_previous_failure(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-302")
    service.apply_deploy_report(db_session, hostname="VNA-MGR-302", state="failed", detail="boom")

    dev = service.mark_deploy_requested(db_session, dev)
    assert dev.deploy_state == "pending"
    assert dev.deploy_detail is None and dev.deploy_requested_at is not None
    assert service.readiness(dev) == "deploying"


def test_deployment_config_keeps_the_write_locks_out_of_the_first_pass(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-POS-11", permanent_password="kentdful")

    cfg = service.deployment_config(dev)
    assert cfg["permanent_password"] == "kentdful"
    assert cfg["options"]["approve-mode"] == "password"
    assert cfg["options"]["allow-logon-screen-password"] == "Y"
    assert cfg["options"]["hide-tray"] == "Y"
    # disable-change-permanent-password would make `--password` a no-op, so it
    # must only appear in the pass that runs after the password is set
    assert "disable-change-permanent-password" not in cfg["options"]
    assert cfg["lock_options"]["disable-change-permanent-password"] == "Y"


def test_deployment_config_drops_the_locks_for_an_attended_device(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-303")
    dev.desired_unattended = False
    dev.desired_hidden = False
    db_session.add(dev)
    db_session.commit()

    cfg = service.deployment_config(dev)
    assert cfg["lock_options"] == {}
    assert "approve-mode" not in cfg["options"] and "hide-tray" not in cfg["options"]


def test_rotate_password_marks_the_address_book_row_stale(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-304")
    dev.in_address_book = True
    dev.ab_password_pushed = True
    db_session.add(dev)
    db_session.commit()

    dev = service.rotate_password(db_session, dev)
    # the console still hands out the old password until the next push
    assert dev.ab_password_pushed is False and dev.in_address_book is True


# --------------------------------------------------------------------------- #
# endpoint script                                                             #
# --------------------------------------------------------------------------- #
def test_bootstrap_script_installs_silently_and_leaves_no_shortcuts(monkeypatch) -> None:
    from app.domains.remote_access import deploy_script

    monkeypatch.setattr(settings, "RUSTDESK_PUBLIC_URL", "http://10.10.99.24:8000")
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "s3cr3t")

    script = deploy_script.render_bootstrap()
    assert "http://10.10.99.24:8000/api/v1/remote-access/deploy" in script
    assert "s3cr3t" in script
    # /qn returns a real exit code, unlike `--silent-install`
    assert "'/qn'" in script and "CREATEDESKTOPSHORTCUTS=N" in script
    assert "CREATESTARTMENUSHORTCUTS=N" in script and "INSTALLPRINTER=N" in script
    # a failed run must not leave the device stuck on "deploying"
    assert "Report 'failed'" in script


def test_deploy_command_is_one_pasteable_line(monkeypatch) -> None:
    from app.domains.remote_access import deploy_script

    monkeypatch.setattr(settings, "RUSTDESK_PUBLIC_URL", "http://10.10.99.24:8000/")
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "s3cr3t")

    cmd = deploy_script.deploy_command()
    assert "\n" not in cmd
    assert "X-InfraScope-Deploy-Token" in cmd and "s3cr3t" in cmd
    assert "//10.10.99.24:8000/api/v1" in cmd  # trailing slash on the base is trimmed


def test_bootstrap_script_self_reports_the_windows_edition(monkeypatch) -> None:
    from app.domains.remote_access import deploy_script

    monkeypatch.setattr(settings, "RUSTDESK_PUBLIC_URL", "http://10.10.99.24:8000")
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "s3cr3t")

    script = deploy_script.render_bootstrap()
    # EditionID (locale-independent) is what block_outgoing's AppLocker step
    # needs; the report carries it on every state, not just success
    assert "EditionID" in script
    assert "os_edition = $OsEdition" in script and "os_caption = $OsCaption" in script


# --------------------------------------------------------------------------- #
# AppLocker support classification                                            #
# --------------------------------------------------------------------------- #
def test_classify_applocker_support_flags_home_editions(db_session) -> None:
    del db_session  # unused; keeps the module's fixture-per-test convention
    assert service.classify_applocker_support(None) is None
    assert service.classify_applocker_support("") is None
    assert service.classify_applocker_support("Core") is False  # Home
    assert service.classify_applocker_support("CoreSingleLanguage") is False
    assert service.classify_applocker_support("CoreCountrySpecific") is False
    assert service.classify_applocker_support("CoreN") is False
    assert service.classify_applocker_support("Professional") is True
    assert service.classify_applocker_support("ProfessionalN") is True
    assert service.classify_applocker_support("Enterprise") is True
    assert service.classify_applocker_support("Education") is True
    assert service.classify_applocker_support("ServerStandard") is True


def test_apply_deploy_report_records_edition_and_derives_applocker_support(db_session) -> None:
    service.ensure_device(db_session, hostname="VNA-MGR-305")

    dev = service.apply_deploy_report(
        db_session,
        hostname="VNA-MGR-305",
        state="configured",
        os_edition="Core",
        os_caption="Windows 10 Домашняя для одного языка",
    )
    assert dev.os_edition == "Core"
    assert dev.os_caption == "Windows 10 Домашняя для одного языка"
    assert dev.applocker_supported is False

    # a later report with no edition (e.g. a retry that failed before reading
    # it) must not erase what we already learned
    dev = service.apply_deploy_report(db_session, hostname="VNA-MGR-305", state="configured")
    assert dev.os_edition == "Core" and dev.applocker_supported is False


def test_apply_deploy_report_with_a_capable_edition(db_session) -> None:
    service.ensure_device(db_session, hostname="VNA-MGR-306")
    dev = service.apply_deploy_report(
        db_session, hostname="VNA-MGR-306", state="configured", os_edition="Professional"
    )
    assert dev.applocker_supported is True


# --------------------------------------------------------------------------- #
# stale config (redeploy needed)                                              #
# --------------------------------------------------------------------------- #
def test_rotate_password_marks_a_configured_device_stale(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-307")
    service.apply_deploy_report(db_session, hostname="VNA-MGR-307", state="configured")

    dev = service.rotate_password(db_session, dev)
    assert dev.deploy_state == "stale"
    assert service.readiness(dev) == "stale"


def test_rotate_password_does_not_invent_deploy_history(db_session) -> None:
    # a device InfraScope has never rolled out has nothing to go stale from -
    # rotating its password ahead of the first deploy must not claim otherwise
    dev = service.ensure_device(db_session, hostname="VNA-MGR-308")
    assert dev.deploy_state == "unknown"

    dev = service.rotate_password(db_session, dev)
    assert dev.deploy_state == "unknown"
    assert service.readiness(dev) == "not_deployed"


def test_ensure_device_marks_stale_only_on_an_actual_change(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-309", permanent_password="pw1")
    service.apply_deploy_report(db_session, hostname="VNA-MGR-309", state="configured")

    # re-saving the same password must not manufacture staleness
    dev = service.ensure_device(db_session, hostname="VNA-MGR-309", permanent_password="pw1")
    assert dev.deploy_state == "configured"

    # a genuinely new password does
    dev = service.ensure_device(db_session, hostname="VNA-MGR-309", permanent_password="pw2")
    assert dev.deploy_state == "stale"


def test_mark_config_stale_is_a_noop_before_first_deploy(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-310")
    service.mark_config_stale(dev)
    assert dev.deploy_state == "unknown"


def test_deploy_report_reaching_configured_clears_staleness(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-311")
    service.apply_deploy_report(db_session, hostname="VNA-MGR-311", state="configured")
    dev = service.rotate_password(db_session, dev)
    assert dev.deploy_state == "stale"

    # the operator reruns the rollout; the script reapplies everything and
    # reports success again, which clears the staleness naturally
    dev = service.apply_deploy_report(db_session, hostname="VNA-MGR-311", state="configured")
    assert dev.deploy_state == "configured"
    assert service.readiness(dev) in ("ready", "installed_offline")


def test_deploy_command_bypasses_the_self_signed_cert_before_downloading(monkeypatch) -> None:
    """nginx hard-redirects :80 to :443 with a self-signed cert (LAN-only, no
    public IP) - Windows PowerShell 5.1's WebClient rejects that by default
    with a generic "unable to create a secure channel" error that gives no
    hint it's a cert problem. Verified live against a real fleet machine
    before this was added: the download died silently, no log, no report.
    The bypass must land BEFORE the WebClient is even constructed."""
    from app.domains.remote_access import deploy_script

    monkeypatch.setattr(settings, "RUSTDESK_PUBLIC_URL", "https://10.10.99.24")
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "s3cr3t")

    cmd = deploy_script.deploy_command()
    bypass = cmd.index("ServerCertificateValidationCallback")
    webclient = cmd.index("New-Object Net.WebClient")
    assert bypass < webclient
    assert "SecurityProtocolType]::Tls12" in cmd


def test_deploy_command_logs_locally_when_the_bootstrap_fetch_itself_fails(monkeypatch) -> None:
    """This line runs before the downloaded script's own logging exists, so a
    failure here has nowhere to go except a local file - InfraScope can't
    learn about it either, since reporting needs this same HTTP call to work.
    Verified live on VNA-MGR-04: its PowerShell hosts .NET CLR 2.0, which
    predates TLS 1.1/1.2 support in ServicePointManager - `Tls12` isn't a
    valid enum member there, so the very first line throws with no trace
    anywhere. The catch block must write to the same log file the downloaded
    script uses, and name the CLR-too-old case specifically since no
    registry/GPO fix helps it - only a WMF upgrade or the offline package do."""
    from app.domains.remote_access import deploy_script

    monkeypatch.setattr(settings, "RUSTDESK_PUBLIC_URL", "https://10.10.99.24")
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "s3cr3t")

    cmd = deploy_script.deploy_command()
    assert "try{" in cmd and "}catch{" in cmd
    assert "rustdesk-configure.log" in cmd
    assert "SecurityProtocolType" in cmd.split("}catch{")[1]  # the CLR-too-old hint check
    assert "offline rustdesk-ksc package" in cmd


def test_bootstrap_script_is_self_sufficient_against_the_same_cert(monkeypatch) -> None:
    from app.domains.remote_access import deploy_script

    monkeypatch.setattr(settings, "RUSTDESK_PUBLIC_URL", "https://10.10.99.24")
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "s3cr3t")

    script = deploy_script.render_bootstrap()
    assert "ServerCertificateValidationCallback" in script


def test_applocker_rule_ids_are_valid_guids() -> None:
    """`Set-AppLockerPolicy` validates each FilePathRule Id against the GUID
    schema and rejects the *whole* policy on one bad id - with no indication
    in the log that it was the id, not the environment, that failed. Caught
    live on VNA-MGR-15: the old "...infrascope01" id has letters outside a-f
    and silently killed block_outgoing on every machine this ever ran on."""
    import re

    from app.domains.remote_access import deploy_script

    guid_re = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    script = deploy_script.render_bootstrap()
    ids = re.findall(r'FilePathRule Id="([^"]+)"', script)
    assert len(ids) == 3
    for rule_id in ids:
        assert guid_re.match(rule_id), f"{rule_id!r} is not a valid GUID"


# --------------------------------------------------------------------------- #
# client vs admin deploy profile                                              #
# --------------------------------------------------------------------------- #
def test_new_devices_default_to_the_client_profile(db_session) -> None:
    # the fleet is overwhelmingly store kiosks/kassa - "client" (locked down)
    # must be the safe default, never "admin" (full, unrestricted access)
    dev = service.ensure_device(db_session, hostname="VNA-MGR-401")
    assert dev.deploy_profile == "client"
    assert dev.desired_hidden is True and dev.desired_block_outgoing is True


def test_admin_profile_gives_an_engineer_workstation_full_normal_access(db_session) -> None:
    # found live: an engineer's own workstation (VNK-ITD-SA05) seeded with
    # client defaults would hide its own tray icon and AppLocker-block the
    # engineer from launching RustDesk themselves - exactly backwards
    dev = service.ensure_device(db_session, hostname="VNK-ITD-SA05")
    dev = service.apply_deploy_profile(db_session, dev, "admin")
    assert dev.deploy_profile == "admin"
    assert dev.desired_hidden is False
    assert dev.desired_block_outgoing is False
    assert dev.desired_unattended is False


def test_apply_deploy_profile_rejects_an_unknown_name(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-402")
    with pytest.raises(ValueError, match="unknown deploy profile"):
        service.apply_deploy_profile(db_session, dev, "superadmin")


def test_switching_profile_on_a_configured_device_marks_it_stale(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-403")
    service.apply_deploy_report(db_session, hostname="VNA-MGR-403", state="configured")

    dev = service.apply_deploy_profile(db_session, dev, "admin")
    assert dev.deploy_state == "stale"
    assert service.readiness(dev) == "stale"


def test_reapplying_the_same_profile_is_not_stale(db_session) -> None:
    dev = service.ensure_device(db_session, hostname="VNA-MGR-404")
    service.apply_deploy_report(db_session, hostname="VNA-MGR-404", state="configured")

    # already "client" (the default) - setting it again changes nothing
    dev = service.apply_deploy_profile(db_session, dev, "client")
    assert dev.deploy_state == "configured"

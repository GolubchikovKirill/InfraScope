"""Remote-access API routes: /deploy/* (called by the endpoint script itself,
no InfraScope session - go through `client` + the shared deploy token rather
than `admin_token`/`user_token`) and the operator-facing /devices list."""

import asyncio

from app.core.config import settings
from app.domains.remote_access import service


def _configure_deploy(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "s3cr3t")
    monkeypatch.setattr(settings, "RUSTDESK_PUBLIC_URL", "https://10.10.99.24")


def test_deploy_config_served_when_the_caller_is_the_device_itself(client, db_session, monkeypatch):
    _configure_deploy(monkeypatch)
    service.ensure_device(db_session, hostname="VNA-MGR-501", permanent_password="kentdful")
    # no console history yet (last_ip unset) - falls through to the DNS lookup
    monkeypatch.setattr(service, "_resolve_hostname_ip", lambda h: "10.10.99.51")

    resp = client.post(
        "/api/v1/remote-access/deploy/config",
        json={"hostname": "VNA-MGR-501"},
        headers={"X-InfraScope-Deploy-Token": "s3cr3t", "X-Real-IP": "10.10.99.51"},
    )
    assert resp.status_code == 200
    assert resp.json()["permanent_password"] == "kentdful"


def test_deploy_config_refused_when_the_caller_is_a_different_machine(client, db_session, monkeypatch):
    # the exact scenario this guards: a stolen/leftover deploy token, used from
    # some other endpoint to fish a different device's password out of its row
    _configure_deploy(monkeypatch)
    service.ensure_device(db_session, hostname="VNA-MGR-502", permanent_password="kentdful")
    monkeypatch.setattr(service, "_resolve_hostname_ip", lambda h: "10.10.99.52")

    resp = client.post(
        "/api/v1/remote-access/deploy/config",
        json={"hostname": "VNA-MGR-502"},
        headers={"X-InfraScope-Deploy-Token": "s3cr3t", "X-Real-IP": "10.10.99.99"},
    )
    assert resp.status_code == 404
    assert "permanent_password" not in resp.text


def test_deploy_config_accepts_a_console_seen_ip_even_if_dns_disagrees(client, db_session, monkeypatch):
    # last_ip (what the console actually saw this device connect from) is
    # trusted on its own - a stale/wrong DNS record must not block a device
    # the fleet has already talked to
    _configure_deploy(monkeypatch)
    dev = service.ensure_device(db_session, hostname="VNA-MGR-503", permanent_password="kentdful")
    dev.last_ip = "10.10.99.53"
    db_session.add(dev)
    db_session.commit()
    monkeypatch.setattr(service, "_resolve_hostname_ip", lambda h: "10.10.99.254")  # stale on purpose

    resp = client.post(
        "/api/v1/remote-access/deploy/config",
        json={"hostname": "VNA-MGR-503"},
        headers={"X-InfraScope-Deploy-Token": "s3cr3t", "X-Real-IP": "10.10.99.53"},
    )
    assert resp.status_code == 200


def test_deploy_config_refused_with_no_signal_at_all(client, db_session, monkeypatch):
    # never seen by the console (no last_ip) and DNS can't resolve it either -
    # exactly what a stolen token used against a name that doesn't exist looks like
    _configure_deploy(monkeypatch)
    service.ensure_device(db_session, hostname="VNA-MGR-504", permanent_password="kentdful")
    monkeypatch.setattr(service, "_resolve_hostname_ip", lambda h: None)

    resp = client.post(
        "/api/v1/remote-access/deploy/config",
        json={"hostname": "VNA-MGR-504"},
        headers={"X-InfraScope-Deploy-Token": "s3cr3t", "X-Real-IP": "10.10.99.60"},
    )
    assert resp.status_code == 404


def test_list_devices_hides_soft_deleted_ones_by_default(client, db_session, user_token: str):
    dev = service.ensure_device(db_session, hostname="VNA-MGR-901")
    asyncio.run(service.delete_device(db_session, dev))
    service.ensure_device(db_session, hostname="VNA-MGR-902")

    resp = client.get(
        "/api/v1/remote-access/devices", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert resp.status_code == 200
    hostnames = {d["hostname"] for d in resp.json()["data"]}
    assert hostnames == {"VNA-MGR-902"}

    resp = client.get(
        "/api/v1/remote-access/devices",
        params={"include_unmanaged": True},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert {d["hostname"] for d in resp.json()["data"]} == {"VNA-MGR-901", "VNA-MGR-902"}

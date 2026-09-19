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


# The `client` fixture (see conftest.py) monkeypatches slowapi's own check to a
# no-op for every test - these two just confirm the rate-limit decorator
# (which requires a `request: Request` param the routes didn't take before)
# didn't break the routes it was added to.
def test_deploy_bootstrap_still_works_with_the_rate_limit_decorator(client, monkeypatch):
    _configure_deploy(monkeypatch)
    resp = client.get(
        "/api/v1/remote-access/deploy/bootstrap.ps1",
        headers={"X-InfraScope-Deploy-Token": "s3cr3t"},
    )
    assert resp.status_code == 200
    assert "InfraScope" in resp.text


def test_deploy_report_still_works_with_the_rate_limit_decorator(client, db_session, monkeypatch):
    _configure_deploy(monkeypatch)
    service.ensure_device(db_session, hostname="VNA-MGR-505")

    resp = client.post(
        "/api/v1/remote-access/deploy/report",
        json={"hostname": "VNA-MGR-505", "state": "configured"},
        headers={"X-InfraScope-Deploy-Token": "s3cr3t"},
    )
    assert resp.status_code == 200


def _fake_peers(monkeypatch, peers, *, enabled=True):
    async def fake_peers():
        return peers

    monkeypatch.setattr(service.rustdesk_client, "list_admin_peers", fake_peers)
    monkeypatch.setattr(service.rustdesk_client, "enabled", lambda: enabled)
    from app.api.routes import remote_access as routes

    monkeypatch.setattr(routes.rustdesk_client, "enabled", lambda: enabled)


def test_unlisted_console_peers_is_superuser_only(client, user_token: str, monkeypatch):
    _fake_peers(monkeypatch, [{"id": "a", "hostname": "vnk-itd-sa03"}])

    resp = client.get("/api/v1/remote-access/console-peers/unlisted", headers={"Authorization": f"Bearer {user_token}"})

    assert resp.status_code in (401, 403)


def test_unlisted_console_peers_lists_untracked_machines(client, admin_token: str, monkeypatch):
    _fake_peers(monkeypatch, [{"id": "VNKITDSA03", "hostname": "vnk-itd-sa03", "os": "windows"}])

    resp = client.get("/api/v1/remote-access/console-peers/unlisted", headers={"Authorization": f"Bearer {admin_token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1 and body["console_reachable"] is True
    assert body["data"][0]["hostname"] == "vnk-itd-sa03"
    assert body["data"][0]["suggested_profile"] == "admin"


def test_unlisted_console_peers_survives_an_unreachable_console(client, admin_token: str, monkeypatch):
    async def boom():
        raise ConnectionError("console down")

    _fake_peers(monkeypatch, [])
    monkeypatch.setattr(service.rustdesk_client, "list_admin_peers", boom)

    resp = client.get("/api/v1/remote-access/console-peers/unlisted", headers={"Authorization": f"Bearer {admin_token}"})

    assert resp.status_code == 200
    assert resp.json() == {"data": [], "count": 0, "nameless_peers": 0, "console_reachable": False}


def test_unlisted_console_peers_reports_console_not_configured(client, admin_token: str, monkeypatch):
    _fake_peers(monkeypatch, [{"id": "a", "hostname": "x-itd-1"}], enabled=False)

    resp = client.get("/api/v1/remote-access/console-peers/unlisted", headers={"Authorization": f"Bearer {admin_token}"})

    assert resp.json()["console_reachable"] is False


def test_adopt_then_the_machine_is_in_the_device_list(client, admin_token: str, user_token: str, monkeypatch):
    headers = {"Authorization": f"Bearer {admin_token}"}

    adopted = client.post("/api/v1/remote-access/console-peers/adopt", json={"hostname": "vnk-itd-sa03"}, headers=headers)

    assert adopted.status_code == 200
    assert adopted.json()["hostname"] == "vnk-itd-sa03"
    assert adopted.json()["deploy_profile"] == "admin"
    listing = client.get("/api/v1/remote-access/devices", headers={"Authorization": f"Bearer {user_token}"})
    assert "vnk-itd-sa03" in [d["hostname"] for d in listing.json()["data"]]


def test_adopt_and_dismiss_require_a_superuser(client, user_token: str):
    headers = {"Authorization": f"Bearer {user_token}"}

    adopt = client.post("/api/v1/remote-access/console-peers/adopt", json={"hostname": "vnk-itd-sa03"}, headers=headers)
    dismiss = client.post("/api/v1/remote-access/console-peers/dismiss", json={"hostname": "vnk-itd-sa03"}, headers=headers)

    assert adopt.status_code in (401, 403)
    assert dismiss.status_code in (401, 403)


def test_dismissed_machine_stays_out_of_the_default_device_list(client, admin_token: str, user_token: str):
    resp = client.post(
        "/api/v1/remote-access/console-peers/dismiss",
        json={"hostname": "macbook-pro"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200
    listing = client.get("/api/v1/remote-access/devices", headers={"Authorization": f"Bearer {user_token}"})
    assert "macbook-pro" not in [d["hostname"] for d in listing.json()["data"]]


def test_adopt_rejects_a_malformed_hostname(client, admin_token: str):
    resp = client.post(
        "/api/v1/remote-access/console-peers/adopt",
        json={"hostname": "bad host!"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 422

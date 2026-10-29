from app.api.routes import computers as computer_routes
from app.domains.inventory import computer_polling
from app.domains.inventory.reachability import ReachabilityResult


class _BusyRedis:
    async def set(self, *_args, **_kwargs):
        return False

    async def delete(self, *_args, **_kwargs):
        return 0


def test_computers_list_requires_auth(client):
    response = client.get("/api/v1/computers/")
    assert response.status_code == 401


def test_create_list_search_and_duplicate_computers(client, admin_token: str, monkeypatch):
    async def _noop_invalidate():
        return None

    monkeypatch.setattr(computer_routes, "invalidate_computer_cache", _noop_invalidate)

    created = client.post(
        "/api/v1/computers/",
        json={
            "hostname": "VNK-MGR-01",
            "location": "A1",
            "comment": "office",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["hostname"] == "VNK-MGR-01"

    duplicate = client.post(
        "/api/v1/computers/",
        json={
            "hostname": "VNK-MGR-01",
            "location": "A1",
            "comment": "duplicate",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert duplicate.status_code == 409

    listing = client.get(
        "/api/v1/computers/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listing.status_code == 200
    assert listing.json()["count"] == 1

    search = client.get(
        "/api/v1/computers/",
        params={"q": "mgr a1"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert search.status_code == 200
    assert search.json()["count"] == 1


def test_update_delete_and_poll_computer(client, admin_token: str, monkeypatch):
    async def _noop_invalidate():
        return None

    monkeypatch.setattr(computer_routes, "invalidate_computer_cache", _noop_invalidate)
    async def _probe(hostname):
        return ReachabilityResult(
            is_online=hostname == "VNK-MGR-ONLINE",
            reason=None if hostname == "VNK-MGR-ONLINE" else "port_closed",
        )

    monkeypatch.setattr(computer_routes, "probe_computer", _probe)

    created = client.post(
        "/api/v1/computers/",
        json={
            "hostname": "VNK-MGR-OFFLINE",
            "location": "A2",
            "comment": "before update",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    computer_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/computers/{computer_id}",
        json={
            "hostname": "VNK-MGR-ONLINE",
            "location": "A3",
            "comment": "after update",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert updated.status_code == 200
    assert updated.json()["location"] == "A3"

    polled = client.post(
        f"/api/v1/computers/{computer_id}/poll",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert polled.status_code == 200
    assert polled.json()["is_online"] is True
    assert polled.json()["reachability_reason"] is None

    deleted = client.delete(
        f"/api/v1/computers/{computer_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deleted.status_code == 200

    listing = client.get(
        "/api/v1/computers/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listing.status_code == 200
    assert listing.json()["count"] == 0


def test_poll_all_computers_updates_rows(client, admin_token: str, monkeypatch):
    async def _noop_invalidate():
        return None

    monkeypatch.setattr(computer_routes, "invalidate_computer_cache", _noop_invalidate)
    monkeypatch.setattr(computer_polling, "invalidate_computer_cache", _noop_invalidate)
    probe_map = {
        "VNK-MGR-01": ReachabilityResult(is_online=True),
        "VNK-MGR-02": ReachabilityResult(is_online=False, reason="dns_unresolved"),
    }
    async def _probe(hostname):
        return probe_map[hostname]

    monkeypatch.setattr(computer_polling, "probe_computer", _probe)

    for hostname in probe_map:
        response = client.post(
            "/api/v1/computers/",
            json={"hostname": hostname, "location": "A1"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    poll_all = client.post(
        "/api/v1/computers/poll-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert poll_all.status_code == 200
    body = poll_all.json()
    assert body["count"] == 2
    statuses = {item["hostname"]: (item["is_online"], item["reachability_reason"]) for item in body["data"]}
    assert statuses["VNK-MGR-01"] == (True, None)
    assert statuses["VNK-MGR-02"] == (False, "dns_unresolved")


def test_poll_all_computers_skips_duplicate_network_scan(client, admin_token: str, monkeypatch):
    async def _noop_invalidate():
        return None

    async def _busy_redis():
        return _BusyRedis()

    monkeypatch.setattr(computer_routes, "invalidate_computer_cache", _noop_invalidate)
    monkeypatch.setattr(computer_polling, "invalidate_computer_cache", _noop_invalidate)
    monkeypatch.setattr(computer_polling, "get_redis", _busy_redis)
    monkeypatch.setattr(
        computer_polling,
        "probe_computers_bulk",
        lambda _rows: (_ for _ in ()).throw(AssertionError("duplicate poll should not probe network")),
    )

    created = client.post(
        "/api/v1/computers/",
        json={"hostname": "VNK-MGR-BUSY", "location": "A1"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200

    poll_all = client.post(
        "/api/v1/computers/poll-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert poll_all.status_code == 200
    assert poll_all.json()["count"] == 1
    assert poll_all.json()["data"][0]["hostname"] == "VNK-MGR-BUSY"


def test_discover_adds_screens_from_dns_and_probes_them(client, admin_token: str, user_token: str, monkeypatch):
    from app.core.config import settings
    from app.domains.inventory import network_discovery

    async def _noop_invalidate():
        return None

    async def _probe(hostname):
        return ReachabilityResult(is_online=hostname == "VNA-TV-1301", reason=None if hostname == "VNA-TV-1301" else "port_closed")

    monkeypatch.setattr(network_discovery, "invalidate_computer_cache", _noop_invalidate)
    monkeypatch.setattr(computer_polling, "probe_computer", _probe)
    monkeypatch.setattr(settings, "DNS_DISCOVERY_ROLES", "TV")
    monkeypatch.setattr(settings, "REMOTE_ACCESS_ENABLED", False)
    monkeypatch.setattr(
        network_discovery,
        "zone_a_records",
        lambda server, zone: {"vna-tv-1301": "172.23.4.5", "vna-tv-902": "10.10.98.205", "vna-kkm-101": "10.1.1.1"},
    )

    assert client.post("/api/v1/computers/discover", headers={"Authorization": f"Bearer {user_token}"}).status_code == 403

    response = client.post("/api/v1/computers/discover", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200, response.text
    assert response.json()["added"] == ["VNA-TV-1301", "VNA-TV-902"]
    listed = client.get("/api/v1/computers/?limit=50", headers={"Authorization": f"Bearer {admin_token}"}).json()
    states = {row["hostname"]: row["is_online"] for row in listed["data"]}
    assert states == {"VNA-TV-1301": True, "VNA-TV-902": False}

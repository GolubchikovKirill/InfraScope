from app.api.routes import computers as computer_routes


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

    monkeypatch.setattr(computer_routes, "_invalidate_cache", _noop_invalidate)

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

    monkeypatch.setattr(computer_routes, "_invalidate_cache", _noop_invalidate)
    monkeypatch.setattr(
        computer_routes,
        "_probe_computer",
        lambda hostname: (hostname == "VNK-MGR-ONLINE", None if hostname == "VNK-MGR-ONLINE" else "port_closed"),
    )

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

    monkeypatch.setattr(computer_routes, "_invalidate_cache", _noop_invalidate)
    probe_map = {
        "VNK-MGR-01": (True, None),
        "VNK-MGR-02": (False, "dns_unresolved"),
    }
    monkeypatch.setattr(computer_routes, "_probe_computer", lambda hostname: probe_map[hostname])

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

    monkeypatch.setattr(computer_routes, "_invalidate_cache", _noop_invalidate)
    monkeypatch.setattr(computer_routes, "get_redis", _busy_redis)
    monkeypatch.setattr(
        computer_routes,
        "_probe_computers_bulk",
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

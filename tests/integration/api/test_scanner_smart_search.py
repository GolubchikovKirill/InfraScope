from app.api.routes import scanner as scanner_routes


def test_smart_search_computers_requires_auth(client):
    response = client.post(
        "/api/v1/scanner/smart-search/computers",
        json={"hostname_contains": "MGR", "limit": 10},
    )
    assert response.status_code == 401


def test_smart_search_cash_registers_requires_auth(client):
    response = client.post(
        "/api/v1/scanner/smart-search/cash-registers",
        json={"hostname_contains": "KKM", "limit": 10},
    )
    assert response.status_code == 401


def test_smart_search_computers_filters_and_ranks(client, admin_token: str, monkeypatch):
    async def _fake_probe(_subnet: str, _ports: str):
        return [
            {"ip": "10.0.0.10", "hostname": "VNA-MGR-1201", "open_ports": [3389, 445]},
            {"ip": "10.0.0.11", "hostname": "PRINTER-1", "open_ports": [9100]},
            {"ip": "10.0.0.12", "hostname": "MGR-NODE", "open_ports": [135]},
        ]

    monkeypatch.setattr(scanner_routes, "smart_probe_network", _fake_probe)

    response = client.post(
        "/api/v1/scanner/smart-search/computers",
        json={"hostname_contains": "MGR", "limit": 50},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["data"][0]["hostname"] == "VNA-MGR-1201"
    assert payload["data"][0]["confidence"] == "high"


def test_smart_search_cash_registers_filters_and_ranks(client, admin_token: str, monkeypatch):
    async def _fake_probe(_subnet: str, _ports: str):
        return [
            {"ip": "10.0.1.20", "hostname": "VNK-KKM-501", "open_ports": [5405, 445]},
            {"ip": "10.0.1.21", "hostname": "POS-TERM", "open_ports": [5405]},
            {"ip": "10.0.1.22", "hostname": "VNK-KKM-2501", "open_ports": [445]},
        ]

    monkeypatch.setattr(scanner_routes, "smart_probe_network", _fake_probe)

    response = client.post(
        "/api/v1/scanner/smart-search/cash-registers",
        json={"hostname_contains": "KKM", "limit": 50},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    hostnames = {item["hostname"] for item in payload["data"]}
    assert hostnames == {"VNK-KKM-501", "VNK-KKM-2501"}
    assert payload["data"][0]["confidence"] == "high"

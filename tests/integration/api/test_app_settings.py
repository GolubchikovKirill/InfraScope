from app.core.config import settings


def test_app_settings_requires_auth(client):
    response = client.get("/api/v1/app-settings/general")
    assert response.status_code == 401


def test_app_settings_returns_defaults_for_authenticated_user(client, user_token: str):
    response = client.get(
        "/api/v1/app-settings/general",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scan_subnet"] == settings.SCAN_SUBNET
    assert body["scan_ports"] == settings.SCAN_PORTS
    assert body["dns_search_suffixes"] == settings.DNS_SEARCH_SUFFIXES


def test_app_settings_patch_requires_superuser(client, user_token: str):
    response = client.patch(
        "/api/v1/app-settings/general",
        json={"scan_subnet": "10.10.98.0/24"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


def test_app_settings_patch_persists_values(client, admin_token: str):
    patch = client.patch(
        "/api/v1/app-settings/general",
        json={
            "scan_subnet": "10.10.98.0/24,10.10.99.0/24",
            "scan_ports": "80,443,445",
            "dns_search_suffixes": "regstaer.local,corp.local",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch.status_code == 200
    assert patch.json()["scan_ports"] == "80,443,445"

    read = client.get(
        "/api/v1/app-settings/general",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert read.status_code == 200
    assert read.json() == patch.json()


def test_app_settings_patch_rejects_empty_values(client, admin_token: str):
    response = client.patch(
        "/api/v1/app-settings/general",
        json={"scan_ports": "   "},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422

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
    assert "scan_subnet" not in body and "scan_ports" not in body
    assert body["dns_search_suffixes"] == settings.DNS_SEARCH_SUFFIXES


def test_app_settings_patch_requires_superuser(client, user_token: str):
    response = client.patch(
        "/api/v1/app-settings/general",
        json={"dns_search_suffixes": "corp.local"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


def test_app_settings_patch_persists_values(client, admin_token: str):
    patch = client.patch(
        "/api/v1/app-settings/general",
        json={"dns_search_suffixes": "regstaer.local,corp.local"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch.status_code == 200
    assert patch.json()["dns_search_suffixes"] == "regstaer.local,corp.local"

    read = client.get(
        "/api/v1/app-settings/general",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert read.status_code == 200
    assert read.json() == patch.json()


def test_app_settings_patch_rejects_empty_values(client, admin_token: str):
    response = client.patch(
        "/api/v1/app-settings/general",
        json={"dns_search_suffixes": "   "},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Validation error"
    assert isinstance(body["errors"], list)
    assert body["errors"]

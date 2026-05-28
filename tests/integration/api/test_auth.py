import jwt
from fastapi.testclient import TestClient

from app.core.security import ALGORITHM


def test_login_success_returns_access_token(client: TestClient, admin_user):
    response = client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": "Pass1234"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_invalid_password_returns_400(client: TestClient, admin_user):
    response = client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": "wrong-pass"},
    )
    assert response.status_code == 400


def test_test_token_endpoint_requires_valid_token(client: TestClient, admin_token: str):
    response = client.post(
        "/api/v1/auth/test-token",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"


def test_refresh_token_cannot_be_used_as_bearer(client: TestClient, admin_user):
    login = client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": "Pass1234"},
    )
    assert login.status_code == 200
    refresh_token = client.cookies.get("refresh_token")
    assert refresh_token

    response = client.post(
        "/api/v1/auth/test-token",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert response.status_code == 401


def test_refresh_rotates_cookie_and_revokes_previous_token(client: TestClient, admin_user):
    login = client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": "Pass1234"},
    )
    assert login.status_code == 200
    old_refresh_token = client.cookies.get("refresh_token")
    assert old_refresh_token

    refreshed = client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh_token})
    assert refreshed.status_code == 200
    new_refresh_token = client.cookies.get("refresh_token")
    assert new_refresh_token
    assert new_refresh_token != old_refresh_token

    replay = client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh_token})
    assert replay.status_code == 401


def test_logout_revokes_access_and_refresh_tokens(client: TestClient, admin_user):
    login = client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": "Pass1234"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    refresh_token = client.cookies.get("refresh_token")
    assert refresh_token

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        cookies={"refresh_token": refresh_token},
    )
    assert logout.status_code == 200

    protected = client.post(
        "/api/v1/auth/test-token",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert protected.status_code == 401

    refresh = client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_token})
    assert refresh.status_code == 401


def test_access_token_payload_marks_access_type(client: TestClient, admin_token: str):
    payload = jwt.decode(admin_token, options={"verify_signature": False}, algorithms=[ALGORITHM])
    assert payload["type"] == "access"

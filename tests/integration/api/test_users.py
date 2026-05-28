from fastapi.testclient import TestClient


def test_admin_can_create_user(client: TestClient, admin_token: str):
    response = client.post(
        "/api/v1/users/",
        json={
            "email": "new.user@example.com",
            "password": "Pass1234",
            "full_name": "New User",
            "is_superuser": False,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "new.user@example.com"


def test_non_admin_cannot_list_users(client: TestClient, user_token: str):
    response = client.get(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403

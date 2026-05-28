from app.api.routes import boarding_pass as boarding_routes


def test_boarding_pass_requires_auth(client):
    response = client.post("/api/v1/boarding-pass/export", json={})
    assert response.status_code == 401


def test_boarding_pass_requires_superuser(client, user_token: str):
    response = client.post(
        "/api/v1/boarding-pass/export",
        json={"format": "aztec", "raw_data": "M1RAW"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


def test_boarding_pass_invalid_payload_returns_400(client, admin_token: str):
    response = client.post(
        "/api/v1/boarding-pass/export",
        json={"format": "aztec", "first_name": "Ivan"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "last_name is required"


def test_boarding_pass_returns_png(client, admin_token: str, monkeypatch):
    def _fake_generate(_payload):
        return type(
            "GeneratedFile",
            (),
            {
                "filename": "boarding_pass_aztec_2026-03-11.png",
                "content_type": "image/png",
                "content": b"\x89PNG\r\n\x1a\nfake",
            },
        )()

    monkeypatch.setattr(boarding_routes.boarding_pass_service, "generate_file", _fake_generate)

    response = client.post(
        "/api/v1/boarding-pass/export",
        json={"format": "aztec", "raw_data": "M1RAW"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["content-disposition"] == 'attachment; filename="boarding_pass_aztec_2026-03-11.png"'
    assert response.content == b"\x89PNG\r\n\x1a\nfake"

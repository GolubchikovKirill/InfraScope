from fastapi.testclient import TestClient

from app.domains.inventory.models import MediaPlayer
from app.domains.media_center.models import MediaClientHeartbeat
from app.domains.media_center.schemas import MediaClientHeartbeatPayload
from app.services.media_center import record_client_heartbeat


def _player(db_session) -> MediaPlayer:
    player = MediaPlayer(
        device_type="nettop",
        name="Nettop Hall",
        model="Nettop",
        ip_address="10.10.98.50",
        mac_address="aa:bb:cc:dd:ee:50",
    )
    db_session.add(player)
    db_session.commit()
    db_session.refresh(player)
    return player


def test_media_assignment_and_manifest(client: TestClient, admin_token: str, user_token: str, db_session):
    player = _player(db_session)
    payload = {
        "title": "Airport promo",
        "media_type": "stream",
        "source_url": "http://media.local/live/airport.m3u8",
        "playback_mode": "loop",
        "volume": 70,
    }

    saved = client.put(
        f"/api/v1/media-center/assignments/{player.id}",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1

    manifest = client.get(
        f"/api/v1/media-center/manifest/{player.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["enabled"] is True
    assert body["source_url"] == "http://media.local/live/airport.m3u8"
    assert body["revision"] == 1

    updated = client.patch(
        f"/api/v1/media-center/assignments/{player.id}",
        json={"volume": 40},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2


def test_media_manifest_without_assignment_disables_client(client: TestClient, user_token: str, db_session):
    player = _player(db_session)

    manifest = client.get(
        f"/api/v1/media-center/manifest/{player.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert manifest.status_code == 200
    body = manifest.json()
    assert body["enabled"] is False
    assert body["revision"] == 0
    assert body["source_url"] is None


def test_media_asset_upload_select_and_manifest(client: TestClient, admin_token: str, user_token: str, db_session, tmp_path, monkeypatch):
    from app.services import media_center as media_center_service

    monkeypatch.setattr(media_center_service.settings, "MEDIA_LIBRARY_DIR", str(tmp_path))
    player = _player(db_session)

    uploaded = client.post(
        "/api/v1/media-center/assets",
        files={"file": ("promo.mp4", b"fake mp4 bytes", "video/mp4")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert uploaded.status_code == 200
    asset = uploaded.json()
    assert asset["media_type"] == "video"
    assert asset["source_url"].startswith("/assets/")

    asset_list = client.get("/api/v1/media-center/assets", headers={"Authorization": f"Bearer {user_token}"})
    assert asset_list.status_code == 200
    assert asset_list.json()["data"][0]["id"] == asset["id"]

    saved = client.put(
        f"/api/v1/media-center/assignments/{player.id}",
        json={
            "title": asset["title"],
            "media_type": asset["media_type"],
            "source_url": asset["source_url"],
            "asset_id": asset["id"],
            "playback_mode": "loop",
            "volume": 80,
            "enabled": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert saved.status_code == 200
    assert saved.json()["asset_id"] == asset["id"]

    manifest = client.get(
        f"/api/v1/media-center/manifest/{player.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert manifest.status_code == 200
    assert manifest.json()["source_url"] == asset["source_url"]

    file_response = client.get(
        f"/api/v1/media-center/assets/{asset['id']}/file",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert file_response.status_code == 200
    assert file_response.content == b"fake mp4 bytes"


def test_media_asset_upload_rejects_non_media_file(client: TestClient, admin_token: str, tmp_path, monkeypatch):
    from app.services import media_center as media_center_service

    monkeypatch.setattr(media_center_service.settings, "MEDIA_LIBRARY_DIR", str(tmp_path))

    response = client.post(
        "/api/v1/media-center/assets",
        files={"file": ("notes.txt", b"not media", "text/plain")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400


def test_media_heartbeat_list_shows_real_agent_state(client: TestClient, user_token: str, db_session):
    player = _player(db_session)
    heartbeat = MediaClientHeartbeat(
        player_id=player.id,
        agent_version="0.2.0",
        hostname="hall-nettop-01",
        current_revision=4,
        player_state="error",
        error_message="mpv executable file not found",
    )
    db_session.add(heartbeat)
    db_session.commit()

    response = client.get("/api/v1/media-center/heartbeats", headers={"Authorization": f"Bearer {user_token}"})

    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows[0]["player_id"] == str(player.id)
    assert rows[0]["current_revision"] == 4
    assert rows[0]["player_state"] == "error"
    assert "mpv" in rows[0]["error_message"]


def test_media_heartbeat_upsert_updates_existing_agent_state(db_session):
    player = _player(db_session)

    first = record_client_heartbeat(
        db_session,
        player.id,
        MediaClientHeartbeatPayload(
            agent_version="0.2.0",
            hostname="hall-nettop-01",
            current_revision=1,
            player_state="playing",
        ),
    )
    second = record_client_heartbeat(
        db_session,
        player.id,
        MediaClientHeartbeatPayload(
            agent_version="0.2.0",
            hostname="hall-nettop-01",
            current_revision=2,
            player_state="error",
            error_message="player exited unexpectedly",
        ),
    )

    assert second.id == first.id
    assert second.current_revision == 2
    assert second.player_state == "error"
    assert second.error_message == "player exited unexpectedly"


def test_media_assignment_requires_existing_player(client: TestClient, admin_token: str):
    response = client.put(
        "/api/v1/media-center/assignments/00000000-0000-0000-0000-000000000001",
        json={"title": "Missing", "source_url": "http://media.local/a.mp4"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404

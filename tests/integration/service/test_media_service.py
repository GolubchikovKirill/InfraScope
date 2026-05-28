import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.domains.media_center.models import MediaAsset, MediaClientHeartbeat
from app.domains.media_center.schemas import MediaClientManifest
from app.media_service import main as media_service


def test_media_service_returns_client_manifest(monkeypatch):
    def _fake_manifest(_session, player_id):
        return MediaClientManifest(
            device_id=str(player_id),
            revision=3,
            enabled=True,
            title="Promo",
            media_type="video",
            source_url="http://media.local/promo.mp4",
            volume=55,
        )

    monkeypatch.setattr(media_service, "build_client_manifest", _fake_manifest)
    client = TestClient(media_service.app)
    response = client.get("/clients/00000000-0000-0000-0000-000000000001/manifest")

    assert response.status_code == 200
    assert response.json()["source_url"] == "http://media.local/promo.mp4"
    assert response.json()["volume"] == 55


def test_media_service_records_client_heartbeat(monkeypatch):
    player_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    def _fake_heartbeat(_session, received_player_id, payload):
        assert received_player_id == player_id
        assert payload.current_revision == 7
        assert payload.player_state == "error"
        assert "mpv" in payload.error_message
        now = datetime.now(UTC)
        return MediaClientHeartbeat(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            player_id=received_player_id,
            agent_version=payload.agent_version,
            hostname=payload.hostname,
            current_revision=payload.current_revision,
            player_state=payload.player_state,
            error_message=payload.error_message,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(media_service, "record_client_heartbeat", _fake_heartbeat)
    client = TestClient(media_service.app)
    response = client.post(
        f"/clients/{player_id}/heartbeat",
        json={
            "agent_version": "0.2.0",
            "hostname": "hall-nettop-01",
            "current_revision": 7,
            "player_state": "error",
            "error_message": "mpv executable file not found",
        },
    )

    assert response.status_code == 200
    assert response.json()["hostname"] == "hall-nettop-01"
    assert response.json()["player_state"] == "error"


def test_media_service_serves_uploaded_asset_file(monkeypatch, tmp_path):
    asset_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
    media_file = tmp_path / f"{asset_id}.mp3"
    media_file.write_bytes(b"audio bytes")

    def _fake_asset(_session, received_asset_id):
        assert received_asset_id == asset_id
        return MediaAsset(
            id=asset_id,
            title="Radio",
            media_type="audio",
            source_url=f"/assets/{asset_id}/file",
            original_filename="radio.mp3",
            stored_filename=media_file.name,
            content_type="audio/mpeg",
            file_size_bytes=11,
        )

    def _fake_path(_asset):
        return media_file

    monkeypatch.setattr(media_service, "get_asset_or_raise", _fake_asset)
    monkeypatch.setattr(media_service, "media_asset_path", _fake_path)
    client = TestClient(media_service.app)
    response = client.get(f"/assets/{asset_id}/file")

    assert response.status_code == 200
    assert response.content == b"audio bytes"
    assert response.headers["content-type"].startswith("audio/mpeg")

import uuid
from datetime import UTC, datetime

from app.models import MLModelRegistry, MLOfflineRiskPrediction, MLTonerPrediction


def test_get_ml_toner_predictions(client, user_token: str, db_session):
    row = MLTonerPrediction(
        printer_id=uuid.uuid4(),
        printer_name="A1",
        toner_color="black",
        toner_model="CF259A",
        current_level=18,
        days_to_replacement=8.2,
        confidence=0.8,
        model_version="toner-test",
    )
    db_session.add(row)
    db_session.commit()

    response = client.get(
        "/api/v1/ml/predictions/toner",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["toner_color"] == "black"


def test_get_ml_offline_risk_predictions(client, user_token: str, db_session):
    row = MLOfflineRiskPrediction(
        device_kind="printer",
        device_id=uuid.uuid4(),
        device_name="A1",
        address="10.10.10.10",
        risk_score=0.82,
        risk_level="high",
        confidence=0.7,
        model_version="offline-test",
    )
    db_session.add(row)
    db_session.commit()

    response = client.get(
        "/api/v1/ml/predictions/offline-risk?device_kind=printer",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["risk_level"] == "high"


def test_get_ml_models_status(client, user_token: str, db_session):
    row = MLModelRegistry(
        model_family="toner_forecast",
        version="toner-v1",
        status="active",
        train_rows=120,
        metric_primary=2.5,
        metric_secondary=1.1,
        trained_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.commit()

    response = client.get(
        "/api/v1/ml/models/status",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["data"][0]["model_family"] == "toner_forecast"

import uuid
from datetime import UTC, datetime, timedelta

from app.ml.pipeline import _risk_level, score_toner_predictions, train_toner_model
from app.models import MLFeatureSnapshot, Printer


def test_risk_level_thresholds():
    assert _risk_level(0.1) == "low"
    assert _risk_level(0.5) == "medium"
    assert _risk_level(0.9) == "high"


def test_train_and_score_toner_model(db_session):
    printer_id = uuid.uuid4()
    printer = Printer(
        id=printer_id,
        printer_type="laser",
        connection_type="ip",
        store_name="A1",
        model="HP",
        ip_address="10.10.10.10",
        snmp_community="public",
        toner_black=20,
        toner_black_name="CF259A",
    )
    db_session.add(printer)

    now = datetime.now(UTC)
    db_session.add(
        MLFeatureSnapshot(
            device_kind="printer",
            device_id=printer_id,
            device_name="A1",
            address="10.10.10.10",
            is_online=True,
            toner_color="black",
            toner_level=80,
            toner_model="CF259A",
            source="test",
            hour_of_day=10,
            day_of_week=1,
            captured_at=now - timedelta(days=6),
        )
    )
    db_session.add(
        MLFeatureSnapshot(
            device_kind="printer",
            device_id=printer_id,
            device_name="A1",
            address="10.10.10.10",
            is_online=True,
            toner_color="black",
            toner_level=50,
            toner_model="CF259A",
            source="test",
            hour_of_day=10,
            day_of_week=2,
            captured_at=now - timedelta(days=3),
        )
    )
    db_session.add(
        MLFeatureSnapshot(
            device_kind="printer",
            device_id=printer_id,
            device_name="A1",
            address="10.10.10.10",
            is_online=True,
            toner_color="black",
            toner_level=20,
            toner_model="CF259A",
            source="test",
            hour_of_day=10,
            day_of_week=3,
            captured_at=now,
        )
    )
    db_session.commit()

    model = train_toner_model(db_session, min_train_rows=1)
    db_session.commit()
    assert model.model_family == "toner_forecast"

    created = score_toner_predictions(db_session)
    db_session.commit()
    assert created >= 1

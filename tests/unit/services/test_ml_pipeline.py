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


def test_train_toner_model_ignores_snapshots_older_than_the_retention_window(db_session):
    """A snapshot pair entirely outside the retention window (see
    settings.ML_FEATURE_SNAPSHOT_RETENTION_DAYS) must not contribute a
    training sample - the query bound in train_toner_model exists so this
    can't quietly regress into loading the whole table again."""
    now = datetime.now(UTC)

    in_window = uuid.uuid4()
    db_session.add(
        Printer(
            id=in_window,
            printer_type="laser",
            connection_type="ip",
            store_name="In-window",
            model="HP",
            ip_address="10.10.10.20",
            snmp_community="public",
        )
    )
    for days_ago, level in ((5, 80), (2, 50)):
        db_session.add(
            MLFeatureSnapshot(
                device_kind="printer",
                device_id=in_window,
                device_name="In-window",
                address="10.10.10.20",
                is_online=True,
                toner_color="black",
                toner_level=level,
                toner_model="CF259A",
                source="test",
                captured_at=now - timedelta(days=days_ago),
            )
        )

    out_of_window = uuid.uuid4()
    db_session.add(
        Printer(
            id=out_of_window,
            printer_type="laser",
            connection_type="ip",
            store_name="Out-of-window",
            model="HP",
            ip_address="10.10.10.21",
            snmp_community="public",
        )
    )
    for days_ago, level in ((200, 90), (150, 60)):
        db_session.add(
            MLFeatureSnapshot(
                device_kind="printer",
                device_id=out_of_window,
                device_name="Out-of-window",
                address="10.10.10.21",
                is_online=True,
                toner_color="black",
                toner_level=level,
                toner_model="CF259A",
                source="test",
                captured_at=now - timedelta(days=days_ago),
            )
        )
    db_session.commit()

    model = train_toner_model(db_session, min_train_rows=1)

    # Only the in-window pair (one consecutive delta) should have counted -
    # if the time bound regressed, this would be 2.
    assert model.train_rows == 1

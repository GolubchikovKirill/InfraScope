import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.domains.ml.models import MLFeatureSnapshot, MLModelRegistry
from app.ml.retention import prune_feature_snapshots, prune_model_registry, run_retention_cycle


def _snapshot(*, captured_at: datetime, device_id=None) -> MLFeatureSnapshot:
    return MLFeatureSnapshot(
        device_kind="printer",
        device_id=device_id or uuid.uuid4(),
        device_name="A1",
        address="10.10.10.10",
        is_online=True,
        source="test",
        captured_at=captured_at,
    )


def _model(*, family: str, trained_at: datetime, status: str = "archived") -> MLModelRegistry:
    return MLModelRegistry(
        model_family=family,
        version=f"v-{trained_at.timestamp()}-{uuid.uuid4().hex[:6]}",
        status=status,
        trained_at=trained_at,
    )


def test_prune_feature_snapshots_deletes_only_rows_past_retention(db_session):
    now = datetime.now(UTC)
    old = _snapshot(captured_at=now - timedelta(days=120))
    recent = _snapshot(captured_at=now - timedelta(days=1))
    db_session.add(old)
    db_session.add(recent)
    db_session.commit()

    deleted = prune_feature_snapshots(db_session, retention_days=90, batch_size=1000)

    assert deleted == 1
    remaining = db_session.exec(select(MLFeatureSnapshot)).all()
    assert len(remaining) == 1
    assert remaining[0].id == recent.id


def test_prune_feature_snapshots_batches_across_multiple_passes(db_session):
    now = datetime.now(UTC)
    for _ in range(7):
        db_session.add(_snapshot(captured_at=now - timedelta(days=200)))
    db_session.commit()

    deleted = prune_feature_snapshots(db_session, retention_days=90, batch_size=3)

    assert deleted == 7
    assert db_session.exec(select(MLFeatureSnapshot)).all() == []


def test_prune_feature_snapshots_disabled_when_retention_days_not_positive(db_session):
    db_session.add(_snapshot(captured_at=datetime.now(UTC) - timedelta(days=400)))
    db_session.commit()

    deleted = prune_feature_snapshots(db_session, retention_days=0)

    assert deleted == 0
    assert len(db_session.exec(select(MLFeatureSnapshot)).all()) == 1


def test_prune_model_registry_keeps_most_recent_n_per_family(db_session):
    now = datetime.now(UTC)
    kept = [_model(family="toner_forecast", trained_at=now - timedelta(days=i)) for i in range(3)]
    stale = [_model(family="toner_forecast", trained_at=now - timedelta(days=10 + i)) for i in range(4)]
    for row in [*kept, *stale]:
        db_session.add(row)
    db_session.commit()

    deleted = prune_model_registry(db_session, keep_per_family=3)

    assert deleted == 4
    remaining_ids = {row.id for row in db_session.exec(select(MLModelRegistry)).all()}
    assert remaining_ids == {row.id for row in kept}


def test_prune_model_registry_never_deletes_the_active_row_even_if_stale(db_session):
    now = datetime.now(UTC)
    active = _model(family="offline_risk", trained_at=now - timedelta(days=400), status="active")
    recent = [_model(family="offline_risk", trained_at=now - timedelta(days=i)) for i in range(3)]
    for row in [active, *recent]:
        db_session.add(row)
    db_session.commit()

    deleted = prune_model_registry(db_session, keep_per_family=3)

    assert deleted == 0
    remaining_ids = {row.id for row in db_session.exec(select(MLModelRegistry)).all()}
    assert active.id in remaining_ids


def test_prune_model_registry_tracks_families_independently(db_session):
    now = datetime.now(UTC)
    for family in ("toner_forecast", "offline_risk"):
        for i in range(5):
            db_session.add(_model(family=family, trained_at=now - timedelta(days=i)))
    db_session.commit()

    deleted = prune_model_registry(db_session, keep_per_family=2)

    assert deleted == 6  # 3 stale per family
    remaining = db_session.exec(select(MLModelRegistry)).all()
    by_family: dict[str, int] = {}
    for row in remaining:
        by_family[row.model_family] = by_family.get(row.model_family, 0) + 1
    assert by_family == {"toner_forecast": 2, "offline_risk": 2}


def test_run_retention_cycle_reports_both_counts(db_session):
    now = datetime.now(UTC)
    db_session.add(_snapshot(captured_at=now - timedelta(days=200)))
    for i in range(3):
        db_session.add(_model(family="toner_forecast", trained_at=now - timedelta(days=i)))
    db_session.commit()

    result = run_retention_cycle(
        db_session,
        snapshot_retention_days=90,
        model_registry_keep_per_family=1,
    )

    assert result == {"feature_snapshots_deleted": 1, "model_registry_deleted": 2}

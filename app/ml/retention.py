"""Bounds the growth of the two ML tables that have no natural cap of their
own: MLFeatureSnapshot (one row per device per poll cycle, forever) and
MLModelRegistry (one row per training run, forever). Both grow without limit
because nothing else in the write path ever deletes from them - training and
scoring only ever read/insert (see app.ml.pipeline).

Run once a day by the tasks.ml_daily_cycle Celery task, right after that
day's training+scoring so both still see the full retained window before
older rows are trimmed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, delete, select

from app.domains.ml.models import MLFeatureSnapshot, MLModelRegistry
from app.observability.metrics import ml_retention_rows_deleted_total

logger = logging.getLogger(__name__)

_ACTIVE = "active"


def prune_feature_snapshots(session: Session, *, retention_days: int, batch_size: int = 5000) -> int:
    """Delete MLFeatureSnapshot rows older than retention_days, oldest first,
    in batches. A single unbounded DELETE would hold one long transaction
    (and its locks) against a table every ~15-minute poll cycle also writes
    to; batching keeps each transaction short and lets writers interleave.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    total_deleted = 0
    while True:
        batch_ids = session.exec(
            select(MLFeatureSnapshot.id).where(MLFeatureSnapshot.captured_at < cutoff).limit(batch_size)
        ).all()
        if not batch_ids:
            break
        session.exec(delete(MLFeatureSnapshot).where(MLFeatureSnapshot.id.in_(batch_ids)))  # type: ignore[attr-defined]
        session.commit()
        total_deleted += len(batch_ids)
        if len(batch_ids) < batch_size:
            break
    if total_deleted:
        ml_retention_rows_deleted_total.labels(table="mlfeaturesnapshot").inc(total_deleted)
        logger.info(
            "ML retention: deleted %d MLFeatureSnapshot rows older than %d days",
            total_deleted,
            retention_days,
        )
    return total_deleted


def prune_model_registry(session: Session, *, keep_per_family: int) -> int:
    """Keep only the most recent keep_per_family MLModelRegistry rows per
    model_family (by trained_at), plus that family's currently active row
    regardless of age - a family that hasn't retrained recently must not
    lose the model it still serves.
    """
    if keep_per_family <= 0:
        return 0
    families = session.exec(select(MLModelRegistry.model_family).distinct()).all()
    total_deleted = 0
    for family in families:
        rows = session.exec(
            select(MLModelRegistry)
            .where(MLModelRegistry.model_family == family)
            .order_by(col(MLModelRegistry.trained_at).desc())
        ).all()
        keep_ids = {row.id for row in rows[:keep_per_family]}
        keep_ids.update(row.id for row in rows if row.status == _ACTIVE)
        stale = [row for row in rows if row.id not in keep_ids]
        if not stale:
            continue
        for row in stale:
            session.delete(row)
        session.commit()
        total_deleted += len(stale)
    if total_deleted:
        ml_retention_rows_deleted_total.labels(table="mlmodelregistry").inc(total_deleted)
        logger.info("ML retention: deleted %d stale MLModelRegistry rows", total_deleted)
    return total_deleted


def run_retention_cycle(
    session: Session,
    *,
    snapshot_retention_days: int,
    model_registry_keep_per_family: int,
    batch_size: int = 5000,
) -> dict[str, int]:
    deleted_snapshots = prune_feature_snapshots(
        session, retention_days=snapshot_retention_days, batch_size=batch_size
    )
    deleted_models = prune_model_registry(session, keep_per_family=model_registry_keep_per_family)
    return {
        "feature_snapshots_deleted": deleted_snapshots,
        "model_registry_deleted": deleted_models,
    }

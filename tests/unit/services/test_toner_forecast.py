"""The toner forecast against series whose true consumption is known.

The end-to-end case reproduces how production records toner - a snapshot every
15 minutes, the level re-read once an hour in whole percent - which is what
made the previous pairwise model forecast "replace today" for every printer.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlmodel import select

from app.domains.inventory.models import Printer
from app.domains.ml.models import MLFeatureSnapshot, MLModelRegistry, MLTonerPrediction
from app.ml.pipeline import score_toner_predictions, train_toner_model
from app.ml.toner import (
    DailyReading,
    Segment,
    TonerRateModel,
    backtest,
    estimate_rate,
    load_daily_readings,
    split_segments,
)
from app.ml.toner.robust import theil_sen

DAY0 = date(2026, 9, 1)


def _daily(levels: list[int], model: str = "CF259A") -> list[DailyReading]:
    return [DailyReading(DAY0 + timedelta(days=i), lvl, lvl, model) for i, lvl in enumerate(levels)]


def _segment(rate: float, days: int, start: float = 100.0, model: str = "CF259A") -> Segment:
    return Segment(points=[(float(d), float(math.floor(start - rate * d))) for d in range(days + 1)], toner_model=model)


# -- series --------------------------------------------------------------------


def test_a_swap_starts_a_new_cartridge_and_the_swap_day_is_split() -> None:
    readings = [
        *_daily([30, 25, 20]),
        DailyReading(DAY0 + timedelta(days=3), 15, 98, "CF259A"),  # swap day: old low, new high
        DailyReading(DAY0 + timedelta(days=4), 96, 96, "CF259A"),
    ]

    old, new = split_segments(readings)

    assert old.ended_by_refill is True
    assert [lvl for _x, lvl in old.points] == [30, 25, 20, 15]
    assert new.ended_by_refill is False
    assert [lvl for _x, lvl in new.points] == [98, 96]


def test_small_wobbles_are_not_swaps() -> None:
    assert len(split_segments(_daily([50, 52, 49, 55, 47]))) == 1


# -- fitting -------------------------------------------------------------------


def test_theil_sen_shrugs_off_a_misread() -> None:
    points = [(float(d), 100.0 - 2 * d) for d in range(10)]
    points[5] = (5.0, 10.0)  # one wild reading

    fit = theil_sen(points)

    assert fit is not None
    assert fit.slope == pytest.approx(-2.0, abs=0.01)


@pytest.mark.parametrize("rate", [0.4, 1.0, 2.5, 6.0])
def test_the_rate_is_recovered_from_whole_percent_steps(rate: float) -> None:
    est = estimate_rate(_segment(rate, days=20))

    assert est is not None
    assert est.rate == pytest.approx(rate, rel=0.15)
    assert est.rate_low <= est.rate <= est.rate_high


def test_too_little_history_gives_no_rate() -> None:
    assert estimate_rate(_segment(1.0, days=1)) is None


# -- forecasting ---------------------------------------------------------------


def test_unknown_level_codes_get_no_forecast_rather_than_zero_days() -> None:
    model = TonerRateModel.fit([("black", _segment(1.0, 20))])

    assert model.forecast(color="black", toner_model="CF259A", level=-3, own=None) is None


def test_a_new_cartridge_leans_on_the_fleet_and_an_old_one_on_itself() -> None:
    fleet = TonerRateModel.fit([("black", _segment(1.0, 30)) for _ in range(5)])
    busy = _segment(4.0, days=20)

    fresh = fleet.forecast(color="black", toner_model="CF259A", level=60, own=None)
    seasoned = fleet.forecast(color="black", toner_model="CF259A", level=60, own=estimate_rate(busy))

    assert fresh is not None and fresh.basis == "cartridge_model"
    assert fresh.days == pytest.approx(60, rel=0.1)
    assert seasoned is not None and seasoned.basis == "printer"
    # Mostly the printer's own 4 %/day: far closer to 15 days than to 60
    assert 13 <= seasoned.days <= 22
    assert seasoned.days_low <= seasoned.days <= seasoned.days_high


def test_the_model_survives_a_round_trip_through_the_registry() -> None:
    model = TonerRateModel.fit([("cyan", _segment(0.8, 25, model="W2031A"))])

    restored = TonerRateModel.from_metadata(json.loads(json.dumps(model.to_metadata())))

    assert restored is not None
    assert restored.by_model.keys() == model.by_model.keys()
    assert TonerRateModel.from_metadata({"rates_by_key": {}}) is None  # the old format


# -- backtest ------------------------------------------------------------------


def test_the_backtest_scores_forecasts_against_how_cartridges_really_ended() -> None:
    labelled = []
    for rate in (0.8, 1.0, 1.5, 2.0, 3.0):
        printer = uuid.uuid4()
        finished = _segment(rate, days=int(90 / rate))
        finished.ended_by_refill = True
        labelled.append((printer, "black", finished))
        labelled.append((printer, "black", _segment(rate, days=5)))

    result = backtest(labelled)

    assert result.cases > 0
    assert result.mae_days is not None
    assert result.mae_days < 3.0
    assert set(result.by_horizon) <= {30, 14, 7}


# -- end to end ----------------------------------------------------------------


def _record_fleet(db_session, truths: dict[uuid.UUID, float], days: int = 30) -> None:
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    for i, (printer_id, daily) in enumerate(truths.items()):
        shown = 80
        for k in range(days * 96):  # a snapshot every 15 minutes
            t = start + timedelta(minutes=15 * k)
            if k % 4 == 0:  # toner re-read hourly, whole percent
                shown = math.floor(80 - daily * k / 96)
            db_session.add(
                MLFeatureSnapshot(
                    device_kind="printer",
                    device_id=printer_id,
                    device_name=f"P{i}",
                    is_online=True,
                    toner_color="black",
                    toner_level=shown,
                    toner_model="CF259A",
                    source="bulk_poll",
                    captured_at=t,
                )
            )
        db_session.add(
            Printer(
                id=printer_id,
                printer_type="laser",
                connection_type="ip",
                store_name=f"P{i}",
                model="HP",
                ip_address=f"10.9.0.{i + 1}",
                toner_black=shown,
                toner_black_name="CF259A",
            )
        )
    db_session.commit()


def test_forecasts_match_real_consumption_on_production_shaped_data(db_session) -> None:
    truths = {uuid.uuid4(): rate for rate in (0.5, 1.0, 2.0)}
    _record_fleet(db_session, truths)

    model = train_toner_model(db_session, min_train_rows=1)
    db_session.commit()
    assert model.status == "active"
    assert json.loads(model.metadata_json or "{}")["algorithm"]
    score_toner_predictions(db_session)
    db_session.commit()

    predictions = db_session.exec(select(MLTonerPrediction)).all()
    assert len(predictions) == 3
    for p in predictions:
        real = p.current_level / truths[p.printer_id]
        # The old model said under one day for all three; now within 30 %
        assert p.days_to_replacement == pytest.approx(real, rel=0.3), (truths[p.printer_id], p.days_to_replacement)
        assert p.basis == "printer"
        assert p.days_low <= p.days_to_replacement <= p.days_high


def test_offline_and_unknown_readings_stay_out_of_the_series(db_session) -> None:
    printer_id = uuid.uuid4()
    now = datetime.now(UTC)
    for days_ago, level, online in ((3, 60, True), (2, 55, False), (1, -3, True), (0, 50, True)):
        db_session.add(
            MLFeatureSnapshot(
                device_kind="printer",
                device_id=printer_id,
                is_online=online,
                toner_color="black",
                toner_level=level,
                captured_at=now - timedelta(days=days_ago),
            )
        )
    db_session.commit()

    series = load_daily_readings(db_session, now - timedelta(days=10))

    assert [r.low for r in series[(printer_id, "black")]] == [60, 50]


def test_an_old_format_active_model_publishes_nothing(db_session) -> None:
    db_session.add(
        MLModelRegistry(
            model_family="toner_forecast",
            version="toner-old",
            status="active",
            metadata_json=json.dumps({"rates_by_key": {"black:cf259a": 96.0}}),
        )
    )
    db_session.add(
        Printer(
            printer_type="laser",
            connection_type="ip",
            store_name="S",
            model="HP",
            ip_address="10.9.1.1",
            toner_black=40,
        )
    )
    db_session.commit()

    assert score_toner_predictions(db_session) == 0


def test_the_first_scoring_after_an_upgrade_retrains_instead_of_waiting_for_the_night(db_session) -> None:
    from app.ml.pipeline import run_scoring_cycle

    _record_fleet(db_session, {uuid.uuid4(): 1.0}, days=10)
    db_session.add(
        MLModelRegistry(
            model_family="toner_forecast",
            version="toner-old",
            status="active",
            metadata_json=json.dumps({"rates_by_key": {"black:cf259a": 96.0}}),
        )
    )
    db_session.commit()

    result = run_scoring_cycle(db_session)

    assert result["toner_predictions"] == 1

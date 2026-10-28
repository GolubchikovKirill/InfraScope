from __future__ import annotations

import uuid

import pytest

from app.domains.inventory.models import CartridgeStock
from app.domains.ml.models import MLTonerPrediction
from app.services.cartridge_demand import forecast_cartridge_demand, replacements_within


@pytest.mark.parametrize(
    ("days_left", "rate", "expected"),
    [
        (40, 1.0, 0),  # runs out after the horizon
        (10, 1.0, 1),  # one swap, the next cartridge lasts 100 days
        (5, 10.0, 3),  # day 5, then every 10 days: 5, 15, 25
        (0, None, 1),  # no rate known: at least the one already due
    ],
)
def test_replacements_within_the_horizon(days_left, rate, expected) -> None:
    assert replacements_within(days_left, rate, 30) == expected


def _prediction(model: str, days: float, rate: float, store: str) -> MLTonerPrediction:
    return MLTonerPrediction(
        printer_id=uuid.uuid4(),
        printer_name=store,
        toner_color="black",
        toner_model=model,
        current_level=int(days * rate),
        days_to_replacement=days,
        daily_rate=rate,
        model_version="t",
    )


def test_demand_is_summed_per_cartridge_and_set_against_stock(db_session) -> None:
    db_session.add(CartridgeStock(cartridge_name="CF259A", toner_color="black", quantity_on_hand=1, minimum_stock=1))
    db_session.add_all(
        [
            _prediction("CF259A", 3, 2.0, "Store A"),
            _prediction("cf259a ", 20, 1.0, "Store B"),  # same cartridge, other spelling
            _prediction("CF259A", 90, 0.5, "Store C"),  # not within 30 days
            _prediction("W2030A", 12, 1.0, "Store D"),  # not in the catalog
        ]
    )
    db_session.commit()

    demand = {d.cartridge_name: d for d in forecast_cartridge_demand(db_session, horizon_days=30)}

    cf = demand["CF259A"]
    assert cf.needed == 2
    assert cf.printers == {"Store A", "Store B", "Store C"}
    assert cf.next_due_days == 3
    assert cf.to_order == 2  # 2 needed + 1 minimum - 1 on hand
    unlisted = demand["W2030A"]
    assert unlisted.on_hand is None
    assert unlisted.to_order == 1


def test_the_endpoint_returns_the_forecast(client, user_token: str, db_session) -> None:
    db_session.add(_prediction("CF259A", 3, 2.0, "Store A"))
    db_session.commit()

    response = client.get(
        "/api/v1/printers/cartridges/forecast?horizon_days=14", headers={"Authorization": f"Bearer {user_token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["horizon_days"] == 14
    assert body["data"][0]["cartridge_name"] == "CF259A"
    assert body["data"][0]["to_order"] == 1

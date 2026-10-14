from dataclasses import replace
from datetime import timedelta

import pytest
from test_scenes import NOW

from custom_components.glance_clock.apps.orders import Order, OrderLedger


def order():
    return Order("example:1", 59978, "USD", NOW.isoformat(), "Example University")


def test_order_announcement_and_summary_are_concise():
    assert order().text == "$599.78 Example University"
    ledger = OrderLedger()
    assert ledger.summary(NOW) == "0 orders"
    ledger, inserted = ledger.with_order(order(), NOW)
    assert inserted and ledger.summary(NOW) == "1 order: $599.78"
    ledger, _ = ledger.with_order(replace(order(), id="2", amount_minor=0), NOW)
    assert ledger.summary(NOW) == "2 orders: $599.78"


def test_duplicate_and_conflict_after_reload():
    ledger, _ = OrderLedger().with_order(order(), NOW)
    loaded = OrderLedger.load(ledger.dump())
    _, inserted = loaded.with_order(order(), NOW)
    assert not inserted
    with pytest.raises(ValueError, match="different"):
        loaded.with_order(replace(order(), amount_minor=1), NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"amount_minor": -1},
        {"amount_minor": 1.2},
        {"amount_minor": True},
        {"currency": "XXX"},
        {"id": ""},
        {"id": "bad\nid"},
        {"display_name": "x" * 41},
        {"occurred_at": "2026-10-14T12:00:00"},
        {"occurred_at": (NOW - timedelta(days=8)).isoformat()},
        {"occurred_at": (NOW + timedelta(minutes=6)).isoformat()},
    ],
)
def test_invalid_payload_rejected_without_mutation(change):
    ledger = OrderLedger()
    with pytest.raises(ValueError):
        ledger.with_order(replace(order(), **change), NOW)
    assert ledger.summary(NOW) == "0 orders"


def test_local_day_boundaries_and_currencies_stay_separate():
    today = replace(order(), occurred_at="2026-10-15T03:59:00+00:00")
    tomorrow = replace(order(), id="2", occurred_at="2026-10-15T04:00:00+00:00")
    euro = replace(today, id="3", currency="EUR", amount_minor=1)
    ledger = OrderLedger([today, tomorrow, euro])
    assert ledger.summary(NOW) == "2 orders: EUR 0.01 / $599.78"
    assert ledger.summary(NOW + timedelta(days=1)) == "1 order: $599.78"


def test_new_insert_prunes_old_records_and_does_not_mutate_original():
    old = replace(order(), occurred_at=(NOW - timedelta(days=8)).isoformat())
    original = OrderLedger([old])
    result, inserted = original.with_order(order(), NOW)
    assert inserted and result.orders[old.id] == order()
    assert original.orders[old.id] == old

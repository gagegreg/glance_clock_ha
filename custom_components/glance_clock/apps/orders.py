"""BYB order ledger. This module exists only on the BYB branch."""

import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

PREFIX = {"USD": "$", "CAD": "CA$", "AUD": "A$", "EUR": "EUR ", "GBP": "GBP "}


def money(amount, currency):
    return f"{PREFIX[currency]}{amount // 100}.{amount % 100:02d}"


@dataclass(frozen=True)
class Order:
    id: str
    amount_minor: int
    currency: str
    occurred_at: str
    display_name: str = ""

    @property
    def date(self):
        return datetime.fromisoformat(self.occurred_at)

    @property
    def text(self):
        return (
            money(self.amount_minor, self.currency) + " " + self.display_name
        ).strip()

    def validate(self, now):
        if (
            not isinstance(self.id, str)
            or not 1 <= len(self.id.encode()) <= 128
            or not isinstance(self.display_name, str)
            or len(self.display_name) > 40
        ):
            raise ValueError("Invalid order ID or display name")
        if any(
            unicodedata.category(c).startswith("C") for c in self.id + self.display_name
        ):
            raise ValueError(
                "Order ID and display name cannot contain control characters"
            )
        if (
            type(self.amount_minor) is not int
            or not 0 <= self.amount_minor <= 10_000_000_000
            or self.currency not in PREFIX
        ):
            raise ValueError("Expected integer minor units and a supported currency")
        if self.date.tzinfo is None or not now - timedelta(
            days=7
        ) < self.date <= now + timedelta(minutes=5):
            raise ValueError(
                "Order date must include a timezone and be within the last seven days"
            )


class OrderLedger:
    def __init__(self, orders=()):
        self.orders = {o.id: o for o in orders}

    def with_order(self, order, now):
        """Return a staged ledger; never mutate before durable save succeeds."""
        order.validate(now)
        kept = [o for o in self.orders.values() if o.date > now - timedelta(days=7)]
        candidate = OrderLedger(kept)
        if old := candidate.orders.get(order.id):
            if old != order:
                raise ValueError("Order ID already exists with different data")
            return candidate, False
        if len(candidate.orders) >= 10000:
            raise ValueError("Order ledger is full")
        candidate.orders[order.id] = order
        return candidate, True

    def dump(self):
        return {"orders": [asdict(o) for o in self.orders.values()]}

    @classmethod
    def load(cls, data):
        return cls(Order(**row) for row in (data or {}).get("orders", []))

    def summary(self, now):
        orders = [
            o
            for o in self.orders.values()
            if o.date.astimezone(now.tzinfo).date() == now.date()
        ]
        if not orders:
            return "0 orders"
        totals = {}
        for order in orders:
            totals[order.currency] = totals.get(order.currency, 0) + order.amount_minor
        amounts = " / ".join(
            money(amount, currency) for currency, amount in sorted(totals.items())
        )
        return f"{len(orders)} {'order' if len(orders) == 1 else 'orders'}: {amounts}"

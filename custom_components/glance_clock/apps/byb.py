"""Authenticated HA actions for the isolated BYB order app.

No inbound public webhook or API-server changes. HA's standard service API
handles authentication; a private background forwarder may call record_order.
"""

import asyncio
import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import DOMAIN, SOUNDS
from .orders import PREFIX, Order, OrderLedger
from .services import ANNOUNCEMENT, COMMON, get_controller

_LOGGER = logging.getLogger(__name__)
RECORD = vol.Schema(
    {
        **COMMON,
        vol.Required("id"): cv.string,
        vol.Required("amount_minor"): int,
        vol.Required("currency"): vol.In(PREFIX),
        vol.Required("occurred_at"): cv.string,
        vol.Optional("display_name", default=""): cv.string,
    }
)
SUMMARY = vol.Schema(ANNOUNCEMENT)


class StoredOrders:
    def __init__(self, store):
        self.store = store
        self.ledger = None
        self.lock = asyncio.Lock()

    async def load(self):
        if self.ledger is None:
            self.ledger = OrderLedger.load(await self.store.async_load())

    async def record(self, order, now):
        async with self.lock:
            await self.load()
            candidate, inserted = self.ledger.with_order(order, now)
            if inserted:
                await self.store.async_save(candidate.dump())
                self.ledger = candidate
            return inserted

    async def summary(self, now):
        async with self.lock:
            await self.load()
            return self.ledger.summary(now)


def async_register_byb_services(hass):
    def destination(data):
        controller = get_controller(hass, data)
        entry_id, entry = next(
            (key, entry)
            for key, entry in hass.data[DOMAIN].items()
            if entry.get("apps") is controller
        )
        if "byb_orders" not in entry:
            entry["byb_orders"] = StoredOrders(
                Store(
                    hass,
                    1,
                    f"{DOMAIN}.byb_orders.{entry_id}",
                    private=True,
                    atomic_writes=True,
                )
            )
        return controller, entry["byb_orders"]

    async def record(call):
        controller, orders = destination(call.data)
        try:
            order = Order(
                **{key: value for key, value in call.data.items() if key != "entry_id"}
            )
            now = dt_util.utcnow()
            inserted = await orders.record(order, now)
        except (ValueError, TypeError, KeyError) as error:
            raise ServiceValidationError(
                "Invalid order data or conflicting order ID"
            ) from error
        if inserted and now - timedelta(minutes=5) <= order.date <= now:
            try:
                controller.announce(
                    text=order.text, effect="glow", colors=(2, 1), sound=6, duration=25
                )
            except ValueError:
                # Notifications are best-effort. The order is still counted once.
                _LOGGER.debug(
                    "Order counted; clock offline, busy, or scene too large for announcement"
                )

    async def summary(call):
        controller, orders = destination(call.data)
        text = await orders.summary(dt_util.now())
        try:
            controller.announce(
                text=text,
                effect="glow",
                colors=(2, 1),
                sound=SOUNDS[call.data["sound"]],
                duration=call.data["duration"],
            )
        except ValueError as error:
            raise ServiceValidationError("Order summary could not be queued") from error

    hass.services.async_register(DOMAIN, "record_order", record, schema=RECORD)
    hass.services.async_register(DOMAIN, "announce_orders", summary, schema=SUMMARY)


def async_unregister_byb_services(hass):
    hass.services.async_remove(DOMAIN, "record_order")
    hass.services.async_remove(DOMAIN, "announce_orders")

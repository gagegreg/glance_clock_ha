"""Narrow, bearer-authenticated BYB receiver; no general HA access token."""

import asyncio
import hmac
import json
import logging
from pathlib import Path

import voluptuous as vol
from aiohttp import web
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from .byb import RECORD
from .orders import Order

_LOGGER = logging.getLogger(__name__)
KEY = "glance_clock_byb_receiver"
TOKEN_FILE = ".storage/glance_clock.orders_token"
MAX_BODY = 4096


class OrderReceiver(HomeAssistantView):
    url = "/api/glance_clock/orders"
    name = "api:glance_clock:orders"
    # Authentication is deliberately limited to this one endpoint.
    requires_auth = False

    def __init__(self, hass, token):
        self.hass = hass
        self.token = token.encode()
        self.slots = asyncio.Semaphore(4)

    def authenticated(self, request):
        header = request.headers.get("Authorization", "")
        return hmac.compare_digest(header.encode(), b"Bearer " + self.token)

    async def get(self, request):
        if not self.authenticated(request):
            return web.json_response({"accepted": False}, status=401)
        ready = self.hass.services.has_service("glance_clock", "record_order")
        return web.json_response({"ready": ready}, status=200 if ready else 503)

    async def post(self, request):
        if not self.authenticated(request):
            return web.json_response({"accepted": False}, status=401)
        if self.slots.locked():
            return web.json_response({"accepted": False}, status=503)
        async with self.slots:
            try:
                async with asyncio.timeout(5):
                    body = bytearray()
                    async for chunk in request.content.iter_chunked(MAX_BODY + 1):
                        body.extend(chunk)
                        if len(body) > MAX_BODY:
                            return web.json_response({"accepted": False}, status=413)
                data = RECORD(json.loads(body))
                Order(**{k: v for k, v in data.items() if k != "entry_id"}).validate(
                    dt_util.utcnow()
                )
            except (ValueError, TypeError, KeyError, vol.Invalid):
                return web.json_response({"accepted": False}, status=400)
            except TimeoutError:
                return web.json_response({"accepted": False}, status=408)
            try:
                async with asyncio.timeout(15):
                    await self.hass.services.async_call(
                        "glance_clock", "record_order", data, blocking=True
                    )
            except ServiceValidationError:
                return web.json_response({"accepted": False}, status=400)
            except (HomeAssistantError, OSError, TimeoutError):
                # No payloads, names, credentials or exception strings in logs.
                _LOGGER.warning("BYB receiver could not persist order; sender may retry")
                return web.json_response({"accepted": False}, status=503)
            # record_order returns only after durable save (or a known duplicate).
            return web.json_response({"accepted": True})


async def async_setup_receiver(hass):
    if KEY in hass.data:
        return
    path = Path(hass.config.path(TOKEN_FILE))

    def read_token():
        try:
            return path.read_text().strip()
        except FileNotFoundError:
            return ""

    token = await hass.async_add_executor_job(read_token)
    if len(token) < 32:
        _LOGGER.info("BYB private receiver disabled: no configured token")
        return
    hass.http.register_view(OrderReceiver(hass, token))
    hass.data[KEY] = True

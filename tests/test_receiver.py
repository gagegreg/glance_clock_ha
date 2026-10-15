"""Exercise the actual HTTP receiver and durable order action together."""
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

pytest.importorskip("homeassistant.core")
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from test_ha_services import setup
from test_orders import order
from test_scenes import NOW

from custom_components.glance_clock.apps import byb
from custom_components.glance_clock.apps.receiver import OrderReceiver

TOKEN = "test-secret-" * 4
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest_asyncio.fixture
async def receiver(tmp_path, monkeypatch):
    store = AsyncMock()
    store.async_load.return_value = None
    monkeypatch.setattr(byb, "Store", lambda *args, **kwargs: store)
    monkeypatch.setattr(byb.dt_util, "utcnow", lambda: NOW)
    hass, apps = setup(tmp_path)
    hass.services.has_service = lambda *args: True
    byb.async_register_byb_services(hass)
    view = OrderReceiver(hass, TOKEN)
    app = web.Application()
    app.router.add_post(view.url, view.post)
    app.router.add_get(view.url, view.get)
    async with TestClient(TestServer(app)) as client:
        yield client, view, store, apps


@pytest.mark.asyncio
async def test_auth_and_health_do_not_insert_orders(receiver):
    client, view, store, _ = receiver
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = await client.post(view.url, json=asdict(order()), headers=headers)
        assert response.status == 401
    response = await client.get(view.url, headers=AUTH)
    assert response.status == 200
    assert await response.json() == {"ready": True}
    store.async_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_acknowledges_durable_order_and_retry_once(receiver):
    client, view, store, apps = receiver
    for _ in range(2):
        response = await client.post(view.url, json=asdict(order()), headers=AUTH)
        assert response.status == 200
        assert await response.json() == {"accepted": True}
        store.async_save.assert_awaited_once()
    apps.announce.assert_called_once()


@pytest.mark.asyncio
async def test_disk_failure_retries_and_offline_clock_still_counts(receiver):
    client, view, store, apps = receiver
    store.async_save.side_effect = OSError("disk")
    response = await client.post(view.url, json=asdict(order()), headers=AUTH)
    assert response.status == 503
    apps.announce.assert_not_called()
    store.async_save.side_effect = None
    apps.announce.side_effect = ValueError("offline")
    response = await client.post(view.url, json=asdict(order()), headers=AUTH)
    assert response.status == 200
    assert await response.json() == {"accepted": True}


@pytest.mark.asyncio
async def test_bad_and_oversized_payloads_do_not_persist(receiver):
    client, view, store, _ = receiver
    for payload in ({}, [], {**asdict(order()), "amount_minor": True},
                    {**asdict(order()), "extra": "not allowed"}):
        response = await client.post(view.url, json=payload, headers=AUTH)
        assert response.status == 400
    response = await client.post(view.url, data=b"x" * 4097, headers=AUTH)
    assert response.status == 413
    store.async_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_busy_receiver_returns_retryable_response(receiver):
    client, view, store, _ = receiver
    for _ in range(4):
        await view.slots.acquire()
    response = await client.post(view.url, json=asdict(order()), headers=AUTH)
    assert response.status == 503
    store.async_save.assert_not_awaited()

import asyncio
from unittest.mock import AsyncMock

import pytest
from test_orders import order
from test_scenes import NOW

pytest.importorskip("homeassistant.core")
from custom_components.glance_clock.apps.byb import StoredOrders


@pytest.mark.asyncio
async def test_concurrent_retry_is_counted_once():
    store = AsyncMock()
    store.async_load.return_value = None
    orders = StoredOrders(store)
    results = await asyncio.gather(
        orders.record(order(), NOW), orders.record(order(), NOW)
    )
    assert sorted(results) == [False, True]
    assert store.async_save.call_count == 1
    assert await orders.summary(NOW) == "1 order: $599.78"


@pytest.mark.asyncio
async def test_disk_failure_does_not_commit_and_can_retry():
    store = AsyncMock()
    store.async_load.return_value = None
    store.async_save.side_effect = OSError("disk unavailable")
    orders = StoredOrders(store)
    with pytest.raises(OSError):
        await orders.record(order(), NOW)
    assert await orders.summary(NOW) == "0 orders"
    store.async_save.side_effect = None
    assert await orders.record(order(), NOW)


@pytest.mark.asyncio
async def test_order_action_uses_byb_colors_and_does_not_repeat_after_retry(
    tmp_path, monkeypatch
):
    from dataclasses import asdict

    from test_ha_services import setup

    from custom_components.glance_clock.apps import byb

    store = AsyncMock()
    store.async_load.return_value = None
    monkeypatch.setattr(byb, "Store", lambda *args, **kwargs: store)
    monkeypatch.setattr(byb.dt_util, "utcnow", lambda: NOW)
    hass, apps = setup(tmp_path)
    byb.async_register_byb_services(hass)
    for _ in range(2):
        await hass.services.async_call(
            "glance_clock", "record_order", asdict(order()), blocking=True
        )
    apps.announce.assert_called_once_with(
        text="$599.78 Example University",
        effect="glow",
        colors=(2, 1),
        sound=6,
        duration=25,
    )
    store.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_offline_notification_does_not_fail_order_recording(
    tmp_path, monkeypatch
):
    from dataclasses import asdict

    from test_ha_services import setup

    from custom_components.glance_clock.apps import byb

    store = AsyncMock()
    store.async_load.return_value = None
    monkeypatch.setattr(byb, "Store", lambda *args, **kwargs: store)
    monkeypatch.setattr(byb.dt_util, "utcnow", lambda: NOW)
    hass, apps = setup(tmp_path)
    apps.announce.side_effect = ValueError("offline")
    byb.async_register_byb_services(hass)
    await hass.services.async_call(
        "glance_clock", "record_order", asdict(order()), blocking=True
    )
    assert (
        await hass.data["glance_clock"]["one"]["byb_orders"].summary(NOW)
        == "1 order: $599.78"
    )

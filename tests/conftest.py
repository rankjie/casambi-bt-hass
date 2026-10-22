"""Isolated HA runtime fixtures; no live account or credential cache is used."""

import pytest

from custom_components.casambi_bt import http, websocket_api
from custom_components.casambi_bt.network_events import (
    DATA_NETWORK_EVENTS,
    NetworkEventsManager,
)
from homeassistant.setup import async_setup_component


@pytest.fixture
async def event_manager(hass, tmp_path):
    """Provide the real archive and HA WebSocket handlers with synthetic networks."""
    assert await async_setup_component(hass, "websocket_api", {})
    manager = NetworkEventsManager(tmp_path / "events.sqlite3")
    await manager.start()
    await manager.attach("network-a", "Test network", "11:22:33:44:55:66")
    await manager.attach("network-b", "Other network", "22:33:44:55:66:77")
    hass.data[DATA_NETWORK_EVENTS] = manager
    websocket_api.async_register(hass)
    http.async_register(hass)
    yield manager
    await manager.close()

"""Observed battery and thermal fields as real HA sensor entities."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from CasambiBt import NetworkEventDecoder
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.casambi_bt import CasambiApi
from custom_components.casambi_bt.diagnostic_sensor import battery_percentage
from custom_components.casambi_bt.network_events import DATA_NETWORK_EVENTS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, None),
        (1, 1),
        (50, 50),
        (100, 100),
        (101, 1),
        (168, 1),
        (169, 1),
        (172, 12),
        (176, 24),
        (179, 35),
        (183, 46),
        (186, 57),
        (189, 68),
        (193, 79),
        (196, 88),
        (200, 96),
        (201, 96),
        (202, 100),
        (203, 100),
        (214, 100),
        (255, 100),
    ],
)
def test_official_battery_percentage(raw, expected):
    """Protect direct percentages, the encoded curve, rounding and unknown zero."""
    assert battery_percentage(raw) == expected


def make_unit(unit_id, controls, *, online=True):
    """Build only the public device metadata used by these entities."""
    return SimpleNamespace(
        deviceId=unit_id,
        uuid=f"synthetic-unit-{unit_id}",
        name=f"Device {unit_id}",
        firmwareVersion="42",
        online=online,
        state=None,
        unitType=SimpleNamespace(
            id=42,
            manufacturer="Casambi",
            model="Synthetic",
            eventProfile={"controls": controls},
        ),
    )


def control(kind, offset=0, length=8):
    """Describe a fixture field, including its actual position in the state."""
    return {"type": kind, "offset": offset, "length": length}


@pytest.mark.asyncio
async def test_diagnostics_initial_live_partial_states_and_unload(
    hass, enable_custom_integrations, event_manager, caplog, tmp_path
):
    """Keep initial readings, unknown fields, enum meanings and sleeping batteries."""
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain="casambi_bt", title="Synthetic", data={})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    api = CasambiApi(hass, entry, "11:22:33:44:55:66", "synthetic")
    battery = make_unit(30, [control("battery")], online=False)
    thermal = make_unit(2, [control("dimmer"), control("overheat", 8, 2)])
    other = make_unit(31, [control("battery"), control("battery", 8)])
    api.casa = Mock(
        units=[battery, thermal, other],
        networkId="synthetic-network",
        networkName="Synthetic",
        connected=True,
    )
    api.network_device_id = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("casambi_bt", "synthetic-network")},
            name="Synthetic",
        )
        .id
    )
    hass.data["casambi_bt"] = {entry.entry_id: api}
    hass.config.components.add("casambi_bt")
    assert hass.data[DATA_NETWORK_EVENTS] is event_manager
    await event_manager.attach(entry.entry_id, "Synthetic", api.address)
    event_manager.start_session(entry.entry_id, api.address)
    decoder = NetworkEventDecoder()

    def report(unit, state):
        for event in decoder.decode(unit, state):
            api._network_event_handler(event)  # noqa: SLF001
        api._unit_changed_handler(unit)  # noqa: SLF001

    # Reports can arrive during GATT setup, before the sensor platform is loaded.
    report(battery, b"\xd6")
    report(thermal, b"\xff")  # The thermal field has not been received.
    report(other, b"\x32")
    assert await async_setup_component(hass, "sensor", {})
    with (
        patch("custom_components.casambi_bt.sensor.async_setup_environment_sensors"),
        patch("custom_components.casambi_bt.sensor.async_setup_network_sensors"),
        patch("custom_components.casambi_bt.sensor.async_setup_switch_config_sensors"),
        patch("custom_components.casambi_bt.sensor.async_setup_switch_sensors"),
        patch(
            "custom_components.casambi_bt.lamel_controls.async_setup_entry_sensor_lamel"
        ),
    ):
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
        await hass.async_block_till_done()
    registry = er.async_get(hass)

    def entity(unit, kind, index):
        unique = f"synthetic-network-unit-{unit.uuid}-diagnostic-{kind}-{index}"
        entity_id = registry.async_get_entity_id("sensor", "casambi_bt", unique)
        assert entity_id is not None
        return hass.states.get(entity_id)

    first = entity(battery, "battery", 0)
    assert first.state == "100"
    assert first.attributes["unit_of_measurement"] == "%"
    assert first.attributes["device_class"] == "battery"
    assert first.attributes["state_class"] == "measurement"
    assert first.attributes["raw_value"] == 214
    assert registry.async_get(first.entity_id).entity_category == "diagnostic"
    device = dr.async_get(hass).async_get_device_by_identifier(
        ("casambi_bt", battery.uuid), entry.entry_id
    )
    assert registry.async_get(first.entity_id).device_id == device.id
    assert device.via_device_id == api.network_device_id
    assert entity(thermal, "overheat", 1).state == "unknown"
    assert entity(other, "battery", 0).state == "50"
    assert entity(other, "battery", 1).state == "unknown"

    for raw, expected in (
        (0, "normal"),
        (1, "was_overheated"),
        (2, "overheated"),
        (3, "unknown"),
        (0, "normal"),
    ):
        report(thermal, bytes((255, raw)))
        await hass.async_block_till_done()
        state = entity(thermal, "overheat", 1)
        assert state.state == expected
        assert state.attributes["device_class"] == "enum"
        assert state.attributes["options"] == ["normal", "was_overheated", "overheated"]
        assert state.attributes["raw_value"] == raw
        assert state.attributes.get("state_class") is None
    assert "Unrecognized thermal status 3" in caplog.text
    report(thermal, b"\x80")  # A later partial report cannot erase the thermal value.
    report(battery, b"\xba")
    report(other, b"\x32\x64")
    await hass.async_block_till_done()
    assert entity(thermal, "overheat", 1).state == "normal"
    assert entity(battery, "battery", 0).state == "57"
    assert entity(other, "battery", 0).state == "50"
    assert entity(other, "battery", 1).state == "100"
    report(battery, b"\x00")
    await hass.async_block_till_done()
    assert entity(battery, "battery", 0).state == "unknown"
    assert entity(battery, "battery", 0).attributes["raw_value"] == 0
    api.casa.connect.assert_not_called()
    assert await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
    assert all(not callbacks for callbacks in api._callback_map.values())  # noqa: SLF001

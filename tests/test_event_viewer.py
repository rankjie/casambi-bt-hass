"""Observable archive and real HA transport behavior with synthetic observations."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from bleak.backends.device import BLEDevice
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.casambi_bt import frontend
from custom_components.casambi_bt.event_store import EventStore
from custom_components.casambi_bt.network_events import (
    DATA_NETWORK_EVENTS,
    QUEUE_CAPACITY,
    NetworkEventsManager,
    project_event,
)
from custom_components.casambi_bt.websocket_api import validate_cursor
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.setup import async_setup_component

pytestmark = pytest.mark.asyncio


def observation(number=1, *, unit=30, stream="button_event"):
    """Build a known parsed input contract without raw packets or credentials."""
    row = {
        "time": 1_700_000_000_000 + number,
        "timestamp": "2026-10-22T12:00:00+02:00",
        "unit": unit,
        "name": f"Switch {unit}",
        "type": "input",
        "value": f"input {number}",
        "source": "invocation",
        "source_stream": stream,
    }
    if stream == "button_event":
        row.update(button_event_index=1, pressed=True)
    else:
        row.update(input_index=1, input_code=2, input_value16=None)
    return row


async def receive(client, predicate):
    """Read past status messages while keeping every wait finite."""
    async with asyncio.timeout(4):
        while True:
            message = await client.receive_json()
            if predicate(message):
                return message


async def result(client, identifier):
    """Read the response to an explicit WebSocket command ID."""
    return await receive(
        client, lambda msg: msg["type"] == "result" and msg["id"] == identifier
    )


async def page(client, identifier):
    """Wait for an archive page belonging to one subscription."""
    return (
        await receive(
            client,
            lambda msg: (
                msg["type"] == "event"
                and msg["id"] == identifier
                and msg["event"]["kind"] == "events"
            ),
        )
    )["event"]


async def subscribe(client, manager, identifier=1, **options):
    """Subscribe using the actual HA command schema."""
    await client.send_json(
        {
            "id": identifier,
            "type": "casambi_bt/events/subscribe",
            "entry_id": "network-a",
            "generation": 1,
            "store_id": manager.store.store_id,
            **options,
        }
    )
    assert (await result(client, identifier))["success"]


async def ack(client, payload, identifier):
    """Acknowledge only the page actually processed by this client."""
    await client.send_json(
        {
            "id": identifier,
            "type": "casambi_bt/events/ack",
            "subscription": payload["subscription_id"],
            "generation": payload["subscription_generation"],
            "sequence": payload["scanned_to_sequence"],
        }
    )
    assert (await result(client, identifier))["success"]


async def test_projection_preserves_button_identity_and_excludes_unparsed_buffers():
    """Physical display aliases retain their provenance and the authoritative index."""
    for index, expected in ((0, 4), (1, 1), (2, 2), (3, 3), (4, None), (7, None)):
        original = {
            **observation(),
            "button_event_index": index,
            "state_hex": "unparsed-synthetic",
            "raw_packet": "unparsed-synthetic",
            "decrypted_data": "unparsed-synthetic",
            "password": "synthetic-secret",
        }
        row = project_event(original)
        assert (row["unit_id"], row["button"], row["button_index"]) == (
            30,
            expected,
            index,
        )
        assert "synthetic-secret" not in json.dumps(row)
        assert "unparsed-synthetic" not in json.dumps(row)
    row = project_event(observation(stream="notify_input"))
    assert row["input_action"] == "release"
    assert row["input_value16"] is None


async def test_archive_search_export_range_and_restart_have_no_live_window_limit(
    tmp_path,
):
    """Old records stay queryable after 10,000 observations and a clean restart."""
    path = tmp_path / "archive.sqlite3"
    store = EventStore(path)
    await store.open(1)
    await store.register_network("a", "Test", "11:22:33:44:55:66")
    records = [
        {
            "kind": "event",
            "entry_id": "a",
            "connection_id": "session-one",
            "time": index,
            "data": project_event(
                {
                    **observation(index, unit=index % 3),
                    "value": "earliest needle" if index == 1 else f"value {index}",
                }
            ),
        }
        for index in range(1, 10_101)
    ]
    await store.append(records)
    identity = store.store_id
    first = await store.query("a", {"query": "earliest needle"}, upper=10_100)
    assert [row["sequence"] for row in first["events"]] == [1]
    assert not (await store.query("a", {"query": "' OR 1=1 --"}, upper=10_100))[
        "events"
    ]
    await store.close(2)
    store = EventStore(path)
    await store.open(3)
    assert store.store_id == identity
    assert (await store.networks())[0]["saved"] == 10_100
    cursor = count = 0
    while True:
        current = await store.query("a", {}, upper=10_100, after=cursor)
        count += len(current["events"])
        cursor = current["scanned_to_sequence"]
        if not current["has_more"]:
            break
    assert (count, cursor) == (10_100, 10_100)
    assert not await store.gaps("a")
    await store.close(4)


async def test_unclean_restart_and_projection_failure_are_explicit(
    tmp_path, event_manager
):
    """A failed capture interval must not masquerade as complete history."""
    path = tmp_path / "interrupted.sqlite3"
    store = EventStore(path)
    await store.open(100)
    await store.close(200, clean=False)
    store = EventStore(path)
    await store.open(300)
    assert (await store.gaps("network-a"))[0]["reason"] == "unclean_shutdown"
    await store.close(400)
    event_manager.event("network-a", {**observation(), "time": "bad time"})
    assert event_manager.status("network-a")["storage"] == "failed"
    await event_manager.flush()
    assert (await event_manager.store.gaps("network-a"))[0][
        "reason"
    ] == "projection_TypeError"
    assert event_manager.status("network-a")["saved"] == 0


async def test_writer_failure_is_visible_without_changing_ble_state(event_manager):
    """An archive fault must not reset lighting control or claim records were saved."""
    event_manager.set_state("network-a", "connected")
    with patch.object(
        event_manager.store,
        "append",
        new=AsyncMock(side_effect=sqlite3.DatabaseError("synthetic database failure")),
    ):
        event_manager.event("network-a", observation())
        with pytest.raises(sqlite3.DatabaseError):
            await event_manager.flush()
    status = event_manager.status("network-a")
    assert status["storage"] == "failed"
    assert status["state"] == "connected"
    assert status["saved"] == 0


async def test_unavailable_archive_keeps_control_lifecycle_and_reports_unknown_count(
    hass, tmp_path
):
    """A startup storage fault must not prevent the existing BLE owner from loading."""
    manager = NetworkEventsManager(tmp_path / "unavailable.sqlite3")
    with patch.object(manager.store, "open", side_effect=PermissionError("synthetic")):
        await manager.start()
    await manager.attach("network-a", "Test", "11:22:33:44:55:66")
    manager.start_session("network-a", "AA:BB:CC:DD:EE:FF")
    manager.set_state("network-a", "connected")
    manager.event("network-a", observation())
    status = manager.status("network-a")
    assert status["state"] == "connected"
    assert status["storage"] == "failed"
    assert status["saved"] is None
    assert status["has_gaps"]
    assert status["capture_dropped"] == 2
    with pytest.raises(HomeAssistantError, match="archive_unavailable"):
        validate_cursor(manager, None)
    await manager.close()


async def test_ingress_overflow_records_a_gap_and_recovers(event_manager):
    """Bounded capture overload preserves accepted rows and makes losses explicit."""
    manager = event_manager
    for number in range(QUEUE_CAPACITY + 3):
        manager.event("network-a", observation(number))
    assert manager.status("network-a")["capture_dropped"] == 3
    assert manager.status("network-a")["storage"] == "failed"
    await manager.flush()
    status = manager.status("network-a")
    assert status["saved"] == QUEUE_CAPACITY
    assert status["storage"] == "ready"
    assert status["has_gaps"]
    gaps = await manager.store.gaps("network-a")
    assert [(gap["reason"], gap["count"]) for gap in gaps] == [("ingress_overflow", 3)]
    manager.event("network-a", observation(QUEUE_CAPACITY + 4))
    await manager.flush()
    assert manager.status("network-a")["saved"] == QUEUE_CAPACITY + 1


async def test_snapshot_commit_race_resume_and_duplicate_protocol_reports(
    event_manager, hass_ws_client
):
    """A commit during snapshot delivery replays once, with raw reports preserved."""
    manager = event_manager
    manager.event("network-a", observation())
    await manager.flush()
    client = await hass_ws_client()
    await subscribe(client, manager)
    initial = await page(client, 1)
    assert [row["sequence"] for row in initial["events"]] == [1]
    manager.event("network-a", observation(2))
    manager.event("network-a", observation(2))
    await manager.flush()
    await ack(client, initial, 2)
    live = await page(client, 1)
    assert [row["sequence"] for row in live["events"]] == [2, 3]
    await ack(client, live, 3)
    await client.close()
    await asyncio.sleep(0)
    manager.event("network-a", observation(4, stream="notify_input"))
    await manager.flush()
    client = await hass_ws_client()
    await subscribe(client, manager, after_sequence=3)
    replay = await page(client, 1)
    assert [row["sequence"] for row in replay["events"]] == [4]
    assert replay["events"][0]["source_stream"] == "notify_input"
    await ack(client, replay, 2)
    await client.close()


async def test_filtered_stream_advances_across_nonmatching_records(
    event_manager, hass_ws_client
):
    """A quiet filter advances its durable cursor instead of replaying a stale range."""
    manager = event_manager
    client = await hass_ws_client()
    await subscribe(client, manager, filters={"unit": 99}, after_sequence=0)
    manager.event("network-a", observation())
    manager.event("network-b", observation(2, unit=99))
    await manager.flush()
    unseen = await page(client, 1)
    assert unseen["events"] == []
    assert unseen["scanned_to_sequence"] == 2
    await ack(client, unseen, 2)
    manager.event("network-a", observation(3, unit=99))
    await manager.flush()
    matched = await page(client, 1)
    assert [row["sequence"] for row in matched["events"]] == [3]
    await ack(client, matched, 3)
    await client.close()


async def test_one_page_in_flight_and_ack_cannot_skip_or_cross_clients(
    event_manager, hass_ws_client
):
    """A slow client cannot queue the whole archive or advance another viewer."""
    manager = event_manager
    for number in range(600):
        manager.event("network-a", observation(number))
    await manager.flush()
    first = await hass_ws_client()
    second = await hass_ws_client()
    await subscribe(first, manager, after_sequence=0)
    pending = await page(first, 1)
    assert len(pending["events"]) == 250
    await second.send_json(
        {
            "id": 1,
            "type": "casambi_bt/events/ack",
            "subscription": 1,
            "generation": 1,
            "sequence": 250,
        }
    )
    assert not (await result(second, 1))["success"]
    await first.send_json(
        {
            "id": 2,
            "type": "casambi_bt/events/ack",
            "subscription": 1,
            "generation": 1,
            "sequence": 600,
        }
    )
    assert not (await result(first, 2))["success"]
    await ack(first, pending, 3)
    next_page = await page(first, 1)
    assert next_page["events"][0]["sequence"] == 251
    assert len(next_page["events"]) == 250
    await first.close()
    await second.close()
    await asyncio.sleep(0.05)
    assert not manager.streams


async def test_ack_timeout_releases_stream_and_allows_cursor_replay(
    event_manager, hass_ws_client
):
    """A stalled viewer has a finite lifetime without losing its saved observations."""
    manager = event_manager
    manager.event("network-a", observation())
    await manager.flush()
    client = await hass_ws_client()
    with patch("custom_components.casambi_bt.websocket_api.ACK_TIMEOUT", 0.02):
        await subscribe(client, manager, after_sequence=0)
        assert (await page(client, 1))["events"][0]["sequence"] == 1
        failure = await receive(
            client,
            lambda msg: msg["type"] == "event" and msg["event"]["kind"] == "error",
        )
        assert failure["event"]["code"] == "ack_timeout"
    assert not manager.streams
    await subscribe(client, manager, identifier=2, after_sequence=0)
    replay = await page(client, 2)
    assert [row["sequence"] for row in replay["events"]] == [1]
    await ack(client, replay, 3)
    await client.close()


async def test_authentication_entry_isolation_and_complete_http_export(
    event_manager, hass_ws_client, hass_client, hass_read_only_access_token
):
    """The normal HA client can export all records; read-only accounts cannot."""
    manager = event_manager
    for number in range(270):
        manager.event("network-a", observation(number))
    manager.event("network-b", observation(271))
    await manager.flush()
    viewer = await hass_ws_client(access_token=hass_read_only_access_token)
    await viewer.send_json({"id": 1, "type": "casambi_bt/events/networks"})
    assert not (await result(viewer, 1))["success"]
    await viewer.close()
    client = await hass_client()
    response = await client.post(
        "/api/casambi_bt/events/export",
        json={"entry_id": "network-a", "store_id": manager.store.store_id},
    )
    assert response.status == 200
    records = [json.loads(line) for line in (await response.text()).splitlines()]
    assert records[0]["kind"] == "manifest"
    assert records[-1]["kind"] == "complete"
    assert records[-1]["count"] == 270
    assert all(record["event"]["entry_id"] == "network-a" for record in records[1:-1])
    other = await hass_client(access_token=hass_read_only_access_token)
    response = await other.post(
        "/api/casambi_bt/events/export",
        json={"entry_id": "network-a", "store_id": manager.store.store_id},
    )
    assert response.status == 401
    assert await manager.store.get("network-a", 271) is None


async def test_invalid_export_identity_and_inverted_time_range_are_rejected(
    event_manager, hass_client, hass_ws_client
):
    """Expected client errors fail before streaming any archive content."""
    manager = event_manager
    client = await hass_client()
    for body in (
        {"entry_id": "unknown", "store_id": manager.store.store_id},
        {"entry_id": "network-a", "store_id": "replaced-store"},
        {
            "entry_id": "network-a",
            "store_id": manager.store.store_id,
            "filters": {"start_ms": 200, "end_ms": 100},
        },
    ):
        response = await client.post("/api/casambi_bt/events/export", json=body)
        assert response.status == 400
    viewer = await hass_ws_client()
    await viewer.send_json(
        {
            "id": 1,
            "type": "casambi_bt/events/query",
            "entry_id": "network-a",
            "store_id": manager.store.store_id,
            "filters": {"start_ms": 200, "end_ms": 100},
        }
    )
    assert not (await result(viewer, 1))["success"]
    await viewer.close()


async def test_actual_panel_registration_and_versioned_module_delivery(
    hass, hass_client, event_manager
):
    """The panel is registered in HA and serves the integration's ES module."""
    assert await async_setup_component(hass, "frontend", {})
    await frontend.async_register(hass, "synthetic-test")
    panel = hass.data["frontend_panels"]["casambi-events"]
    assert panel.require_admin
    client = await hass_client()
    response = await client.get("/casambi_bt/frontend/synthetic-test/casambi-events.js")
    assert response.status == 200
    assert 'customElements.define("casambi-events-panel"' in await response.text()


async def test_unit_links_use_current_registry_ids_and_scope_duplicate_units_to_entry(
    hass, event_manager, hass_ws_client, device_registry, entity_registry
):
    """Names, unit numbers and even shared UUIDs cannot select a different entry."""
    entries = {
        identifier: MockConfigEntry(domain="casambi_bt", entry_id=identifier)
        for identifier in ("network-a", "network-b")
    }
    for entry in entries.values():
        entry.add_to_hass(hass)
    unit = SimpleNamespace(deviceId=30, uuid="shared-unit-uuid", name="Same switch")
    hass.data["casambi_bt"] = {
        identifier: SimpleNamespace(
            casa=SimpleNamespace(
                units=[
                    unit,
                    SimpleNamespace(deviceId=31, uuid="missing", name="Missing"),
                ]
            )
        )
        for identifier in ("network-a", "network-b")
    }
    devices = {
        identifier: device_registry.async_get_or_create(
            config_entry_id=identifier,
            identifiers={("casambi_bt", unit.uuid)},
            name="Same switch",
        )
        for identifier in ("network-a", "network-b")
    }
    light = entity_registry.async_get_or_create(
        "light",
        "casambi_bt",
        "unit-light-a",
        config_entry=entries["network-a"],
        device_id=devices["network-a"].id,
        original_name="Original light",
    )
    renamed = entity_registry.async_update_entity(
        light.entity_id, new_entity_id="light.renamed_by_user", name="Renamed light"
    )
    disabled = entity_registry.async_get_or_create(
        "sensor",
        "casambi_bt",
        "unit-disabled-a",
        config_entry=entries["network-a"],
        device_id=devices["network-a"].id,
        disabled_by=RegistryEntryDisabler.USER,
        original_name="Raw configuration",
    )
    other = entity_registry.async_get_or_create(
        "sensor",
        "casambi_bt",
        "unit-sensor-b",
        config_entry=entries["network-b"],
        device_id=devices["network-b"].id,
        original_name="Other network",
    )
    client = await hass_ws_client()
    for number, entry_id in enumerate(("network-a", "network-b"), start=1):
        await client.send_json(
            {
                "id": number,
                "type": "casambi_bt/events/unit",
                "entry_id": entry_id,
                "unit": 30,
            }
        )
        response = await result(client, number)
        assert response["success"]
        links = response["result"]
        assert links["status"] == "ready"
        assert links["device"]["id"] == devices[entry_id].id
        if entry_id == "network-a":
            assert links["entities"] == [
                {
                    "entity_id": renamed.entity_id,
                    "name": "Renamed light",
                    "disabled": False,
                },
                {
                    "entity_id": disabled.entity_id,
                    "name": "Raw configuration",
                    "disabled": True,
                },
            ]
        else:
            assert [entity["entity_id"] for entity in links["entities"]] == [
                other.entity_id
            ]
    for number, unit_id in enumerate((31, 99), start=3):
        await client.send_json(
            {
                "id": number,
                "type": "casambi_bt/events/unit",
                "entry_id": "network-a",
                "unit": unit_id,
            }
        )
        links = (await result(client, number))["result"]
        assert links == {
            "unit": unit_id,
            "status": "not_found",
            "device": None,
            "entities": [],
        }
    hass.data["casambi_bt"].pop("network-a")
    await client.send_json(
        {
            "id": 5,
            "type": "casambi_bt/events/unit",
            "entry_id": "network-a",
            "unit": 30,
        }
    )
    assert (await result(client, 5))["result"]["status"] == "unloaded"
    await client.close()


async def test_unit_links_require_administrator_and_reject_unknown_network(
    event_manager, hass_ws_client, hass_read_only_access_token
):
    """Unit metadata follows the same authentication and entry boundary as events."""
    client = await hass_ws_client(access_token=hass_read_only_access_token)
    await client.send_json(
        {
            "id": 1,
            "type": "casambi_bt/events/unit",
            "entry_id": "network-a",
            "unit": 30,
        }
    )
    assert not (await result(client, 1))["success"]
    await client.close()
    client = await hass_ws_client()
    await client.send_json(
        {
            "id": 1,
            "type": "casambi_bt/events/unit",
            "entry_id": "unknown",
            "unit": 30,
        }
    )
    assert not (await result(client, 1))["success"]
    await client.close()


async def test_full_entry_reload_keeps_archive_identity_and_one_gatt_client(
    hass, tmp_path, enable_custom_integrations, hass_ws_client
):
    """Exercise integration setup/reload through HA with only the radio mocked."""
    hass.config.config_dir = str(tmp_path)
    instances = []

    def radio_client(*_args):
        casa = Mock(
            connected=True,
            networkName="Synthetic network",
            networkId="synthetic-network",
            rawNetworkData={"network": {"protocolVersion": 11}},
        )
        casa.connect = AsyncMock()
        casa.disconnect = AsyncMock()
        instances.append(casa)
        return casa

    entry = MockConfigEntry(
        domain="casambi_bt",
        title="Synthetic network",
        data={
            "address": "11:22:33:44:55:66",
            "password": "synthetic-test-password",
        },
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "homeassistant.components.bluetooth.async_setup",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "homeassistant.components.bluetooth_adapters.async_setup",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "homeassistant.components.usb.async_setup", new=AsyncMock(return_value=True)
        ),
        patch("custom_components.casambi_bt.Casambi", side_effect=radio_client),
        patch(
            "custom_components.casambi_bt.bluetooth.async_ble_device_from_address",
            return_value=BLEDevice("11:22:33:44:55:66", "Synthetic", {}),
        ),
        patch(
            "custom_components.casambi_bt.bluetooth.async_register_callback",
            return_value=Mock(),
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ),
        patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ),
    ):
        assert await async_setup_component(hass, "casambi_bt", {})
        await hass.async_block_till_done()
        assert len(instances) == 1
        manager = hass.data[DATA_NETWORK_EVENTS]
        original_store = manager.store.store_id
        api = hass.data["casambi_bt"][entry.entry_id]
        api._network_event_handler(observation())  # noqa: SLF001
        await manager.flush()
        first_connection = manager.status(entry.entry_id)["connection_id"]
        first = await hass_ws_client()
        second = await hass_ws_client()
        for client in (first, second):
            await client.send_json({"id": 1, "type": "casambi_bt/events/networks"})
            assert (await result(client, 1))["success"]
        assert len(instances) == 1
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert hass.data[DATA_NETWORK_EVENTS] is manager
        assert manager.store.store_id == original_store
        assert len(instances) == 2
        assert manager.status(entry.entry_id)["connection_id"] != first_connection
        assert manager.status(entry.entry_id)["saved"] == 1
        api = hass.data["casambi_bt"][entry.entry_id]
        api._network_event_handler(observation(2))  # noqa: SLF001
        await manager.flush()
        assert (await manager.store.query(entry.entry_id, {}, upper=2))["events"][0][
            "sequence"
        ] == 2
        await first.close()
        await second.close()
        await hass.config_entries.async_unload(entry.entry_id)

"""Authenticated, acknowledged archive subscriptions over HA's connection."""

from __future__ import annotations

import asyncio
from typing import Any

from CasambiBt.errors import ConnectionStateError
import probatio as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .event_store import SCHEMA_VERSION
from .network_events import DATA_NETWORK_EVENTS, NetworkEventsManager

ACK_TIMEOUT = 15
NONNEGATIVE = vol.All(int, vol.Range(min=0))


def validate_filter_range(filters: dict) -> dict:
    """Reject an inverted time range at both transport boundaries."""
    if (
        "start_ms" in filters
        and "end_ms" in filters
        and filters["end_ms"] < filters["start_ms"]
    ):
        raise vol.Invalid("end_ms precedes start_ms")
    return filters


FILTER_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("query"): vol.All(str, vol.Length(max=512)),
            vol.Optional("unit"): NONNEGATIVE,
            vol.Optional("event_type"): str,
            vol.Optional("source"): str,
            vol.Optional("source_stream"): str,
            vol.Optional("start_ms"): NONNEGATIVE,
            vol.Optional("end_ms"): NONNEGATIVE,
        }
    ),
    validate_filter_range,
)


def manager_for(hass: HomeAssistant) -> NetworkEventsManager:
    """Return the one integration-owned collector."""
    return hass.data[DATA_NETWORK_EVENTS]


def validate_entry(manager: NetworkEventsManager, entry_id: str) -> None:
    """Scope every read to a known configured or archived network."""
    if entry_id not in manager.networks:
        raise HomeAssistantError("Unknown Casambi network")


def validate_cursor(manager: NetworkEventsManager, store_id: str | None) -> None:
    """Report store replacement instead of silently starting over."""
    if not manager.archive_ready:
        raise HomeAssistantError("archive_unavailable")
    if store_id is not None and store_id != manager.store.store_id:
        raise HomeAssistantError("store_reset")


class EventSubscription:
    """Read committed pages with only one unacknowledged page per client."""

    def __init__(
        self, manager: NetworkEventsManager, connection, message: dict
    ) -> None:
        """Register wakeups before the first archive watermark is read."""
        self.manager, self.connection, self.message = manager, connection, message
        self.entry_id = message["entry_id"]
        self.cursor: int | None = message.get("after_sequence")
        self.generation = message["generation"]
        self._wake = asyncio.Event()
        self._remove = manager.listen(self._wake)
        self._pending: asyncio.Future | None = None
        self._sent_cursor: int | None = None
        self._task: asyncio.Task | None = None
        self._key = (id(connection), message["id"])
        self._closed = False

    def start(self) -> None:
        """Start delivery after HA has acknowledged subscription creation."""
        self._task = asyncio.create_task(self._run(), name="Casambi event subscription")

    def close(self) -> None:
        """Cancel sender work and release the connection's subscription exactly once."""
        if self._closed:
            return
        self._closed = True
        self._remove()
        self.manager.streams.pop(self._key, None)
        # HA iterates this mapping while disconnecting. Remove our entry afterward.
        asyncio.get_running_loop().call_soon(self._forget_subscription)
        if self._task is not None and self._task is not asyncio.current_task():
            self._task.cancel()

    def _forget_subscription(self) -> None:
        if self.connection.subscriptions.get(self.message["id"]) == self.close:
            self.connection.subscriptions.pop(self.message["id"], None)

    def acknowledge(self, sequence: int, generation: int) -> None:
        """Accept only the outstanding page, with idempotent repeated acknowledgements."""
        if generation != self.generation:
            raise HomeAssistantError("Invalid subscription generation")
        if self.cursor is not None and sequence == self.cursor:
            return
        if (
            self._pending is not None
            and self._pending.done()
            and sequence == self._sent_cursor
        ):
            return
        if (
            self._pending is None
            or self._pending.done()
            or sequence != self._sent_cursor
        ):
            raise HomeAssistantError("Invalid acknowledgement cursor")
        self._pending.set_result(sequence)

    def _send(self, kind: str, **data: Any) -> None:
        self.connection.send_event(
            self.message["id"],
            {
                "kind": kind,
                "schema_version": SCHEMA_VERSION,
                "subscription_id": self.message["id"],
                "store_id": self.manager.store.store_id,
                "entry_id": self.entry_id,
                "subscription_generation": self.generation,
                **data,
            },
        )

    async def _page(self, phase: str, page: dict) -> None:
        self._sent_cursor = page["scanned_to_sequence"]
        self._pending = asyncio.get_running_loop().create_future()
        self._send("events", phase=phase, **page)
        async with asyncio.timeout(ACK_TIMEOUT):
            self.cursor = await self._pending
        self._pending = None

    async def _run(self) -> None:
        try:
            first = True
            while not self._closed:
                await asyncio.sleep(0.05)
                self._wake.clear()
                status = self.manager.status(self.entry_id)
                self._send("status", status=status)
                if self.message["mode"] != "status_only":
                    upper = await self.manager.store.watermark()
                    if self.cursor is not None and self.cursor > upper:
                        self._send("error", code="invalid_cursor")
                        return
                    if self.cursor is None:
                        page = await self.manager.store.query(
                            self.entry_id, self.message["filters"], upper=upper
                        )
                        self._send(
                            "facets",
                            **(await self.manager.store.facets(self.entry_id)),
                            gaps=await self.manager.store.gaps(self.entry_id),
                        )
                        await self._page("snapshot", page)
                    elif self.cursor < upper:
                        more = True
                        while more:
                            page = await self.manager.store.query(
                                self.entry_id,
                                self.message["filters"],
                                upper=upper,
                                after=self.cursor,
                            )
                            more = page["has_more"]
                            await self._page("catch_up" if first else "live", page)
                    first = False
                    self._send("caught_up", scanned_to_sequence=self.cursor)
                await self._wake.wait()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            self._send("error", code="ack_timeout")
        except Exception as error:  # noqa: BLE001
            # This is a network recovery boundary; payloads and exception text stay private.
            self._send(
                "error", code="archive_read_failed", exception_type=type(error).__name__
            )
        finally:
            self.close()


@callback
@websocket_api.websocket_command({vol.Required("type"): "casambi_bt/events/networks"})
@websocket_api.require_admin
def networks(hass: HomeAssistant, connection, message: dict) -> None:
    """List current and archived public network metadata."""
    manager = manager_for(hass)
    connection.send_result(
        message["id"],
        {
            "store_id": manager.store.store_id,
            "schema_version": SCHEMA_VERSION,
            "networks": [manager.status(entry_id) for entry_id in manager.networks],
        },
    )


@callback
@websocket_api.websocket_command(
    {
        vol.Required("type"): "casambi_bt/events/subscribe",
        vol.Required("entry_id"): cv.string,
        vol.Required("generation"): NONNEGATIVE,
        vol.Optional("filters", default=dict): FILTER_SCHEMA,
        vol.Optional("store_id"): cv.string,
        vol.Optional("after_sequence"): NONNEGATIVE,
        vol.Optional("mode", default="events"): vol.In(("events", "status_only")),
    }
)
@websocket_api.require_admin
def subscribe(hass: HomeAssistant, connection, message: dict) -> None:
    """Create a subscription without opening another Casambi connection."""
    manager = manager_for(hass)
    validate_entry(manager, message["entry_id"])
    validate_cursor(manager, message.get("store_id"))
    if "after_sequence" in message and "store_id" not in message:
        raise HomeAssistantError("A resume cursor requires a store ID")
    stream = EventSubscription(manager, connection, message)
    manager.streams[(id(connection), message["id"])] = stream
    connection.subscriptions[message["id"]] = stream.close
    connection.send_result(message["id"])
    stream.start()


@callback
@websocket_api.websocket_command(
    {
        vol.Required("type"): "casambi_bt/events/ack",
        vol.Required("subscription"): NONNEGATIVE,
        vol.Required("generation"): NONNEGATIVE,
        vol.Required("sequence"): NONNEGATIVE,
    }
)
@websocket_api.require_admin
def acknowledge(hass: HomeAssistant, connection, message: dict) -> None:
    """Advance only a subscription belonging to the authenticated connection."""
    stream = manager_for(hass).streams.get((id(connection), message["subscription"]))
    if stream is None:
        raise HomeAssistantError("Unknown observation subscription")
    stream.acknowledge(message["sequence"], message["generation"])
    connection.send_result(message["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "casambi_bt/events/query",
        vol.Required("entry_id"): cv.string,
        vol.Required("store_id"): cv.string,
        vol.Optional("filters", default=dict): FILTER_SCHEMA,
        vol.Optional("before_sequence"): NONNEGATIVE,
        vol.Optional("upper_sequence"): NONNEGATIVE,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def query(hass: HomeAssistant, connection, message: dict) -> None:
    """Page through the whole archive using a fixed upper watermark."""
    manager = manager_for(hass)
    validate_entry(manager, message["entry_id"])
    validate_cursor(manager, message["store_id"])
    upper = message.get("upper_sequence")
    if upper is None:
        upper = await manager.store.watermark()
    page = await manager.store.query(
        message["entry_id"],
        message["filters"],
        upper=upper,
        before=message.get("before_sequence"),
    )
    connection.send_result(message["id"], page)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "casambi_bt/events/get",
        vol.Required("entry_id"): cv.string,
        vol.Required("store_id"): cv.string,
        vol.Required("sequence"): NONNEGATIVE,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def get_event(hass: HomeAssistant, connection, message: dict) -> None:
    """Retrieve one inspected observation, scoped to its owning network."""
    manager = manager_for(hass)
    validate_entry(manager, message["entry_id"])
    validate_cursor(manager, message["store_id"])
    event = await manager.store.get(message["entry_id"], message["sequence"])
    if event is None:
        raise HomeAssistantError("Observation not found")
    connection.send_result(message["id"], event)


@callback
@websocket_api.websocket_command(
    {
        vol.Required("type"): "casambi_bt/events/unit",
        vol.Required("entry_id"): cv.string,
        vol.Required("unit"): NONNEGATIVE,
    }
)
@websocket_api.require_admin
def unit_links(hass: HomeAssistant, connection, message: dict) -> None:
    """Resolve the current unit UUID through the owning entry's HA registries."""
    entry_id, unit_id = message["entry_id"], message["unit"]
    validate_entry(manager_for(hass), entry_id)
    result = {"unit": unit_id, "status": "unloaded", "device": None, "entities": []}
    api = hass.data.get(DOMAIN, {}).get(entry_id)
    if api is not None:
        try:
            units = api.casa.units
        except ConnectionStateError:
            units = None
        if units is not None:
            result["status"] = "not_found"
            unit = next((unit for unit in units if unit.deviceId == unit_id), None)
            if unit is not None and (
                device := dr.async_get(hass).async_get_device_by_identifier(
                    (DOMAIN, unit.uuid), entry_id
                )
            ):
                result["status"] = "ready"
                result["device"] = {
                    "id": device.id,
                    "name": device.name_by_user or device.name or unit.name,
                }
                result["entities"] = [
                    {
                        "entity_id": entity.entity_id,
                        "name": entity.name or entity.original_name or entity.entity_id,
                        "disabled": entity.disabled_by is not None,
                    }
                    for entity in sorted(
                        er.async_entries_for_device(
                            er.async_get(hass),
                            device.id,
                            include_disabled_entities=True,
                        ),
                        key=lambda entity: entity.entity_id,
                    )
                    if entity.config_entry_id == entry_id and entity.platform == DOMAIN
                ]
    connection.send_result(message["id"], result)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register commands once for this integration runtime."""
    for command in (networks, subscribe, acknowledge, query, get_event, unit_links):
        websocket_api.async_register_command(hass, command)

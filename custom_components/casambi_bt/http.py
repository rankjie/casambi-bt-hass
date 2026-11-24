"""Stream complete approved archives through HA's authenticated HTTP client."""

import json

from aiohttp import web
from CasambiBt.errors import CasambiBtError
import probatio as vol

from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.http import KEY_HASS

from .backup import async_create_backup
from .const import DOMAIN
from .event_store import SCHEMA_VERSION
from .network_events import DATA_NETWORK_EVENTS
from .websocket_api import FILTER_SCHEMA, validate_cursor, validate_entry

BACKUP_SCHEMA = vol.Schema({vol.Required("entry_id"): str})

EXPORT_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Required("store_id"): str,
        vol.Optional("filters", default=dict): FILTER_SCHEMA,
    }
)


class EventExportView(HomeAssistantView):
    """Export a fixed archive range without depending on browser-loaded pages."""

    url = "/api/casambi_bt/events/export"
    name = "api:casambi_bt:events:export"
    requires_auth = True

    @require_admin
    async def post(self, request: web.Request) -> web.StreamResponse:
        """Emit typed JSONL with a final completion record."""
        try:
            data = EXPORT_SCHEMA(await request.json())
        except (vol.Invalid, ValueError) as error:
            raise web.HTTPBadRequest(text="Invalid export request") from error
        manager = request.app[KEY_HASS].data[DATA_NETWORK_EVENTS]
        try:
            validate_entry(manager, data["entry_id"])
            validate_cursor(manager, data["store_id"])
        except HomeAssistantError as error:
            raise web.HTTPBadRequest(text=str(error)) from error
        upper = await manager.store.watermark()
        response = web.StreamResponse(
            headers={
                "Content-Type": "application/x-ndjson; charset=utf-8",
                "Content-Disposition": 'attachment; filename="casambi-events.jsonl"',
                "Cache-Control": "no-store",
            }
        )
        await response.prepare(request)

        async def emit(record):
            await response.write(
                (
                    json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
                ).encode()
            )

        await emit(
            {
                "kind": "manifest",
                "schema_version": SCHEMA_VERSION,
                "store_id": manager.store.store_id,
                "entry_id": data["entry_id"],
                "upper_sequence": upper,
                "filters": data["filters"],
                "gaps": await manager.store.gaps(data["entry_id"]),
            }
        )
        cursor = count = 0
        while True:
            page = await manager.store.query(
                data["entry_id"], data["filters"], upper=upper, after=cursor
            )
            for event in page["events"]:
                await emit({"kind": "event", "event": event})
                count += 1
            cursor = page["scanned_to_sequence"]
            if not page["has_more"]:
                break
        await emit({"kind": "complete", "count": count, "scanned_to_sequence": cursor})
        await response.write_eof()
        return response


class BackupView(HomeAssistantView):
    """Download the backup file that sets a network up on a fresh HA."""

    url = "/api/casambi_bt/backup"
    name = "api:casambi_bt:backup"
    requires_auth = True

    @require_admin
    async def post(self, request: web.Request) -> web.Response:
        """Return the backup of a loaded network; it holds the network keys."""
        try:
            entry_id = BACKUP_SCHEMA(await request.json())["entry_id"]
        except (vol.Invalid, ValueError) as error:
            raise web.HTTPBadRequest(text="Invalid backup request") from error
        api = request.app[KEY_HASS].data.get(DOMAIN, {}).get(entry_id)
        if api is None:
            raise web.HTTPBadRequest(text="The network isn't loaded")
        try:
            backup = await async_create_backup(api)
        except CasambiBtError as error:
            raise web.HTTPConflict(text=str(error)) from error
        return web.Response(
            text=json.dumps(backup, ensure_ascii=False, indent=2),
            content_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="casambi-backup.json"',
                "Cache-Control": "no-store",
            },
        )


def async_register(hass: HomeAssistant) -> None:
    """Register the authenticated export endpoints once."""
    hass.http.register_view(EventExportView())
    hass.http.register_view(BackupView())

"""Offline-first start, background refresh and backup files.

The integration runs against the real casambi-bt library and a fake Casambi
cloud; only the bluetooth radio is replaced.
"""

from contextlib import ExitStack, contextmanager
import json
import shutil
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from bleak.backends.device import BLEDevice
import httpx
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

DOMAIN = "casambi_bt"
ADDRESS = "11:22:33:44:55:66"
UUID = "112233445566"
NETWORK_ID = "synthetic-network-id"
PASSWORD = "synthetic-test-password"
FILE_ID = "00000000-0000-4000-8000-000000000001"
FIXTURE = {
    "id": 4711,
    "model": "Synthetic dimmer",
    "vendor": "Test",
    "mode": "Dimmer",
    "stateLength": 1,
    "controls": [
        {"type": "dimmer", "offset": 0, "length": 8, "default": 0, "readonly": False}
    ],
}


def _network(revision: int, names: list[str]) -> dict:
    return {
        "status": "OK",
        "network": {
            "revision": revision,
            "name": "Synthetic network",
            "protocolVersion": 10,
            "keyStore": {
                "keys": [{"id": 1, "type": 1, "role": 3, "name": "m", "key": "00" * 16}]
            },
            "units": [
                {
                    "type": FIXTURE["id"],
                    "deviceID": i + 1,
                    "uuid": f"{i:012x}",
                    "address": f"{i:012x}",
                    "name": name,
                    "firmware": "1.0",
                }
                for i, name in enumerate(names)
            ],
            "grid": {"cells": []},
            "scenes": [],
        },
    }


class FakeCloud:
    """Answers like the Casambi cloud; `mode` selects a failure."""

    def __init__(self) -> None:
        """Start healthy with one lamp."""
        self.network = _network(1, ["Lamp"])
        self.password = PASSWORD
        self.mode = "ok"
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Answer one request."""
        path = request.url.path
        self.requests.append(path)
        if self.mode == "down":
            raise httpx.ConnectError("synthetic outage", request=request)
        if path == f"/network/uuid/{UUID}":
            return httpx.Response(200, json={"id": NETWORK_ID})
        if path == f"/network/{NETWORK_ID}/session":
            if json.loads(request.content)["password"] != self.password:
                return httpx.Response(401)
            return httpx.Response(
                200,
                json={
                    "session": "synthetic-session",
                    "network": NETWORK_ID,
                    "manager": True,
                    "keyID": 1,
                    "expires": int((time.time() + 3600) * 1000),
                },
            )
        if path == f"/network/{NETWORK_ID}/":
            if self.mode == "gone":
                # The answer after the password was changed in the app.
                return httpx.Response(410)
            if (
                json.loads(request.content)["revision"]
                == self.network["network"]["revision"]
            ):
                return httpx.Response(200, json={"status": "UPTODATE"})
            return httpx.Response(200, json=self.network)
        if path == f"/fixture/{FIXTURE['id']}":
            return httpx.Response(200, json=FIXTURE)
        return httpx.Response(404)


@pytest.fixture
async def cloud(hass, tmp_path, enable_custom_integrations):
    """Run the integration with a fake cloud and a fake bluetooth radio."""
    hass.config.config_dir = str(tmp_path)
    fake = FakeCloud()
    fake.radio = SimpleNamespace(device=BLEDevice(ADDRESS, "Synthetic", {}), scanners=1)
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))

    def device(*_args, **_kwargs):
        return fake.radio.device

    def scanners(*_args, **_kwargs):
        return fake.radio.scanners

    with ExitStack() as stack:
        for target, kwargs in (
            (
                "homeassistant.components.bluetooth.async_setup",
                {"new": AsyncMock(return_value=True)},
            ),
            (
                "homeassistant.components.bluetooth_adapters.async_setup",
                {"new": AsyncMock(return_value=True)},
            ),
            (
                "homeassistant.components.usb.async_setup",
                {"new": AsyncMock(return_value=True)},
            ),
            ("custom_components.casambi_bt.get_async_client", {"return_value": client}),
            (
                "custom_components.casambi_bt.config_flow.get_async_client",
                {"return_value": client},
            ),
            (
                "custom_components.casambi_bt.backup.get_async_client",
                {"return_value": client},
            ),
            (
                "custom_components.casambi_bt.bluetooth.async_ble_device_from_address",
                {"side_effect": device},
            ),
            (
                "custom_components.casambi_bt.config_flow.async_ble_device_from_address",
                {"side_effect": device},
            ),
            (
                "custom_components.casambi_bt.config_flow.async_scanner_count",
                {"side_effect": scanners},
            ),
            (
                "custom_components.casambi_bt.config_flow.async_get_gateways",
                {"return_value": []},
            ),
            (
                "custom_components.casambi_bt.bluetooth.async_register_callback",
                {"return_value": Mock()},
            ),
            ("CasambiBt._casambi.Casambi._connectClient", {"new": AsyncMock()}),
            ("CasambiBt._casambi.CasambiClient", {}),
        ):
            stack.enter_context(patch(target, **kwargs))
        stack.enter_context(
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            )
        )
        stack.enter_context(
            patch.object(
                hass.config_entries,
                "async_unload_platforms",
                new=AsyncMock(return_value=True),
            )
        )
        assert await async_setup_component(hass, DOMAIN, {})
        yield fake
    await client.aclose()


async def _add_entry(
    hass, password: str, gateway: str | None = None
) -> MockConfigEntry:
    data = {"address": ADDRESS, "password": password, "import_groups": True}
    if gateway is not None:
        data["gateway_address"] = gateway
    entry = MockConfigEntry(
        domain=DOMAIN, title="Synthetic network", unique_id=ADDRESS, data=data
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _download(hass_client, entry_id: str):
    client = await hass_client()
    return await client.post("/api/casambi_bt/backup", json={"entry_id": entry_id})


async def _import(hass, tmp_path, content: str):
    """Run the backup step of the config flow with an uploaded file."""
    upload = tmp_path / "upload.json"
    upload.write_text(content)

    @contextmanager
    def uploaded(_hass, file_id):
        assert file_id == FILE_ID
        yield upload

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "backup"}
    )
    with patch(
        "custom_components.casambi_bt.config_flow.process_uploaded_file", uploaded
    ):
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], {"backup": FILE_ID}
        )


async def _fresh_install(hass, entry) -> None:
    """Remove the entry and its cache like a new Home Assistant would lack them."""
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.async_add_executor_job(
        shutil.rmtree, hass.config.path(".storage", DOMAIN)
    )


async def test_backup_file_restores_without_cloud_or_bluetooth(
    hass, cloud, hass_client, tmp_path
) -> None:
    """Download a backup, then add it on a fresh install with no radio and no cloud."""
    entry = await _add_entry(hass, PASSWORD, gateway="AA:BB:CC:DD:EE:02")
    response = await _download(hass_client, entry.entry_id)
    assert response.status == 200
    assert "attachment" in response.headers["Content-Disposition"]
    content = await response.text()
    await _fresh_install(hass, entry)

    cloud.mode = "down"
    cloud.radio.device = None
    cloud.radio.scanners = 0
    result = await _import(hass, tmp_path, content)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Synthetic network"
    assert result["data"] == {
        "address": ADDRESS,
        "password": PASSWORD,
        "import_groups": True,
        "gateway_address": "AA:BB:CC:DD:EE:02",
    }
    await hass.async_block_till_done(wait_background_tasks=True)
    restored = hass.config_entries.async_entries(DOMAIN)[0]
    # Nothing to connect to yet: HA retries until the network shows up.
    assert restored.state is ConfigEntryState.SETUP_RETRY

    cloud.radio.device = BLEDevice(ADDRESS, "Synthetic", {})
    assert await hass.config_entries.async_reload(restored.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert restored.state is ConfigEntryState.LOADED
    api = hass.data[DOMAIN][restored.entry_id]
    assert [u.name for u in api.casa.units] == ["Lamp"]
    assert not api.offline


async def test_backup_without_password_never_contacts_the_cloud(
    hass, cloud, hass_client, tmp_path
) -> None:
    """A backup whose password was removed runs the entry offline."""
    entry = await _add_entry(hass, PASSWORD)
    backup = await (await _download(hass_client, entry.entry_id)).json()
    await _fresh_install(hass, entry)
    backup["entry"]["password"] = ""

    cloud.requests.clear()
    result = await _import(hass, tmp_path, json.dumps(backup))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    restored = hass.config_entries.async_entries(DOMAIN)[0]
    api = hass.data[DOMAIN][restored.entry_id]
    assert api.offline
    await api.async_refresh_network()
    assert [u.name for u in api.casa.units] == ["Lamp"]
    assert cloud.requests == []


async def test_invalid_backup_files_are_rejected(
    hass, cloud, hass_client, tmp_path
) -> None:
    """Files that aren't a backup of this network are reported, not imported."""
    entry = await _add_entry(hass, PASSWORD)
    backup = await (await _download(hass_client, entry.entry_id)).json()
    await _fresh_install(hass, entry)

    other_network = json.loads(json.dumps(backup))
    other_network["entry"]["address"] = "AA:AA:AA:AA:AA:AA"
    broken_network = json.loads(json.dumps(backup))
    del broken_network["library"]["network"]
    for content in (
        "not json",
        "[]",
        json.dumps(backup["library"]),
        json.dumps(other_network),
        json.dumps(broken_network),
    ):
        result = await _import(hass, tmp_path, content)
        assert result["errors"] == {"base": "invalid_backup"}, content[:40]
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_backup_download_is_admin_only_and_needs_a_loaded_network(
    hass, cloud, hass_client, hass_read_only_access_token
) -> None:
    """The file holds the network keys."""
    entry = await _add_entry(hass, PASSWORD)
    client = await hass_client(hass_read_only_access_token)
    response = await client.post(
        "/api/casambi_bt/backup", json={"entry_id": entry.entry_id}
    )
    assert response.status == 401
    assert (await _download(hass_client, "missing")).status == 400


async def test_start_uses_the_cache_and_refresh_reloads_on_changes(hass, cloud) -> None:
    """A restart needs no cloud; a changed network is picked up by the refresh."""
    entry = await _add_entry(hass, PASSWORD)
    await hass.config_entries.async_unload(entry.entry_id)

    cloud.mode = "down"
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    api = hass.data[DOMAIN][entry.entry_id]
    assert [u.name for u in api.casa.units] == ["Lamp"]

    cloud.mode = "ok"
    cloud.network = _network(2, ["Lamp", "New lamp"])
    await api.async_refresh_network()
    await hass.async_block_till_done(wait_background_tasks=True)
    api = hass.data[DOMAIN][entry.entry_id]
    assert [u.name for u in api.casa.units] == ["Lamp", "New lamp"]


async def test_changed_password_starts_reauth_and_keeps_running(hass, cloud) -> None:
    """A password changed in the app asks for the new one; the network stays loaded."""
    entry = await _add_entry(hass, PASSWORD)
    api = hass.data[DOMAIN][entry.entry_id]

    cloud.password = "new-password"
    cloud.mode = "gone"
    await api.async_refresh_network()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.data[DOMAIN][entry.entry_id] is api
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]

    cloud.mode = "ok"
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"password": PASSWORD}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"password": "new-password"}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data["password"] == "new-password"
    assert [u.name for u in hass.data[DOMAIN][entry.entry_id].casa.units] == ["Lamp"]

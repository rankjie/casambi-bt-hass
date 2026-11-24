"""Config flow for Casambi Bluetooth integration."""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
from typing import Any

from CasambiBt import Casambi
from CasambiBt.errors import (
    AuthenticationError,
    CloudUnavailableError,
    NetworkNotFoundError,
    NetworkOnlineUpdateNeededError,
    OfflineBackupError,
)
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
    async_scanner_count,
)
from homeassistant.components.bluetooth.models import BluetoothServiceInfoBleak
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.httpx_client import get_async_client

from . import credentials_rejected, get_cache_dir
from .backup import InvalidBackupError, async_restore_backup
from .const import CONF_BACKUP, CONF_GATEWAY_ADDRESS, CONF_IMPORT_GROUPS, DOMAIN
from .gateway import async_get_gateways

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADDRESS): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_IMPORT_GROUPS, default=True): cv.boolean,
    }
)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): cv.string,
    }
)

BACKUP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BACKUP): selector.FileSelector(
            selector.FileSelectorConfig(accept=".json,application/json")
        ),
    }
)


def _read_backup_file(hass: HomeAssistant, file_id: str) -> Any:
    """Read an uploaded backup file; runs in the executor."""
    with process_uploaded_file(hass, file_id) as path:
        return json.loads(path.read_text(encoding="utf-8"))


def _error_key(err: Exception) -> str:
    """Map a failed connection attempt to a form error."""
    if isinstance(err, AuthenticationError):
        return "invalid_auth" if credentials_rejected(err) else "cannot_connect"
    if isinstance(err, (CloudUnavailableError, NetworkOnlineUpdateNeededError)):
        return "cloud_unavailable"
    if isinstance(err, NetworkNotFoundError):
        return "cannot_connect"
    _LOGGER.exception("Unexpected exception", exc_info=err)
    return "unknown"


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    client = get_async_client(hass)
    casa = Casambi(client, get_cache_dir(hass))
    bt_device = async_ble_device_from_address(
        hass, data.get(CONF_GATEWAY_ADDRESS, data[CONF_ADDRESS]), connectable=True
    )

    if not bt_device:
        raise NetworkNotFoundError

    await casa.invalidateCache(data[CONF_ADDRESS])
    await casa.connect(
        bt_device, data[CONF_PASSWORD], networkAddress=data[CONF_ADDRESS]
    )
    try:
        return {
            "title": casa.networkName,
            "id": data[CONF_ADDRESS],
            "unit_names": {unit.deviceId: unit.name for unit in casa.units},
        }
    finally:
        # Release the GATT connection before HA sets up the entry.
        await casa.disconnect()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Casambi Bluetooth."""

    discovery_info: BluetoothServiceInfoBleak | None = None

    VERSION = 1

    def __init__(self) -> None:
        """Keep network validation separate from gateway selection."""
        super().__init__()
        self._network_data: dict[str, Any] | None = None
        self._network_info: dict[str, Any] | None = None

    async def _async_create_casa_entry(
        self, title: str, id: str, data: dict[str, Any]
    ) -> FlowResult:
        existing_entry = await self.async_set_unique_id(id)

        if existing_entry:
            changed = self.hass.config_entries.async_update_entry(
                existing_entry, unique_id=id, title=title, data=data
            )

            if not changed:
                return self.async_abort(reason="already_configured")

            self.hass.async_create_task(
                self.hass.config_entries.async_reload(existing_entry.entry_id)
            )
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(title=title, data=data)

    async def async_step_bluetooth_error(
        self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle bluetooth errors.

        The config flow can't proceed if there is a bluetooth error so this is the last step.
        """
        return self.async_abort(reason="bluetooth_error")

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle bluetooth discovery."""
        self.discovery_info = discovery_info

        if not discovery_info.connectable:
            return self.async_abort(reason="Unsuitable discovery.")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        _LOGGER.debug(
            "Discovery: [%s] %s from %s. Advertisement: %s.",
            discovery_info.address,
            discovery_info.name,
            discovery_info.source,
            discovery_info.advertisement,
        )

        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose between the Casambi cloud and a backup file."""
        return self.async_show_menu(step_id="user", menu_options=["cloud", "backup"])

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle entry of network information and attempt to connect."""

        suggested_input = {}
        if self.discovery_info:
            suggested_input[CONF_ADDRESS] = self.discovery_info.address

        if async_scanner_count(self.hass, connectable=True) < 1:
            return self.async_show_form(step_id="bluetooth_error")

        if user_input:
            errors = {}

            user_input[CONF_ADDRESS] = format_mac(user_input[CONF_ADDRESS]).upper()

            if len(user_input[CONF_ADDRESS]) == 17:
                try:
                    info = await _validate_input(self.hass, user_input)
                except Exception as err:  # pylint: disable=broad-except
                    errors["base"] = _error_key(err)
                else:
                    self._network_data = dict(user_input)
                    self._network_info = info
                    return await self.async_step_gateway()
            else:
                errors["base"] = "invalid_address"

            return self.async_show_form(
                step_id="cloud",
                data_schema=self.add_suggested_values_to_schema(
                    USER_SCHEMA, user_input
                ),
                errors=errors,
            )

        return self.async_show_form(
            step_id="cloud",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, suggested_input
            ),
        )

    async def async_step_backup(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Set a network up from a backup file, without the cloud or Bluetooth.

        The entry connects as soon as Home Assistant sees the network.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                backup = await self.hass.async_add_executor_job(
                    _read_backup_file, self.hass, user_input[CONF_BACKUP]
                )
                title, data = await async_restore_backup(
                    self.hass, backup, get_cache_dir(self.hass)
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                InvalidBackupError,
                OfflineBackupError,
            ) as err:
                _LOGGER.warning("Invalid Casambi backup file: %s", err)
                errors["base"] = "invalid_backup"
            else:
                return await self._async_create_casa_entry(
                    title, data[CONF_ADDRESS], data
                )

        return self.async_show_form(
            step_id="backup", data_schema=BACKUP_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Change the GATT node without replacing the network identity."""
        return await self.async_step_gateway(user_input)

    async def async_step_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show current GATT receivers and select a same-network node."""
        entry = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            data = entry.data
            api = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            unit_names = (
                {unit.deviceId: unit.name for unit in api.casa.units} if api else {}
            )
        else:
            assert self._network_data is not None
            assert self._network_info is not None
            data = self._network_data
            unit_names = self._network_info["unit_names"]

        network_address = data[CONF_ADDRESS]
        current = data.get(CONF_GATEWAY_ADDRESS, network_address)
        gateways = async_get_gateways(self.hass, network_address)
        reachable = {node.address for node in gateways}
        errors = {}
        if user_input is not None:
            selected = user_input[CONF_GATEWAY_ADDRESS]
            if selected not in reachable and selected not in (network_address, current):
                errors["base"] = "gateway_unavailable"
            elif entry is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_GATEWAY_ADDRESS: selected},
                    reload_even_if_entry_is_unchanged=False,
                )
            else:
                assert self._network_info is not None
                return await self._async_create_casa_entry(
                    self._network_info["title"],
                    network_address,
                    {**data, CONF_GATEWAY_ADDRESS: selected},
                )

        options = []
        for node in gateways:
            name = (
                f"#{node.unit_id} {unit_names.get(node.unit_id, '')}".strip()
                if node.unit_id is not None
                else node.address
            )
            label = f"{name} · {node.rssi} dBm · {node.scanner_name}"
            if node.unit_id is not None:
                label += f" · {node.address}"
            options.append(selector.SelectOptionDict(value=node.address, label=label))
        if network_address not in reachable:
            options.insert(
                0,
                selector.SelectOptionDict(value=network_address, label=network_address),
            )
        if current not in reachable and current != network_address:
            options.insert(0, selector.SelectOptionDict(value=current, label=current))

        return self.async_show_form(
            step_id="gateway",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_GATEWAY_ADDRESS, default=current
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, mode=selector.SelectSelectorMode.DROPDOWN
                        )
                    ),
                }
            ),
            description_placeholders={"network_address": network_address},
            errors=errors,
            last_step=True,
        )

    async def async_step_reauth(self, _entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle re-authentication with Casambi."""
        self.entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm re-authentication with Casambi."""
        errors: dict[str, str] = {}
        assert self.entry is not None

        if user_input:
            data = {
                **self.entry.data,
                **user_input,
            }

            api = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
            try:
                if api is not None:
                    # The running network keeps its connection and cache; the
                    # cloud session was dropped when the password was rejected,
                    # so this is a real login with the new password.
                    await api.casa.refreshNetwork(data[CONF_PASSWORD])
                else:
                    await _validate_input(self.hass, data)
            except Exception as err:  # pylint: disable=broad-except
                errors["base"] = _error_key(err)
            else:
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data=data,
                )
                await self.hass.config_entries.async_reload(self.entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                REAUTH_SCHEMA, self.entry.data
            ),
            errors=errors,
        )

"""Exercise gateway discovery, configuration and reconnects without running HA."""

# ruff: noqa: PT009, PT027, SLF001

import ast
import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import voluptuous as vol

ROOT = Path(__file__).parent / "custom_components" / "casambi_bt"
NETWORK = "11:22:33:44:55:66"
NODE = "AA:BB:CC:DD:EE:02"


def load_declarations(filename, names, namespace):
    """Load production bodies, using the repository's HA-isolation test pattern."""
    path = ROOT / filename
    tree = ast.parse(path.read_text())
    body = [node for node in tree.body if getattr(node, "name", None) in names]
    body.insert(
        0,
        ast.ImportFrom(
            module="__future__", names=[ast.alias(name="annotations")], level=0
        ),
    )
    namespace = {"__name__": __name__, **namespace}
    exec(  # noqa: S102
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            str(path),
            "exec",
        ),
        namespace,
    )
    return namespace


def node_payload(unit_id=2, network=NETWORK, protocol=11):
    """Build a synthetic long advertisement with a different embedded unit MAC."""
    return (
        bytes.fromhex("010203040506")
        + bytes(6)
        + bytes.fromhex(network.replace(":", ""))
        + bytes((unit_id, protocol, 0, 0, 0))
    )


def scanner_path(payload, rssi=-60, name="GATT proxy", connectable=True):
    """Represent the public BluetoothScannerDevice fields used by discovery."""
    return SimpleNamespace(
        scanner=SimpleNamespace(name=name, connectable=connectable),
        advertisement=SimpleNamespace(manufacturer_data={963: payload}, rssi=rssi),
    )


def gateway_module(bluetooth):
    """Bind public Bluetooth APIs to a synthetic receiver inventory."""
    return load_declarations(
        "gateway.py",
        {
            "Gateway",
            "gateway_unit_id",
            "async_get_gateways",
        },
        {
            "dataclass": dataclass,
            "callback": lambda func: func,
            "bluetooth": bluetooth,
            "CASAMBI_MANUFACTURER_ID": 963,
        },
    )


class GatewayDiscoveryTest(unittest.TestCase):
    """Only same-network, complete EVO advertisements may become node choices."""

    def test_advertisement_boundaries(self):
        """Reject truncation, other networks, unassigned units and Classic nodes."""
        parser = gateway_module(Mock())["gateway_unit_id"]
        network = bytes.fromhex(NETWORK.replace(":", ""))
        for payload, expected in (
            (node_payload(protocol=10), 2),
            (node_payload(unit_id=28, protocol=43) + b"extra", 28),
            (node_payload()[:22], None),
            (b"", None),
            (node_payload(network="66:55:44:33:22:11"), None),
            (node_payload(protocol=9), None),
            (node_payload(unit_id=0), None),
        ):
            with self.subTest(length=len(payload), expected=expected):
                self.assertEqual(parser(payload, network), expected)

    def test_gatt_ranking_excludes_receive_only_scanners_and_uses_ble_address(self):
        """Show the strongest GATT path, including passive but connectable proxies."""
        second = "AA:BB:CC:DD:EE:03"
        infos = [
            SimpleNamespace(address=address) for address in (NETWORK, NODE, second)
        ]
        paths = {
            NETWORK: [
                scanner_path(bytes.fromhex(NETWORK.replace(":", "")) + b"\x0b", -65)
            ],
            NODE: [
                scanner_path(node_payload(), -70, "Living room"),
                scanner_path(node_payload(), -20, "Receive-only scanner", False),
                scanner_path(node_payload(), -57, "Meterboard"),
            ],
            second: [scanner_path(node_payload(3), -63, "SLZB passive")],
        }
        bluetooth = Mock()
        bluetooth.async_discovered_service_info.return_value = infos
        bluetooth.async_scanner_devices_by_address.side_effect = (
            lambda _, address, **kw: paths[address]
        )
        nodes = gateway_module(bluetooth)["async_get_gateways"](Mock(), NETWORK)
        self.assertEqual([node.address for node in nodes], [NODE, second, NETWORK])
        self.assertEqual(
            (nodes[0].unit_id, nodes[0].rssi, nodes[0].scanner_name),
            (2, -57, "Meterboard"),
        )
        self.assertEqual(nodes[2].unit_id, None)
        self.assertTrue(
            bluetooth.async_discovered_service_info.call_args.kwargs["connectable"]
        )
        self.assertTrue(
            all(
                call.kwargs["connectable"]
                for call in bluetooth.async_scanner_devices_by_address.call_args_list
            )
        )

    def test_other_networks_and_receive_only_devices_are_not_selectable(self):
        """A strong signal alone does not establish a usable GATT gateway."""
        bluetooth = Mock()
        bluetooth.async_discovered_service_info.return_value = [
            SimpleNamespace(address=NODE)
        ]
        for paths in (
            [],
            [scanner_path(node_payload(), -20, "Receive-only scanner", False)],
            [scanner_path(node_payload(network="66:55:44:33:22:11"))],
            [scanner_path(node_payload()[:22])],
        ):
            bluetooth.async_scanner_devices_by_address.return_value = paths
            self.assertEqual(
                gateway_module(bluetooth)["async_get_gateways"](Mock(), NETWORK), []
            )


class FlowBase:
    """Capture observable form and persistence calls at the HA boundary."""

    def __init_subclass__(cls, **_kwargs):
        """Accept the integration domain used by HA's config-flow registration."""
        super().__init_subclass__()

    def __init__(self):
        """Start a user-initiated flow."""
        self.context = {}
        self.source = "user"

    def async_show_form(self, **kwargs):
        """Return the form contract for assertions."""
        return {"type": "form", **kwargs}


class Select:
    """Expose selector options without importing HA's unrelated integrations."""

    def __init__(self, config):
        """Retain the selector's public configuration."""
        self.config = config

    def __call__(self, value):
        """Validate choices when Voluptuous applies the production form schema."""
        if value not in {option["value"] for option in self.config["options"]}:
            raise vol.Invalid("Invalid gateway")
        return value


def flow_instance():
    """Create the production flow with mocked HA persistence and Bluetooth APIs."""
    gateways = Mock(return_value=[])
    validation = AsyncMock(
        return_value={
            "title": "Synthetic network",
            "id": NETWORK,
            "unit_names": {2: "Window"},
        }
    )
    namespace = load_declarations(
        "config_flow.py",
        {"ConfigFlow"},
        {
            "config_entries": SimpleNamespace(
                ConfigFlow=FlowBase, SOURCE_RECONFIGURE="reconfigure"
            ),
            "CONF_ADDRESS": "address",
            "CONF_PASSWORD": "password",
            "CONF_GATEWAY_ADDRESS": "gateway_address",
            "DOMAIN": "casambi_bt",
            "USER_SCHEMA": vol.Schema({}),
            "REAUTH_SCHEMA": vol.Schema({}),
            "async_scanner_count": lambda *args, **kwargs: 1,
            "format_mac": lambda value: value,
            "async_get_gateways": gateways,
            "_validate_input": validation,
            "vol": vol,
            "_LOGGER": logging.getLogger(__name__),
            "selector": SimpleNamespace(
                SelectSelector=Select,
                SelectSelectorConfig=dict,
                SelectOptionDict=dict,
                SelectSelectorMode=SimpleNamespace(DROPDOWN="dropdown"),
            ),
        },
    )
    flow = namespace["ConfigFlow"]()
    flow.hass = SimpleNamespace(data={}, config_entries=Mock())
    flow.async_update_reload_and_abort = Mock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )
    flow._async_create_casa_entry = AsyncMock(return_value={"type": "create_entry"})
    flow.add_suggested_values_to_schema = lambda schema, data: schema
    return flow, gateways, validation


class GatewayFlowTest(unittest.IsolatedAsyncioTestCase):
    """Initial setup and existing entries share the same gateway selection."""

    async def test_initial_setup_selects_node_after_network_validation(self):
        """Store the selected node separately from the validated network address."""
        flow, gateways, validation = flow_instance()
        gateways.return_value = [
            SimpleNamespace(
                address=NODE, unit_id=2, rssi=-57, scanner_name="Meterboard"
            )
        ]
        data = {
            "address": NETWORK,
            "password": "synthetic-password",
            "import_groups": False,
        }
        form = await flow.async_step_user(data)
        self.assertEqual(form["step_id"], "gateway")
        selector = next(iter(form["data_schema"].schema.values()))
        self.assertIn(
            "#2 Window · -57 dBm · Meterboard", selector.config["options"][1]["label"]
        )
        self.assertEqual(form["data_schema"]({})["gateway_address"], NETWORK)
        result = await flow.async_step_gateway({"gateway_address": NODE})
        self.assertEqual(result["type"], "create_entry")
        validation.assert_awaited_once_with(flow.hass, data)
        flow._async_create_casa_entry.assert_awaited_once_with(
            "Synthetic network", NETWORK, {**data, "gateway_address": NODE}
        )

    async def test_existing_entry_changes_only_gateway_and_schedules_reload(self):
        """Existing passwords, identities and import settings are not replaced."""
        flow, gateways, validation = flow_instance()
        entry = SimpleNamespace(
            entry_id="existing",
            data={
                "address": NETWORK,
                "password": "synthetic-password",
                "import_groups": False,
            },
        )
        flow.source = "reconfigure"
        flow._get_reconfigure_entry = Mock(return_value=entry)
        flow.hass.data = {
            "casambi_bt": {
                "existing": SimpleNamespace(
                    casa=SimpleNamespace(
                        units=[SimpleNamespace(deviceId=2, name="Window")]
                    )
                )
            }
        }
        gateways.return_value = [
            SimpleNamespace(
                address=NODE, unit_id=2, rssi=-57, scanner_name="Meterboard"
            )
        ]
        form = await flow.async_step_reconfigure()
        self.assertEqual(form["data_schema"]({})["gateway_address"], NETWORK)
        await flow.async_step_gateway({"gateway_address": NODE})
        flow.async_update_reload_and_abort.assert_called_once_with(
            entry,
            data_updates={"gateway_address": NODE},
            reload_even_if_entry_is_unchanged=False,
        )
        validation.assert_not_awaited()
        self.assertEqual(entry.data["address"], NETWORK)

    async def test_unavailable_new_selection_is_rejected_and_saved_target_is_retained(
        self,
    ):
        """Do not silently switch away from a pinned node or accept stale choices."""
        flow, gateways, _ = flow_instance()
        flow.source = "reconfigure"
        flow._get_reconfigure_entry = Mock(
            return_value=SimpleNamespace(
                entry_id="existing", data={"address": NETWORK, "gateway_address": NODE}
            )
        )
        form = await flow.async_step_reconfigure()
        self.assertEqual(form["data_schema"]({})["gateway_address"], NODE)
        form = await flow.async_step_gateway({"gateway_address": "AA:BB:CC:DD:EE:99"})
        self.assertEqual(form["errors"], {"base": "gateway_unavailable"})
        flow.async_update_reload_and_abort.assert_not_called()
        await flow.async_step_gateway({"gateway_address": NETWORK})
        self.assertEqual(
            flow.async_update_reload_and_abort.call_args.kwargs["data_updates"],
            {"gateway_address": NETWORK},
        )

    async def test_reauth_validates_full_saved_network_and_gateway(self):
        """A password-only form must retain both connection addresses."""
        flow, _, validation = flow_instance()
        flow.entry = SimpleNamespace(
            entry_id="existing",
            data={
                "address": NETWORK,
                "gateway_address": NODE,
                "password": "synthetic-old",
            },
        )
        flow.hass.config_entries.async_reload = AsyncMock()
        flow.async_abort = Mock(return_value={"type": "abort"})
        await flow.async_step_reauth_confirm({"password": "synthetic-new"})
        validation.assert_awaited_once_with(
            flow.hass,
            {
                "address": NETWORK,
                "gateway_address": NODE,
                "password": "synthetic-new",
            },
        )


class NotReady(Exception):
    """Stand in for HA's retryable connection exception."""


class GatewayRuntimeTest(unittest.IsolatedAsyncioTestCase):
    """Connect and reconnect through the saved GATT target."""

    def make_api(self, gateway=NODE):
        """Bind the production API to synthetic connection and scanner clients."""
        bluetooth = Mock()
        casa = Mock(connected=True, rawNetworkData={"network": {"protocolVersion": 11}})
        casa.connect = AsyncMock()
        namespace = load_declarations(
            "__init__.py",
            {"CasambiApi"},
            {
                "asyncio": asyncio,
                "bluetooth": bluetooth,
                "callback": lambda func: func,
                "Casambi": Mock(return_value=casa),
                "get_async_client": Mock(),
                "get_cache_dir": Mock(),
                "CONF_GATEWAY_ADDRESS": "gateway_address",
                "DATA_NETWORK_EVENTS": "casambi_bt_network_events",
                "_LOGGER": logging.getLogger(__name__),
                "RECONNECT_BACKOFF_SECONDS": (3,),
                "ConfigEntryNotReady": NotReady,
                "NetworkNotFoundError": type("NetworkNotFoundError", (Exception,), {}),
                "BluetoothError": type("BluetoothError", (Exception,), {}),
                "AuthenticationError": type("AuthenticationError", (Exception,), {}),
            },
        )
        entry = SimpleNamespace(entry_id="existing", data={"gateway_address": gateway} if gateway else {})
        hass = Mock()
        hass.data = {"casambi_bt_network_events": Mock()}
        api = namespace["CasambiApi"](hass, entry, NETWORK, "synthetic-password")
        api._register_casambi_callbacks = Mock()
        return api, bluetooth

    async def test_connect_and_reconnect_keep_selected_node(self):
        """GATT lookup, library connection and advertisement callbacks use the pin."""
        api, bluetooth = self.make_api()
        device = bluetooth.async_ble_device_from_address.return_value
        await api.connect()
        api.casa.connect.assert_awaited_once_with(
            device, "synthetic-password", networkAddress=NETWORK
        )
        self.assertEqual(
            bluetooth.async_register_callback.call_args.args[2],
            {"address": NODE, "connectable": True},
        )
        api.casa.connected = False

        async def reconnect():
            api.casa.connected = True
            return True

        api.try_reconnect = AsyncMock(side_effect=reconnect)
        with patch("asyncio.sleep", new=AsyncMock()):
            await api._reconnect_loop()
        self.assertEqual(bluetooth.async_ble_device_from_address.call_count, 2)
        self.assertTrue(
            all(
                call.args[1] == NODE and call.kwargs["connectable"]
                for call in bluetooth.async_ble_device_from_address.call_args_list
            )
        )

    async def test_missing_pin_is_retryable_without_using_network_endpoint(self):
        """An unavailable pinned node must not cause an unrequested node change."""
        api, bluetooth = self.make_api()
        bluetooth.async_ble_device_from_address.return_value = None
        with self.assertRaisesRegex(NotReady, NODE):
            await api.connect()
        api.casa.connect.assert_not_awaited()

    async def test_old_entry_keeps_original_connection_address(self):
        """Entries without a pin retain their existing network-address behavior."""
        api, bluetooth = self.make_api(gateway=None)
        await api.connect()
        self.assertEqual(api.gateway_address, NETWORK)
        api.casa.connect.assert_awaited_once_with(
            bluetooth.async_ble_device_from_address.return_value,
            "synthetic-password",
            networkAddress=NETWORK,
        )


if __name__ == "__main__":
    unittest.main()

"""Exercise device-info properties without a running Home Assistant instance."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from typing import cast
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).parent / "custom_components" / "casambi_bt"
CLASSES = {
    "entities.py": ["CasambiUnitEntity"],
    "switch_sensor.py": ["CasambiSwitchSensor", "CasambiSwitchUnitIdSensor"],
    "switch_config_sensor.py": [
        "CasambiButtonActionSensor", "CasambiSwitchRawConfigSensor",
        "CasambiSwitchSettingsSensor",
    ],
}


def load_device_info(filename, class_name):
    """Load the production property body, isolating unrelated HA imports."""
    tree = ast.parse((ROOT / filename).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "device_info")
    method.decorator_list = []
    method.returns = None
    method.body = [n for n in method.body if not isinstance(n, ast.ImportFrom)]
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = {"DeviceInfo": dict, "DOMAIN": "casambi_bt", "cast": cast}
    exec(compile(module, str(ROOT / filename), "exec"), namespace)
    return namespace["device_info"]


class DeviceInfoTest(unittest.TestCase):
    """All child entities must preserve the registered network relationship."""

    def test_children_reference_registered_network_id(self):
        """Use registry IDs even when network identifiers match across entries."""
        unit = SimpleNamespace(
            uuid="unit-uuid", name="Switch", deviceId=23, firmwareVersion="42",
            unitType=SimpleNamespace(manufacturer="Casambi", model="Xpress"),
        )
        for filename, classes in CLASSES.items():
            for class_name in classes:
                for parent_id in ("registry-id-entry-a", "registry-id-entry-b"):
                    with self.subTest(entity=class_name, parent_id=parent_id):
                        entity = SimpleNamespace(
                            _api=SimpleNamespace(
                                casa=SimpleNamespace(networkId="same-network"),
                                network_device_id=parent_id,
                            ),
                            _obj=unit, _unit=unit,
                        )
                        info = load_device_info(filename, class_name)(entity)
                        self.assertEqual(info["via_device_id"], parent_id)
                        self.assertEqual(info["identifiers"], {("casambi_bt", "unit-uuid")})
                        self.assertEqual(info["name"], "Switch")


class PlatformSetupReached(Exception):
    """Stop setup after checking the platform handoff."""


class NetworkRegistrationTest(unittest.IsolatedAsyncioTestCase):
    """Verify the parent exists before any platform can register children."""

    async def test_parent_registration_precedes_platform_setup(self):
        """Register network metadata and pass its actual registry ID to entities."""
        tree = ast.parse((ROOT / "__init__.py").read_text())
        setup = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry")
        module = ast.Module(body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            setup,
        ], type_ignores=[])
        api = SimpleNamespace(
            connect=AsyncMock(), address="AA:BB:CC:DD:EE:FF",
            casa=SimpleNamespace(networkId="network-1", networkName="Living room"),
        )
        entry = SimpleNamespace(
            entry_id="entry-1", title="Casambi", unique_id="network-1",
            data={"address": api.address, "password": "synthetic-test-password"},
        )
        registry = Mock()
        registry.async_get_or_create.return_value = SimpleNamespace(id="registered-parent-id")
        dr = SimpleNamespace(async_get=Mock(return_value=registry), CONNECTION_BLUETOOTH="bluetooth")

        async def forward(actual_entry, platforms):
            self.assertIs(actual_entry, entry)
            self.assertEqual(platforms, ["light", "sensor"])
            self.assertEqual(api.network_device_id, "registered-parent-id")
            self.assertIs(hass.data["casambi_bt"][entry.entry_id], api)
            registry.async_get_or_create.assert_called_once_with(
                config_entry_id="entry-1",
                identifiers={("casambi_bt", "network-1")},
                connections={("bluetooth", api.address)},
                name="Living room", manufacturer="Casambi", model="Network",
            )
            raise PlatformSetupReached

        hass = SimpleNamespace(data={}, config_entries=SimpleNamespace(async_forward_entry_setups=forward))
        namespace = {
            "_LOGGER": Mock(), "DOMAIN": "casambi_bt", "CasambiApi": Mock(return_value=api),
            "CONF_ADDRESS": "address", "CONF_PASSWORD": "password",
            "device_registry": dr, "PLATFORMS": ["light", "sensor"],
        }
        exec(compile(ast.fix_missing_locations(module), str(ROOT / "__init__.py"), "exec"), namespace)
        with self.assertRaises(PlatformSetupReached):
            await namespace["async_setup_entry"](hass, entry)
        api.connect.assert_awaited_once()
        dr.async_get.assert_called_once_with(hass)


if __name__ == "__main__":
    unittest.main()

"""Exercise production network-event forwarding without a running HA instance."""

import ast
import contextlib
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


def load_api_methods():
    """Use the existing AST-isolation test pattern for HA-dependent methods."""
    path = Path(__file__).parent / "custom_components/casambi_bt/__init__.py"
    tree = ast.parse(path.read_text())
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "CasambiApi"
    )
    methods = [
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("_network_event_handler", "_register_casambi_callbacks")
    ]
    for method in methods:
        method.decorator_list = []
    isolated = ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[]))
    namespace = {
        "contextlib": contextlib,
        "DOMAIN": "casambi_bt",
        "_LOGGER": logging.getLogger(__name__),
    }
    exec(compile(isolated, str(path), "exec"), namespace)  # noqa: S102
    return namespace


class NetworkEventsTest(unittest.TestCase):
    """Check the event contract and callback lifecycle that HA observes."""

    def test_event_preserves_protocol_fields_and_adds_entry_id(self):
        """Route input and state rows to the network event bus with config identity."""
        method = load_api_methods()["_network_event_handler"]
        api = SimpleNamespace(
            hass=SimpleNamespace(bus=Mock()),
            conf_entry=SimpleNamespace(entry_id="network-entry"),
            _events_manager=Mock(),
        )
        for event in (
            {
                "type": "input",
                "source_stream": "notify_input",
                "unit": 32,
                "origin_unit_id": 2,
                "input_code": 2,
            },
            {"type": "presence", "numeric_value": 1, "unit": 7},
        ):
            method(api, event)
            api.hass.bus.async_fire.assert_called_with(
                "casambi_bt_network_event", {**event, "entry_id": "network-entry"}
            )

    def test_reconnect_registers_exactly_one_network_callback(self):
        """Repeated registration replaces the existing handler instead of duplicating it."""
        callbacks = []
        casa = Mock()
        casa.registerNetworkEventHandler.side_effect = callbacks.append
        casa.unregisterNetworkEventHandler.side_effect = callbacks.remove
        handler = Mock()
        api = SimpleNamespace(
            casa=casa,
            _casa_disconnect=Mock(),
            _unit_changed_handler=Mock(),
            _switch_event_handler=Mock(),
            _network_event_handler=handler,
            _receive_diagnostic_handler=Mock(),
        )
        method = load_api_methods()["_register_casambi_callbacks"]
        method(api)
        method(api)
        assert callbacks == [handler]


if __name__ == "__main__":
    unittest.main()

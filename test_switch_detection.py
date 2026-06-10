"""Tests for Casambi switch/button unit detection."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


def _load_switch_detection():
    path = (
        Path(__file__).parent
        / "custom_components"
        / "casambi_bt"
        / "switch_detection.py"
    )
    spec = importlib.util.spec_from_file_location("switch_detection", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


switch_detection = _load_switch_detection()


def _unit(mode: str, model: str, manufacturer: str = "Casambi"):
    return SimpleNamespace(
        unitType=SimpleNamespace(
            mode=mode,
            model=model,
            manufacturer=manufacturer,
        )
    )


class SwitchDetectionTest(unittest.TestCase):
    def test_live_pushbutton_and_switch_modes_are_switches(self) -> None:
        self.assertTrue(
            switch_detection.is_switch_unit(
                _unit("PushButton", "SC-TI-CAS", "Scemtec Hard & Software GmbH")
            )
        )
        self.assertTrue(
            switch_detection.is_switch_unit(_unit("Switch", "4CHANNEL_SW EVO", "LEDsGO"))
        )

    def test_sensor_mode_is_not_switch(self) -> None:
        self.assertFalse(switch_detection.is_switch_unit(_unit("Sensor", "BT repeater")))

    def test_keyword_models_still_work(self) -> None:
        self.assertTrue(switch_detection.is_switch_unit(_unit("UNKNOWN", "Xpress Switch")))
        self.assertTrue(switch_detection.is_switch_unit(_unit("Kinetic", "PTM215B")))


if __name__ == "__main__":
    unittest.main()

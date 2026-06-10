"""Helpers for identifying Casambi switch/button units."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from CasambiBt import Unit


SWITCH_MODES: Final[set[str]] = {
    "PushButton",
    "Switch",
}

SWITCH_MODEL_KEYWORDS: Final[set[str]] = {
    "switch",
    "xpress",
    "button",
    "pushbutton",
    "batteryswitch",
    "wall switch",
    "remote",
}


def is_switch_unit(unit: "Unit") -> bool:
    """Return True if a unit is a physical switch/button controller."""
    mode = unit.unitType.mode
    if "Kinetic" in mode:
        return True
    if mode in SWITCH_MODES:
        return True
    if mode == "Sensor":
        return False

    model_lower = unit.unitType.model.lower()
    if any(keyword in model_lower for keyword in SWITCH_MODEL_KEYWORDS):
        return True

    manufacturer_lower = unit.unitType.manufacturer.lower()
    if "switch" in manufacturer_lower:
        return True

    return False

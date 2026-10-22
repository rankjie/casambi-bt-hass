"""Battery and thermal diagnostics from observed fixture state fields."""

from __future__ import annotations

import math
from typing import cast

from CasambiBt import Unit

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CasambiApi
from .const import DOMAIN
from .entities import CasambiUnitEntity

THERMAL_STATES = {0: "normal", 1: "was_overheated", 2: "overheated"}
_BATTERY_CURVE = (100, 96, 88, 79, 68, 57, 46, 35, 24, 12, 1)
DESCRIPTIONS = {
    "battery": SensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "overheat": SensorEntityDescription(
        key="thermal_status",
        translation_key="thermal_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(THERMAL_STATES.values()),
        icon="mdi:thermometer-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}


def battery_percentage(raw: int) -> int | None:
    """Match Android 3.21 mf3.C2's percentage/encoded-level conversion.

    Zero has no battery reading. Values 1..100 are already percentages; larger
    values use the app's clamped 169..203 lookup curve, not raw/255 scaling.
    """
    if raw < 0:
        raise ValueError("Battery level cannot be negative")
    if raw == 0:
        return None
    if raw <= 100:
        return raw
    encoded = min(203, max(169, raw))
    index = math.floor((203 - encoded) / 34 * 10 + 0.5)
    return _BATTERY_CURVE[index]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create diagnostics only for controls declared by the fixture profile."""
    api: CasambiApi = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    for unit in api.casa.units:
        profile = unit.unitType.eventProfile
        if profile is None:
            raise ValueError(f"Fixture {unit.unitType.id} has no event profile")
        for index, control in enumerate(profile["controls"]):
            if control["type"] in DESCRIPTIONS and control["length"]:
                entities.append(
                    CasambiDiagnosticSensor(api, unit, control["type"], index)
                )
    async_add_entities(entities)


class CasambiDiagnosticSensor(CasambiUnitEntity, SensorEntity):
    """Expose an actually received field, independently of default-packed state."""

    def __init__(
        self, api: CasambiApi, unit: Unit, kind: str, control_index: int
    ) -> None:
        """Keep each profile control associated with its existing HA device."""
        super().__init__(api, DESCRIPTIONS[kind], unit)
        self._kind = kind
        self._control_index = control_index

    @property
    def unique_id(self) -> str:
        """Identify separate controls without depending on editable names."""
        unit = cast("Unit", self._obj)
        return (
            f"{self._api.casa.networkId}-unit-{unit.uuid}"
            f"-diagnostic-{self._kind}-{self._control_index}"
        )

    @property
    def available(self) -> bool:
        """Keep a sleeping battery switch's last reading available."""
        if self._kind == "battery":
            return self._api.assumed_available
        return super().available

    @property
    def _raw_value(self) -> int | None:
        unit = cast("Unit", self._obj)
        return self._api.unit_diagnostic_values.get(
            (unit.deviceId, self._kind, self._control_index)
        )

    @property
    def native_value(self) -> int | str | None:
        """Retain the distinction between past and active thermal protection."""
        raw = self._raw_value
        if raw is None:
            return None
        if self._kind == "battery":
            return battery_percentage(raw)
        # The fourth two-bit code is reserved; never report it as healthy.
        return THERMAL_STATES.get(raw)

    @property
    def extra_state_attributes(self) -> dict:
        """Retain the wire value for inspection without exposing state buffers."""
        unit = cast("Unit", self._obj)
        return {
            "unit_id": unit.deviceId,
            "control_index": self._control_index,
            "raw_value": self._raw_value,
        }

"""Find same-network GATT nodes using Casambi advertisements."""

from dataclasses import dataclass

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

CASAMBI_MANUFACTURER_ID = 963


@dataclass(frozen=True, slots=True)
class Gateway:
    """A reachable GATT address and its strongest connectable receiver."""

    address: str
    unit_id: int | None
    rssi: int
    scanner_name: str


def gateway_unit_id(payload: bytes, network_id: bytes) -> int | None:
    """Read an EVO node's network and unit ID as in the official app's ip.s."""
    # The official long-advertisement branch consumes 23 bytes. Its first six
    # bytes identify the unit, not the Bluetooth address used for GATT.
    if (
        len(payload) >= 23
        and payload[12:18] == network_id
        and payload[18] != 0
        and (payload[19] & 31) >= 10
    ):
        return payload[18]
    return None


@callback
def async_get_gateways(hass: HomeAssistant, network_address: str) -> list[Gateway]:
    """List this network's nodes using only HA's GATT-capable scanners."""
    network_id = bytes.fromhex(network_address.replace(":", ""))
    gateways = []
    for info in bluetooth.async_discovered_service_info(hass, connectable=True):
        address = info.address.upper()
        paths = bluetooth.async_scanner_devices_by_address(
            hass, info.address, connectable=True
        )
        candidates = []
        for path in paths:
            if not path.scanner.connectable:
                continue
            payload = path.advertisement.manufacturer_data.get(CASAMBI_MANUFACTURER_ID)
            if payload is None:
                continue
            unit_id = gateway_unit_id(payload, network_id)
            is_network = (
                address == network_address.upper()
                and 7 <= len(payload) < 22
                and payload[:6] == network_id
            )
            if is_network or unit_id is not None:
                candidates.append(
                    Gateway(
                        address, unit_id, path.advertisement.rssi, path.scanner.name
                    )
                )
        if candidates:
            gateways.append(max(candidates, key=lambda node: node.rssi))
    return sorted(gateways, key=lambda node: (-node.rssi, node.address))

"""Constants for the Casambi Bluetooth integration."""

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "casambi_bt"

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.COVER, Platform.LIGHT, Platform.SCENE, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

CONF_IMPORT_GROUPS: Final = "import_groups"
CONF_GATEWAY_ADDRESS: Final = "gateway_address"
CONF_BACKUP: Final = "backup"

# The network starts from its cached configuration; the cloud is only checked
# for changes in the background at this interval.
NETWORK_REFRESH_INTERVAL: Final = timedelta(hours=24)

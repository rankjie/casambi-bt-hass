"""Backup files that set a network up again on a fresh Home Assistant.

A file holds the settings of the config entry and the casambi-bt offline backup
(network configuration with its keys, unit type fixtures). Importing it needs
neither the Casambi cloud nor a Bluetooth connection. The file contains the
keys and the password of the network; treat it like a password.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from CasambiBt import Casambi

from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .const import CONF_GATEWAY_ADDRESS, CONF_IMPORT_GROUPS

if TYPE_CHECKING:
    from . import CasambiApi

BACKUP_FORMAT: Final = "casambi-bt-hass-backup"
BACKUP_VERSION: Final = 1
ENTRY_KEYS: Final = (
    CONF_ADDRESS,
    CONF_PASSWORD,
    CONF_IMPORT_GROUPS,
    CONF_GATEWAY_ADDRESS,
)


class InvalidBackupError(ValueError):
    """The file isn't a backup of this integration."""


async def async_create_backup(api: CasambiApi) -> dict[str, Any]:
    """Return the backup of a loaded network.

    :raises CasambiBtError: The network configuration isn't complete in the cache.
    """
    entry = api.conf_entry
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created": datetime.now(UTC).isoformat(),
        "title": entry.title,
        "entry": {k: entry.data[k] for k in ENTRY_KEYS if k in entry.data},
        "library": await api.casa.exportOfflineBackup(),
    }


async def async_restore_backup(
    hass: HomeAssistant, backup: Any, cache_dir: Any
) -> tuple[str, dict[str, Any]]:
    """Write the network of a backup into the cache.

    :return: The title and the config entry data of the network.
    :raises InvalidBackupError: The file isn't a backup of this integration.
    :raises OfflineBackupError: The network part of the backup is invalid.
    """
    if (
        not isinstance(backup, dict)
        or backup.get("format") != BACKUP_FORMAT
        or backup.get("version") != BACKUP_VERSION
        or not isinstance(backup.get("entry"), dict)
        or not isinstance(backup.get("title"), str)
    ):
        raise InvalidBackupError("Not a Casambi Bluetooth backup")
    data = {k: backup["entry"][k] for k in ENTRY_KEYS if k in backup["entry"]}
    if not isinstance(data.get(CONF_ADDRESS), str) or not isinstance(
        data.get(CONF_PASSWORD), str
    ):
        raise InvalidBackupError("The backup lacks the network address")

    library = backup.get("library")
    if not isinstance(library, dict) or library.get("address") != data[CONF_ADDRESS]:
        # Checked before writing, so a mismatched file leaves the cache alone.
        raise InvalidBackupError("The entry and the network of the backup differ")
    await Casambi(get_async_client(hass), cache_dir).importOfflineBackup(library)
    return backup["title"], data

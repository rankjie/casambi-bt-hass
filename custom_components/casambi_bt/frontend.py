"""Register the integration's self-contained HA panel and versioned assets."""

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

PANEL_PATH = "casambi-events"


async def async_register(hass: HomeAssistant, version: str) -> None:
    """Use HA's navigation, authentication and theme instead of a second server."""
    asset_path = f"/casambi_bt/frontend/{version}"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(asset_path, str(Path(__file__).with_name("frontend")), True)]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="casambi-events-panel",
        sidebar_title="Casambi",
        sidebar_icon="mdi:timeline-text",
        module_url=f"{asset_path}/casambi-events.js",
        require_admin=True,
        config_panel_domain="casambi_bt",
    )

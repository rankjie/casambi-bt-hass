# Casambi Bluetooth Revamped

[![Discord](https://img.shields.io/discord/1186445089317326888)](https://discord.gg/jgZVugfx)

An enhanced fork of the [original Casambi Bluetooth integration](https://github.com/lkempf/casambi-bt-hass) by [@lkempf](https://github.com/lkempf), with additional features for better switch and relay support.

> ⚠️ **DEVELOPMENT WARNING**: This repository is used as a development environment. Things might break at any moment. It's recommended to wait at least 1 day after a new release before updating to ensure stability. All stable changes will be merged back to the original repository.
> 
> **When to use this fork**: Use this version if you need Classic firmware support, want to use Casambi switches in Home Assistant (usable but still being improved), or need relay support. Otherwise, stick with the original integration.

## What's Enhanced

- **Classic protocol support** - Lighting fixtures on Classic (legacy) Casambi firmware networks: on/off, dimming, and live state sync from the Casambi app. More testers welcome!
- **Switch event support** - Physical switch button press/hold/release events (wired + wireless)
- **Automation blueprints** - Ready-to-use blueprints for button automations
- **Fixed relay status** - Properly reports the status of relay units (also merged to the original integration)
- **Based on casambi-bt-revamped** - Uses an enhanced version of the underlying library (protocol-level INVOCATION parsing)

## Quick Start

### Installation

#### HACS (Recommended)
1. Add this repository as a custom repository in HACS
2. Search for "Casambi Bluetooth Revamped" and install
3. Restart Home Assistant

#### Manual
1. Copy the `custom_components/casambi_bt` folder to your `config/custom_components/`
2. Restart Home Assistant

### Configuration
1. Go to Settings → Devices & Services → Add Integration
2. Search for "Casambi Bluetooth"
3. Enter your network password from the Casambi app
4. Choose the network address or an individual EVO node as the GATT connection target

### Connection node

For an existing network, open Settings → Devices & Services → Casambi Bluetooth,
then use the entry's menu → Reconfigure. The list shows node names and IDs,
Bluetooth addresses, and the strongest RSSI reported by a GATT-capable receiver.
Scanners without GATT connection capability are excluded. Readings are a snapshot when
the form is opened; Home Assistant still chooses the Bluetooth receiver used
for the connection.

Selecting the network address retains Casambi's network-level connection behavior.
Selecting an individual node pins the GATT target, including after reconnects.
Saving reloads only that config entry; the network identity, entities, password
and cache address are preserved. If a pinned node goes out of range, HA retries
that node until it returns or you change the selection. An existing saved target
without current reception remains selectable, with no RSSI shown.

The integration requires Home Assistant 2026.9 or newer and
`casambi-bt-revamped==0.4.2`, which provides
`Casambi.connect(..., networkAddress=...)`. Install the matching library and
integration builds together.

## Features

### Battery and thermal diagnostics

Devices whose fixture profile declares `battery` or `overheat` controls gain
diagnostic sensors on their existing HA device. Battery uses HA's battery class,
percentage unit and measurement statistics. It follows Android 3.21.0 `mf3.C2`:
values 1–100 are percentages; larger values use the app's 169–203 lookup curve.
Zero means no reading, so it is shown as unknown. The received wire value remains
in the `raw_value` attribute. Sleeping battery switches retain their last reading.

Thermal status is an enum: `normal` (0), `was_overheated` (1) or `overheated` (2),
matching Android `r73` / `ud3.z1`. A past thermal event is distinct from active
overheating; the reserved code 3 is unknown and produces a warning. Entity names
and enum labels follow HA's English, German, Dutch or Simplified Chinese locale.
Only actually received fields supply readings; profile defaults and unreceived
parts of a partial state do not become sensor values. After reload, diagnostics
remain unknown until a new report arrives. No extra GATT connection is opened.

### 📱 Switch Button Events
Physical switches fire events for automations:
- Button press, hold, and release detection
- Hold/release-after-hold are emitted when the device/firmware sends them (no timer-based synthesis)
- Support for short/long press actions

[**→ Detailed Switch Event Documentation**](docs/SWITCH_EVENTS.md)

### Network Events

With a library build providing `registerNetworkEventHandler`, the integration fires
`casambi_bt_network_event` with `entry_id` and the library's event fields. Listen
for it in Developer Tools → Events. `source="unit_state"` reports fixture-control
changes; `source="invocation"` preserves received type 7 frames, with
`source_stream="button_event"` or `"notify_input"` for switch observations.
Raw protocol indices are retained and reports from the two sources are not merged
into one physical click. Existing `casambi_bt_switch_event` automations keep their
semantic API.

The **Casambi** sidebar panel (`/casambi-events`, administrator accounts) shows
these observations over HA's authenticated WebSocket connection. Switch rows
include the unit ID, button label and press/release action. Select a row for
decoded fields and JSON; new events and reconnects keep the inspector open.
Click `Unit #N` to open the corresponding HA device. The inspector also lists its
current registered entities, with enabled entities opening HA's native details.

Capture continues while the panel is closed or display is paused. The dedicated
SQLite archive survives HA restarts and has no automatic row-count or age cutoff.
Search, filters, history paging and JSONL export cover the complete saved archive;
the 250-row resident page is only a display bound. BLE, HA connection and archive
failures have separate status. The panel shares the integration's existing GATT
client and does not require the Mac demo server.

Install the matching library/integration builds together and restart HA to
register the panel. See the [viewer contract and installation notes](docs/NETWORK_EVENTS_VIEWER_DESIGN.md)
for button-label provenance, storage behavior, API details and validation limits.

### 🎯 Automation Blueprints
Import ready-to-use blueprints with one click:

[![Toggle and Dim](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Frankjie%2Fcasambi-bt-hass%2Fmain%2Fblueprints%2Fautomation%2Fcasambi_bt%2Fbutton_toggle_and_dim.yaml) **Toggle and Dim** - All-in-one light control (short press = toggle, hold = dim)

[![Button Actions](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Frankjie%2Fcasambi-bt-hass%2Fmain%2Fblueprints%2Fautomation%2Fcasambi_bt%2Fbutton_short_long_press.yaml) **Button Actions** - Versatile automation for any button event

[![Cover Control](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Frankjie%2Fcasambi-bt-hass%2Fmain%2Fblueprints%2Fautomation%2Fcasambi_bt%2Fbutton_cover_control.yaml) **Cover Control** - Smart blind/cover control (press = open/close/stop, hold = continuous)

[**→ Blueprint Documentation & Examples**](docs/BLUEPRINTS.md)

### 💡 Supported Devices
- Lights (dimmer, color, temperature, on/off)
- Light groups
- Scenes
- Switches (as events, not entities)
- Relays

Classic (legacy) firmware notes:
- Discovery includes both EVO (`FE4D`) and Classic (`CA5A`) advertisements.
- On/off, dimming, and bidirectional state sync are working for lighting fixtures.
- Changes made in the Casambi app are reflected in HA in real time.
- More testers welcome — if you have a Classic network, please [open an issue](https://github.com/rankjie/casambi-bt-hass/issues) with your experience.

## Network Setup

**Important**: Your Casambi network must be configured correctly:
1. Enable "Bluetooth control" in the Casambi app
2. Set a network password
3. See the [original setup guide](https://github.com/lkempf/casambi-bt#casambi-network-setup) for details

## Troubleshooting

Enable debug logging in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    CasambiBt: debug
    custom_components.casambi_bt: debug
```

For issues, please include:
- Debug logs (sanitize sensitive data)
- Your network configuration
- Device types you're trying to control

## Credits

This integration is based on the excellent work by [@lkempf](https://github.com/lkempf):
- Original integration: [casambi-bt-hass](https://github.com/lkempf/casambi-bt-hass)
- Original library: [casambi-bt](https://github.com/lkempf/casambi-bt)

## Development

For development setup and contribution guidelines, see the [original repository](https://github.com/lkempf/casambi-bt-hass#development).

## License

This project maintains the same license as the original work.

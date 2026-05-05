# Lutron Fader

A Home Assistant custom integration that adds extended fade time support to Lutron lights via direct Telnet communication using the Lutron Integration Protocol (LIP).

## Why This Integration?

The standard Lutron Caseta integration provides excellent support for features exposed through the Lutron Caseta app. However, owners of professional-grade Lutron hardware have access to powerful extended features that aren't typically exposed to users. These systems expose the **Lutron Integration Protocol (LIP)** over a direct Telnet connection — an openly documented, line-based text protocol that gives you full zone control including hardware-native fade times.

**Supported systems (per Lutron ICD 040249):**

| System | Integration Access Point | Telnet Port |
|--------|--------------------------|-------------|
| Caseta Pro Smart Bridge ⁺ | L-BDGPRO2-WH | 23 |
| RadioRA 2 | Main Repeater (RR-MAIN-REP-WH / RRK-MAIN-REP-WH) | Configurable in software |
| HomeWorks QS | HomeWorks QS Processor | — |
| Quantum | QSE-CI-NWK-E | 23 |
| Athena | QSE-CI-NWK-E | 23 |
| QS Standalone | QSE-CI-NWK-E | 23 |
| myRoom Plus | GCU-HOSP Processor | — |

> ⁺ Caseta Pro (L-BDGPRO2-WH) supports Telnet and the LIP command set in practice, but is not documented in Lutron ICD 040249 — use at your own discretion. Standard non-Pro Caseta (L-BDG2-WH) does **not** support LIP.

### The Power of Native Dimming

Smart dimming products like the Lamp Dimming Smart Plug (PD-3PCL-WH), Smart Dimmer Switch (PD-5NE), and Diva Smart Dimmer Switch (DVRF-6L) support hardware-level dimming. When you leverage this native capability, fades are smoother, more reliable, and far more elegant than software-based solutions that repeatedly send brightness commands.

Previously, accessing these native fade capabilities required manually telnetting into the system or running command-line scripts—not exactly user-friendly!

### What This Integration Does

Lutron Fader brings these professional features directly into Home Assistant's ecosystem, making them as easy to use as any other automation:

- **Select any Lutron light**
- **Specify your desired brightness level** (0-100%)
- **Set how long the fade should take** (seconds to hours)
- **Press a button** and watch as your lights smoothly transition over the exact duration you specified

All of this happens through a single service call—no manual dimming, no multiple commands, just smooth, hardware-accelerated fading that works exactly as you'd expect from professional lighting control systems.

## Features

- 🌅 **Long fade times** - Fade lights over minutes or hours (not limited by standard HA transition times)
- 🔌 **Direct Telnet control** - Bypasses standard integration limits using Lutron Integration Protocol (LIP)
- 🎛️ **Custom service** - `lutron_fader.fade_to` with extended fade time support
- 💡 **Standard HA light control** - `light.turn_on` / `light.turn_off` with `transition:` works natively
- 📡 **Real-time push updates** - Persistent connection with background reader; Pico button presses and app changes update HA state instantly without polling
- 📊 **Live brightness tracking** - HA brightness attribute updates every second during an active fade so dashboards and automations see the actual dimmer position
- 🔄 **Connection management** - Persistent keep-alive ping with automatic reconnect on drop

## Requirements

- Home Assistant 2023.1 or newer
- A Lutron system that supports LIP over Telnet: Caseta Pro Smart Bridge (L-BDGPRO2-WH), RadioRA 2 Main Repeater, HomeWorks QS Processor, Quantum, Athena, QS Standalone, or myRoom Plus
- Telnet/LIP integration enabled on the hub

## Installation

### Via HACS (Coming Soon)
1. Open HACS
2. Go to Integrations
3. Search for "Lutron Fader"
4. Click Install

### Manual Installation
1. Download the latest release from GitHub
2. Copy the `custom_components/lutron_fader` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

### Option 1: UI Configuration (Recommended)
1. Go to Settings > Devices & Services
2. Click "+ Add Integration"
3. Search for "Lutron Fader"
4. Enter your Lutron hub details:
   - **Host**: Your Caseta Pro hub IP address (e.g., `10.0.1.111`)
   - **Port**: Default is `23`
   - **Username**: Default is `lutron`
   - **Password**: Default is `integration`

### Option 2: YAML Configuration
Add to your `configuration.yaml`:
```yaml
lutron_fader:
  host: 10.0.1.111  # Your Caseta Pro hub IP address
  port: 23          # Default Telnet port
  username: lutron  # Default username
  password: integration  # Default password
```

Then restart Home Assistant.

## Finding Your Zone IDs

To find the zone ID for your lights:

1. Enable Telnet on your Lutron hub (Lutron App > Settings > Advanced > Integration)
2. Use the Lutron app to view your Integration Report:
   - Go to Settings > Advanced > Integration
   - Tap "Send Integration Report"
   - Copy to clipboard or email to yourself
3. Zone IDs are listed in the report under "Zones"

## Custom Lovelace Card

This integration includes a custom Lovelace card for easy control of your Lutron lights with fade times.

### Installing the Card

1. The card is automatically included with the integration
2. Go to **Settings → Dashboards → Resources** (☰ menu → Resources)
3. Click **"+ Add Resource"**
4. Enter:
   - URL: `/lutron_fader_static/lutron-fader-card.js`
   - Resource type: **JavaScript Module**
5. Click "Create"
6. Refresh your browser (Ctrl+F5 or Cmd+Shift+R)

### Using the Card

Add to your dashboard in YAML mode:

```yaml
type: custom:lutron-fader-card
entity: light.living_room_floor_lamp
```

Or use the visual editor:
1. Edit your dashboard
2. Click "+ Add Card"
3. Search for "Lutron Fader Card"
4. Select your entity

### Card Features

- **Current State Display**: Shows ON/OFF status and current brightness
- **Brightness Slider**: Select desired brightness (0-100%)
- **Fade Time Input**: Enter fade duration (0-14400 seconds)
- **Start Fade Button**: Execute the fade to selected brightness
- **Turn Off Button**: Turn off light with specified fade time
- **Input Validation**: Ensures fade time is within valid range

### Dashboard Examples

For complete dashboard configuration examples, see the [examples/](examples/) folder:
- Single and multiple card layouts
- Grid and vertical stack arrangements
- Auto-entities configurations
- Full page dashboard templates

## Usage

### Standard HA Light Control (Recommended)

Lutron Fader entities appear as standard HA lights and support the `transition` parameter natively:

```yaml
service: light.turn_off
target:
  entity_id: light.lutron_zone_5
data:
  transition: 1800  # 30 minutes
```

```yaml
service: light.turn_on
target:
  entity_id: light.lutron_zone_5
data:
  brightness: 255
  transition: 900  # 15 minutes
```

HA brightness updates every second during the fade so dashboards stay in sync.

### Service: `lutron_fader.fade_to`

Fade a light to a specific brightness over time. Supports fade times from 0 to 14400 seconds (4 hours):

```yaml
service: lutron_fader.fade_to
data:
  zone_id: 28
  brightness: 50    # 0-100%
  fade_time: 1800   # 30 minutes in seconds
```

You can also use entity_id instead of zone_id (requires running `auto_configure_from_report` first):

```yaml
service: lutron_fader.fade_to
data:
  entity_id: light.master_bedroom_ron_lamp
  brightness: 0     # Turn off
  fade_time: 3600   # 1 hour (max is 14400 = 4 hours)
```

## Example Automations

### Sunrise Simulation
Wake up gently with a 30-minute sunrise:
```yaml
automation:
  - alias: "Wake Up - Sunrise Simulation"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - service: lutron_fader.fade_to
        data:
          zone_id: 28
          brightness: 100
          fade_time: 1800  # 30 minutes
```

### Sunset Simulation
Gradually dim lights for bedtime:
```yaml
automation:
  - alias: "Bedtime - Sunset Simulation"
    trigger:
      - platform: time
        at: "21:30:00"
    action:
      - service: lutron_fader.fade_to
        data:
          zone_id: 28
          brightness: 0
          fade_time: 1800  # 30 minutes
```

### Multiple Lights Simultaneously
Fade multiple lights at the same time:
```yaml
automation:
  - alias: "Bedroom Lights - Fade Off"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: lutron_fader.fade_to
        data:
          zone_id: 25
          brightness: 0
          fade_time: 900  # 15 minutes
      - service: lutron_fader.fade_to
        data:
          zone_id: 34
          brightness: 0
          fade_time: 900  # 15 minutes
```

### Button to Trigger Fade
Create a script and button for one-touch fading:
```yaml
script:
  bedroom_sleep_mode:
    alias: "Bedroom Sleep Mode"
    sequence:
      - service: lutron_fader.fade_to
        data:
          zone_id: 25
          brightness: 0
          fade_time: 900
      - service: lutron_fader.fade_to
        data:
          zone_id: 34
          brightness: 0
          fade_time: 900
```

Then add a button card to your dashboard:
```yaml
type: button
name: Sleep Mode
icon: mdi:sleep
tap_action:
  action: call-service
  service: script.turn_on
  target:
    entity_id: script.bedroom_sleep_mode
```

## Known Limitations

- Requires a Lutron system with LIP/Telnet support — see the supported systems table in the Why This Integration? section
- Standard Caseta bridge (L-BDG2-WH) is **not supported** — does not expose LIP over Telnet
- Zone IDs must be manually configured (auto-discovery coming soon)
- Shades do not support extended fade times (they move at fixed motor speed)

## Troubleshooting

### Integration doesn't appear after installation
1. Verify files are in `/config/custom_components/lutron_fader/`
2. Check Home Assistant logs for errors (Settings > System > Logs)
3. Restart Home Assistant

### Connection fails
1. Verify Telnet is enabled on your Lutron hub (Lutron App > Settings > Advanced > Integration)
2. Confirm the IP address is correct
3. Test Telnet connection: `telnet <hub_ip> 23`
4. Ensure hub is on the same network as Home Assistant

### Services don't appear
1. Check Home Assistant logs for errors during startup
2. Verify `services.yaml` is present in the integration folder
3. Try reloading "Groups, group entities, and notify services" in Developer Tools > YAML

## Development

This integration is under active development. Contributions are welcome!

### Implemented
- Config flow (connection credentials via UI)
- Automatic light discovery (via `auto_configure_from_report` service)
- Custom Lovelace card with fade controls
- Persistent Telnet connection with background reader loop
- Real-time push state updates (Pico/app changes reflected instantly)
- Live brightness interpolation during active fades
- Standard `light.turn_on/off` with `transition:` support
- Hardware fade via correct LIP `HH:MM:SS` time format
- Unit tests (89 passing)

### To-Do
- [ ] GUI setup — zone discovery integrated into config flow
- [ ] HACS integration
- [ ] Multi-zone fade service

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the Apache 2.0 License - see the LICENSE file for details.

## Credits

Created by [rblancarte](https://github.com/rblancarte)

Built with inspiration from the Home Assistant community and the Lutron Integration Protocol documentation.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Lutron Electronics Co., Inc.
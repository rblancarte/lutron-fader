# Lutron Fader

A Home Assistant custom integration that adds extended fade time support to Lutron Caseta lights via direct Telnet communication.

## Why This Integration?

The standard Lutron Caseta integration provides excellent support for features exposed through the Lutron Caseta app. However, owners of professional-grade hardware—including the Smart Bridge Pro (L-BDGPRO2-WH), RadioRA 2 Main Repeater (RR-SEL-REP2-BL), and HomeWorks QS/QSX Processors—have access to powerful extended features that aren't typically exposed to users.

These advanced capabilities are accessible through two protocols:
- **Lutron Integration Protocol (LIP)** - Openly available and documented
- **Lutron Extensible Application Protocol (LEAP)** - Available only to professional integrators

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
- 🎛️ **Custom services** - `lutron_fader.fade_to` and `lutron_fader.long_fade`
- 🔄 **Connection management** - Intelligent connection pooling with automatic keep-alive

## Requirements

- Home Assistant 2023.1 or newer
- Lutron Caseta Pro Smart Bridge (L-BDGPRO2-WH), RadioRA 2 Select (RR-SEL-REP2-BL), or HomeWorks QS/QSX Processor
- Telnet integration enabled on your Lutron hub

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
- **Fade Time Input**: Enter fade duration (0-3600 seconds)
- **Start Fade Button**: Execute the fade to selected brightness
- **Turn Off Button**: Turn off light with specified fade time
- **Input Validation**: Ensures fade time is within valid range

## Usage

### Service: `lutron_fader.fade_to`

Fade a light to a specific brightness over time:
```yaml
service: lutron_fader.fade_to
data:
  zone_id: 28
  brightness: 50    # 0-100%
  fade_time: 1800   # 30 minutes in seconds
```

### Service: `lutron_fader.long_fade`

Same as `fade_to` but with explicit duration parameter (defaults to 30 minutes if not specified):
```yaml
service: lutron_fader.long_fade
data:
  zone_id: 28
  brightness: 0     # Turn off
  duration: 3600    # 1 hour
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

- Only works with Caseta Pro, RadioRA 2 Select, or HomeWorks QS/QSX (requires Telnet/LIP support)
- Standard Caseta bridge (non-Pro model L-BDG2-WH) is **not supported**
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

### To-Do List
- [x] GUI setup / Config Flow
- [x] Automatic light discovery
- [x] Custom Lovelace card with fade controls
- [ ] HACS integration
- [ ] Multi-zone fade service
- [ ] Fade cancellation
- [ ] Better error handling and notifications

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the Apache 2.0 License - see the LICENSE file for details.

## Credits

Created by [rblancarte](https://github.com/rblancarte)

Built with inspiration from the Home Assistant community and the Lutron Integration Protocol documentation.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Lutron Electronics Co., Inc.
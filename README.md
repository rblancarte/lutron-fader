# Lutron Fader

A Home Assistant custom integration that adds extended fade time support to Lutron Caseta lights via direct Telnet communication.

## Features

- 🌅 **Long fade times** - Fade lights over minutes or hours (not limited by standard HA transition times)
- 🔌 **Direct Telnet control** - Bypasses standard integration limits
- 🎛️ **Custom services** - `lutron_fader.fade_to` and `lutron_fader.long_fade`
- 🔄 **Parallel entities** - Creates `*_fader` entities alongside your existing Lutron lights

## Installation

### Via HACS (Recommended - Coming Soon)
1. Open HACS
2. Go to Integrations
3. Search for "Lutron Fader"
4. Click Install

### Manual Installation
1. Copy the `lutron_fader` folder to your `custom_components` directory
2. Restart Home Assistant

## Configuration

Add to your `configuration.yaml`:
```yaml
lutron_fader:
  host: 10.0.1.111  # Your Caseta Pro hub IP
  port: 23
  username: lutron
  password: integration
```

## Usage

### Via Service Calls

Fade a light over 30 minutes:
```yaml
service: lutron_fader.fade_to
data:
  zone_id: 28
  brightness: 0
  fade_time: 1800
```

### Via Automations

Sunrise simulation:
```yaml
automation:
  - alias: "Wake Up - Sunrise"
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

## Requirements

- Home Assistant 2023.1 or newer
- Lutron Caseta Pro Smart Bridge (L-BDGPRO2-WH) or RadioRA 2 Select
- Telnet integration enabled on your Lutron hub

## Known Limitations

- Only works with Caseta **Pro** or RadioRA 2 Select (requires Telnet support)
- Zone IDs must be manually configured (auto-discovery in progress)

## Development

This integration is under active development. Contributions welcome!

## License

Apache 2.0

## Credits

Created by rblancarte
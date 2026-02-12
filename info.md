# Lutron Fader

Extended fade time support for Lutron Caseta Pro lights via direct Telnet control.

## Features

- **Long Fade Times** - Fade lights over minutes or hours (up to 2 hours), not limited by standard Home Assistant transition times
- **Hardware-Accelerated Fading** - Uses native Lutron dimming for smooth, reliable transitions
- **Custom Lovelace Card** - Included card with brightness slider and fade time controls
- **Direct Telnet Control** - Uses Lutron Integration Protocol (LIP) for professional-grade control
- **Auto-Discovery** - Automatically discover and configure lights from Integration Report
- **Config Flow** - Easy UI-based setup, no YAML required

## Requirements

- Lutron Caseta Pro Smart Bridge (L-BDGPRO2-WH), RadioRA 2 Select, or HomeWorks QS/QSX
- Telnet/LIP support enabled on your Lutron hub
- Home Assistant 2023.1 or newer

**Note:** Standard Caseta bridges (non-Pro) are not supported as they lack Telnet access.

## Quick Start

1. Install via HACS
2. Add integration via UI (Settings → Devices & Services → Add Integration)
3. Enter your Lutron hub IP address
4. Run `auto_configure_from_report` service with your Integration Report
5. Add the custom card resource: `/lutron_fader_static/lutron-fader-card.js`
6. Start creating long fades!

## Usage

Use the `lutron_fader.fade_to` service for smooth fades:

```yaml
service: lutron_fader.fade_to
data:
  entity_id: light.bedroom_lamp
  brightness: 0
  fade_time: 1800  # 30 minutes
```

Or use the custom Lovelace card for visual control with a fade time slider.

## Perfect For

- 🌅 Sunrise/sunset simulations
- 😴 Bedtime routines
- 🎬 Movie mode transitions
- 🎨 Mood lighting scenes
- ⏰ Wake-up automations

---

[Full Documentation](https://github.com/rblancarte/lutron-fader) | [Report Issues](https://github.com/rblancarte/lutron-fader/issues)

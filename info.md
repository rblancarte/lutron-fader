# Lutron Fader

See the **progress of native fades** on your Lutron lights.

Lutron hubs fade lights in hardware, but report only the fade's *target*. Start a 30-minute fade and Home Assistant shows the end brightness straight away. Lutron Fader watches for fades you start from Home Assistant and publishes each one's progress as a sensor.

## Features

- A `sensor.<light>_fade` for every dimmable Lutron light: `idle` or `fading`, with live brightness, target, end time and percent complete
- Tracks fades from dashboards, automations, scripts and voice, including area and device targets
- Ends a tracked fade as soon as it's overridden (a Pico, the app, a new command)
- Resumes its countdown after a Home Assistant restart
- Zero configuration: lights are found automatically

## Requirements

- Home Assistant 2026.10+
- Lutron lights from the official **Lutron Caseta** integration (any Smart Bridge), the official **Lutron** (RadioRA 2) integration, or **lutron_caseta_pro**

## Quick Start

1. Install via HACS and restart Home Assistant
2. **Settings → Devices & services → Add Integration → Lutron Fader**
3. Fade a light with `light.turn_on` + `transition`, then watch its `sensor.<light>_fade`

## Upgrading from 1.x

1.x drove lights over Telnet. 2.0 migrates automatically and removes the old `light.lutron_zone_*` entities. Point automations and cards at the official Lutron lights.

See the [README](https://github.com/rblancarte/lutron-fader) for the full sensor reference, examples and troubleshooting.

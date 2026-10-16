# Lutron Fader

A Home Assistant custom integration that shows the **progress of native fades** on Lutron lights.

## Why This Integration?

Lutron dimmers fade beautifully in hardware: smoother and more reliable than software that steps the brightness every few seconds. Home Assistant's official Lutron Caseta integration can already ask for those fades. `light.turn_on` with a `transition` sends a native fade over Lutron's LEAP API, and long fades (minutes to hours) work.

What's missing is **seeing the fade happen**. The hub reports only the fade's *target*, never the level along the way. So the moment a 30-minute fade starts, Home Assistant shows the light at its end brightness. Dashboards, automations and you have no idea where the fade actually is or when it will finish.

Lutron Fader fills that gap. It never talks to the hub and never sends commands. It watches Home Assistant for fades sent to your Lutron lights, works out where each fade is, and publishes it as a sensor per light.

## Features

- 📈 **Live fade progress**: a `sensor.<light>_fade` for every dimmable Lutron light, with the current calculated brightness, start and target, start and end times, and percent complete
- 🎯 **Works with every way you start a fade**: dashboards, automations, scripts, voice. Targets by entity, area, device or floor are all resolved to the lights involved.
- ✋ **Knows when a fade is overridden**: a Pico press, the Lutron app, or a new command ends the tracked fade at once
- 🔁 **Survives restarts**: a fade in progress picks up its countdown after Home Assistant restarts
- 🧩 **Zero configuration**: one click to add; lights are found automatically, including ones added later
- 🪶 **Light on your database**: the per-second attributes are kept out of the recorder

## Requirements

- Home Assistant **2026.10** or newer
- Lutron lights in Home Assistant from one of:
  - the official **Lutron Caseta** integration (any Smart Bridge; the Pro model is *not* required)
  - the official **Lutron** integration (RadioRA 2)
  - the **lutron_caseta_pro** custom integration

Only lights that can **dim** and support **transitions** get a fade sensor. On/off-only loads have nothing to fade.

## Installation

### Via HACS (custom repository)
1. In HACS, open the ⋮ menu → **Custom repositories**
2. Add `https://github.com/rblancarte/lutron-fader` with category **Integration**
3. Install **Lutron Fader** and restart Home Assistant

### Manual Installation
1. Download the latest release from GitHub
2. Copy `custom_components/lutron_fader` into your Home Assistant `config/custom_components/` folder
3. Restart Home Assistant

### Setup
**Settings → Devices & services → Add Integration → Lutron Fader → Submit.** That's all: there's nothing to configure.

## The Fade Sensors

Each tracked light gets a sensor whose ID mirrors the light's: `light.living_room_floor_lamp` → `sensor.living_room_floor_lamp_fade`. The sensor sits on the light's own device page.

**State:** `idle` or `fading`

**Attributes:**

| Attribute | When | Meaning |
|---|---|---|
| `light_entity_id` | always | The light this sensor tracks |
| `brightness` | fading | Calculated current brightness (0–255) |
| `brightness_pct` | fading | Calculated current brightness (0–100%) |
| `start_pct` | fading | Brightness when the fade began |
| `target_pct` | fading | Brightness the fade is heading to |
| `started_at` | fading | When the fade began (ISO time, UTC) |
| `ends_at` | fading | When the fade will finish (ISO time, UTC) |
| `progress` | fading | Percent complete (0–100) |

### How a fade is tracked

```
light.turn_on / turn_off with transition ──▶ Pending ──light reports its new target──▶ Fading
                                                │                                    │
                         already there, or no report within 5s       ends_at reached, or the light
                                                ▼                    changes to anything else
                                              Idle ◀─────────────────────────────────┘
```

The fade's target is taken from what the light itself reports right after the command, so every form of command works: `brightness`, `brightness_pct`, a bare `turn_on`, or `turn_off`. A new fade started partway through a fade begins from the calculated level, not from the target Home Assistant was showing.

## Examples

### Start a fade (nothing new: standard Home Assistant)
```yaml
action: light.turn_on
target:
  entity_id: light.master_bedroom_ron_lamp
data:
  brightness_pct: 100
  transition: 1800   # 30 minutes
```

### Do something when a fade finishes
```yaml
automation:
  - alias: "Sunrise fade done"
    triggers:
      - trigger: state
        entity_id: sensor.master_bedroom_ron_lamp_fade
        from: "fading"
        to: "idle"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Bedroom lamp has finished fading."
```
`idle` also follows an override (for example, someone pressing the Pico). Add a condition on the light's brightness if you only want fades that ran to the end.

### Minutes left, as a template
```jinja
{% set ends = state_attr('sensor.master_bedroom_ron_lamp_fade', 'ends_at') %}
{{ ((as_datetime(ends) - now()).total_seconds() / 60) | round(0) if ends else 0 }}
```

### Companion card
The [Lutron Fader Card](https://github.com/rblancarte/lutron-fader-card) gives a dashboard control for starting fades of any length. Point it at the **official** Lutron light (for example `light.living_room_floor_lamp`).

## Known Limitations

- **Fades started outside Home Assistant aren't tracked.** For a fade from the Lutron app, a Pico or a scene on the hub, Home Assistant only ever hears the target. The light still updates; there's just no fade sensor activity.
- **The progress is calculated, not measured.** No Lutron API reports the in-between level, so the sensor assumes an even fade from start to target over the requested time.
- Lights that can't dim, or don't support transitions, aren't tracked.

## Upgrading from 1.x

Version 1.x controlled lights itself over a Telnet connection to the hub. 2.0 replaces that entirely:

- Your existing setup migrates automatically on restart. The old `light.lutron_zone_*` entities are removed.
- Point automations, scripts and cards at the **official** Lutron lights instead. Use `light.turn_on` with `transition` in place of the old `lutron_fader.fade_to` service.
- If a fade sensor's entity ID comes out with its area doubled (for example `sensor.bedroom_bedroom_lamp_fade`), open the sensor's settings and press **↻** next to the entity ID.

## Troubleshooting

### No fade sensors appear
1. Check that your lights come from a supported integration (see Requirements) and are dimmable
2. Check the logs (Settings → System → Logs) for `custom_components.lutron_fader`
3. For more detail, add this to `configuration.yaml`:
   ```yaml
   logger:
     logs:
       custom_components.lutron_fader: debug
   ```

### A fade doesn't show as fading
1. Make sure the command included `transition` and was sent from Home Assistant
2. With debug logging on, look for `fade requested` and `Pending(...) -> Fading(...)` lines

## Development

The integration's tests live in the [lutron-fader-dev](https://github.com/rblancarte/lutron-fader-dev) workspace. They run against a real Home Assistant using `pytest-homeassistant-custom-component`.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the Apache 2.0 License - see the LICENSE file for details.

## Credits

Created by [rblancarte](https://github.com/rblancarte)

Built with inspiration from the Home Assistant community.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Lutron Electronics Co., Inc.

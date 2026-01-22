# Lutron Fader Examples

This folder contains example dashboard configurations and usage examples for the Lutron Fader integration.

## Dashboard Examples

### example-dashboard.yaml

Contains various dashboard layouts for the Lutron Fader custom card:

- Single card example
- Vertical stack with multiple cards
- Grid layout (2 columns)
- Panel with title and multiple cards

**How to use:**
1. Copy the YAML configuration you want
2. Edit your Home Assistant dashboard
3. Add a new card in manual/YAML mode
4. Paste the configuration
5. Update entity IDs to match your lights

### auto-lutron-dashboard.yaml

Contains examples for automatically displaying all Lutron Fader entities:

- Manual grid layout
- Auto-entities configuration (requires auto-entities from HACS)
- Compact entity list

**How to use:**
1. For auto-entities examples, install `auto-entities` from HACS first
2. Copy the desired configuration
3. Update entity IDs as needed

## Quick Start Example

The simplest way to add a Lutron Fader card:

```yaml
type: custom:lutron-fader-card
entity: light.your_light_name
```

## Multi-Card Grid Layout

Display multiple lights in a 2-column grid:

```yaml
type: grid
columns: 2
cards:
  - type: custom:lutron-fader-card
    entity: light.living_room_floor_lamp
  - type: custom:lutron-fader-card
    entity: light.bedroom_lamp
  - type: custom:lutron-fader-card
    entity: light.office_lamp
```

## Full Page Dashboard

Create a dedicated page for all your Lutron lights:

```yaml
views:
  - title: Lutron Fader
    path: lutron
    icon: mdi:lightbulb-on-outline
    cards:
      - type: grid
        columns: 2
        cards:
          - type: custom:lutron-fader-card
            entity: light.living_room_floor_lamp
          - type: custom:lutron-fader-card
            entity: light.living_room_table_lamps
          # Add more cards for each light
```

## Automation Examples

See the main [README.md](../README.md#example-automations) for automation examples using the Lutron Fader services.

## Need Help?

- Check the main [README.md](../README.md) for installation and setup
- See [custom_components/lutron_fader/www/README.md](../custom_components/lutron_fader/www/README.md) for card-specific documentation
- Visit the [GitHub Issues](https://github.com/rblancarte/lutron-fader/issues) page for support

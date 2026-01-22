# Lutron Fader Card

This custom Lovelace card is bundled with the Lutron Fader integration.

## Installation

The card is automatically available after installing the integration. You just need to add it to your Lovelace resources:

### Step 1: Add the Resource

Go to **Settings → Dashboards → Resources** (☰ menu in top right → Resources)

Click **"+ Add Resource"** and enter:
- **URL**: `/lutron_fader_static/lutron-fader-card.js`
- **Resource type**: **JavaScript Module**

### Step 2: Use the Card

Add to your dashboard using YAML:

```yaml
type: custom:lutron-fader-card
entity: light.living_room_floor_lamp
```

Or use the visual editor and search for "Lutron Fader Card"

## Features

- Display current light state (ON/OFF) and brightness
- Slider to select desired brightness (0-100%)
- Fade time input (0-3600 seconds)
- Start Fade button to execute the transition
- Turn Off button with fade time support
- Input validation for fade time

## Configuration Options

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `entity` | string | Yes | Entity ID of your Lutron Fader light |
| `name` | string | No | Custom name (defaults to entity's friendly name) |

## Example

```yaml
type: custom:lutron-fader-card
entity: light.master_bedroom_ron_lamp
name: Ron's Lamp
```

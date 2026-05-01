"""Tests for LutronFaderLight entity."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from custom_components.lutron_fader.light import LutronFaderLight


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_light(zone_id=25, name="Test Light", original_entity_id=None):
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    connection = AsyncMock()
    return LutronFaderLight(
        hass=hass,
        connection=connection,
        name=name,
        zone_id=zone_id,
        unique_id=f"lutron_fader_{zone_id}",
        original_entity_id=original_entity_id,
    )


# ---------------------------------------------------------------------------
# Brightness conversion
# ---------------------------------------------------------------------------

class TestBrightnessConversion:
    @pytest.mark.asyncio
    async def test_turn_on_converts_255_to_100pct(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(brightness=255)

        light._connection.set_light_level.assert_called_once_with(25, 100, 0)

    @pytest.mark.asyncio
    async def test_turn_on_converts_128_to_50pct(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(brightness=128)

        args = light._connection.set_light_level.call_args[0]
        assert args[1] == 50  # ~50%

    @pytest.mark.asyncio
    async def test_update_converts_lutron_100_to_255(self):
        light = make_light()
        light._connection.query_light_level = AsyncMock(return_value=100.0)

        await light.async_update()

        assert light._attr_brightness == 255
        assert light._attr_is_on is True

    @pytest.mark.asyncio
    async def test_update_converts_lutron_0_to_off(self):
        light = make_light()
        light._connection.query_light_level = AsyncMock(return_value=0.0)

        await light.async_update()

        assert light._attr_brightness == 0
        assert light._attr_is_on is False

    @pytest.mark.asyncio
    async def test_update_none_response_leaves_state_unchanged(self):
        light = make_light()
        light._attr_is_on = True
        light._attr_brightness = 128
        light._connection.query_light_level = AsyncMock(return_value=None)

        await light.async_update()

        assert light._attr_is_on is True
        assert light._attr_brightness == 128


# ---------------------------------------------------------------------------
# turn_on / turn_off
# ---------------------------------------------------------------------------

class TestTurnOnOff:
    @pytest.mark.asyncio
    async def test_turn_on_passes_transition(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(brightness=255, transition=1800)

        light._connection.set_light_level.assert_called_once_with(25, 100, 1800)

    @pytest.mark.asyncio
    async def test_turn_on_defaults_transition_to_zero(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(brightness=255)

        args = light._connection.set_light_level.call_args[0]
        assert args[2] == 0

    @pytest.mark.asyncio
    async def test_turn_on_updates_state_on_success(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(brightness=255)

        assert light._attr_is_on is True
        light.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_on_does_not_update_state_on_failure(self):
        light = make_light()
        light._attr_is_on = False
        light._connection.set_light_level = AsyncMock(return_value=False)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(brightness=255)

        assert light._attr_is_on is False
        light.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_sends_brightness_zero(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_off(transition=900)

        light._connection.set_light_level.assert_called_once_with(25, 0, 900)

    @pytest.mark.asyncio
    async def test_turn_off_updates_state_on_success(self):
        light = make_light()
        light._attr_is_on = True
        light._connection.set_light_level = AsyncMock(return_value=True)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_off()

        assert light._attr_is_on is False
        assert light._attr_brightness == 0

    @pytest.mark.asyncio
    async def test_turn_on_no_zone_id_does_nothing(self):
        light = make_light(zone_id=None)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_on(brightness=255)

        light._connection.set_light_level.assert_not_called()
        light.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_no_zone_id_does_nothing(self):
        light = make_light(zone_id=None)
        light.async_write_ha_state = MagicMock()

        await light.async_turn_off()

        light._connection.set_light_level.assert_not_called()


# ---------------------------------------------------------------------------
# brightness property
# ---------------------------------------------------------------------------

class TestBrightnessProperty:
    def test_brightness_returns_zero_when_off(self):
        light = make_light()
        light._attr_is_on = False
        light._attr_brightness = 200

        assert light.brightness == 0

    def test_brightness_returns_value_when_on(self):
        light = make_light()
        light._attr_is_on = True
        light._attr_brightness = 200

        assert light.brightness == 200


# ---------------------------------------------------------------------------
# state mirroring from original entity
# ---------------------------------------------------------------------------

class TestOriginalEntityMirroring:
    @pytest.mark.asyncio
    async def test_mirrors_on_state(self):
        light = make_light(original_entity_id="light.original")
        original_state = MagicMock()
        original_state.state = "on"
        original_state.attributes = {"brightness": 200}
        light.hass.states.get = MagicMock(return_value=original_state)

        await light.async_update()

        assert light._attr_is_on is True
        assert light._attr_brightness == 200

    @pytest.mark.asyncio
    async def test_mirrors_off_state(self):
        light = make_light(original_entity_id="light.original")
        original_state = MagicMock()
        original_state.state = "off"
        original_state.attributes = {"brightness": 0}
        light.hass.states.get = MagicMock(return_value=original_state)

        await light.async_update()

        assert light._attr_is_on is False

    @pytest.mark.asyncio
    async def test_skips_telnet_query_when_mirroring(self):
        light = make_light(original_entity_id="light.original")
        original_state = MagicMock()
        original_state.state = "on"
        original_state.attributes = {"brightness": 128}
        light.hass.states.get = MagicMock(return_value=original_state)

        await light.async_update()

        light._connection.query_light_level.assert_not_called()

"""Tests for LutronFaderLight entity."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from custom_components.lutron_fader.light import LutronFaderLight
from custom_components.lutron_fader.lutron_telnet import SOURCE_INTERNAL, SOURCE_EXTERNAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_light(zone_id=25, name="Test Light", original_entity_id=None):
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    connection = AsyncMock()
    light = LutronFaderLight(
        hass=hass,
        connection=connection,
        name=name,
        zone_id=zone_id,
        unique_id=f"lutron_fader_{zone_id}",
        original_entity_id=original_entity_id,
    )
    light.async_write_ha_state = MagicMock()
    return light


# ---------------------------------------------------------------------------
# Brightness conversion
# ---------------------------------------------------------------------------

class TestBrightnessConversion:
    @pytest.mark.asyncio
    async def test_turn_on_255_sends_99_pct(self):
        """255 brightness hits the snap-to-full boundary: hub receives 99%."""
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)

        with patch("asyncio.get_event_loop") as mock_loop, \
             patch("custom_components.lutron_fader.light.async_track_time_interval"):
            mock_loop.return_value.call_later = MagicMock()
            await light.async_turn_on(brightness=255)

        light._connection.set_light_level.assert_called_once_with(25, 99, 0)

    @pytest.mark.asyncio
    async def test_turn_on_converts_128_to_50pct(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)

        await light.async_turn_on(brightness=128)

        args = light._connection.set_light_level.call_args[0]
        assert args[1] == 50

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
        """brightness=255 sends 99 to hub (snap boundary) with transition."""
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)

        with patch("asyncio.get_event_loop") as mock_loop, \
             patch("custom_components.lutron_fader.light.async_track_time_interval"):
            mock_loop.return_value.call_later = MagicMock()
            await light.async_turn_on(brightness=255, transition=1800)

        light._connection.set_light_level.assert_called_once_with(25, 99, 1800)

    @pytest.mark.asyncio
    async def test_turn_on_defaults_transition_to_zero(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)

        await light.async_turn_on(brightness=128)

        args = light._connection.set_light_level.call_args[0]
        assert args[2] == 0

    @pytest.mark.asyncio
    async def test_turn_on_updates_state_on_success(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)

        await light.async_turn_on(brightness=128)

        assert light._attr_is_on is True
        light.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_on_does_not_update_state_on_failure(self):
        light = make_light()
        light._attr_is_on = False
        light._connection.set_light_level = AsyncMock(return_value=False)

        await light.async_turn_on(brightness=255)

        assert light._attr_is_on is False
        light.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_instant_sends_zero(self):
        """Instant turn-off (no transition) sends level 0."""
        light = make_light()
        light._attr_is_on = True
        light._connection.set_light_level = AsyncMock(return_value=True)

        await light.async_turn_off()

        light._connection.set_light_level.assert_called_once_with(25, 0, 0)

    @pytest.mark.asyncio
    async def test_turn_off_with_fade_sends_level_1(self):
        """Fade-to-off sends level 1 so the hub uses its dimmer curve."""
        light = make_light()
        light._attr_is_on = True
        light._connection.set_light_level = AsyncMock(return_value=True)

        with patch("asyncio.get_event_loop") as mock_loop, \
             patch("custom_components.lutron_fader.light.async_track_time_interval"):
            mock_loop.return_value.call_later = MagicMock()
            await light.async_turn_off(transition=900)

        light._connection.set_light_level.assert_called_once_with(25, 1, 900)

    @pytest.mark.asyncio
    async def test_turn_off_instant_updates_state_on_success(self):
        light = make_light()
        light._attr_is_on = True
        light._connection.set_light_level = AsyncMock(return_value=True)

        await light.async_turn_off()

        assert light._attr_is_on is False
        assert light._attr_brightness == 0

    @pytest.mark.asyncio
    async def test_turn_on_no_zone_id_does_nothing(self):
        light = make_light(zone_id=None)

        await light.async_turn_on(brightness=255)

        light._connection.set_light_level.assert_not_called()
        light.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_no_zone_id_does_nothing(self):
        light = make_light(zone_id=None)

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
# Fade interpolation
# ---------------------------------------------------------------------------

class TestFadeInterpolation:
    def test_no_interpolation_when_no_fade_active(self):
        light = make_light()
        light._attr_is_on = True
        light._attr_brightness = 128

        assert light.brightness == 128

    def test_interpolated_at_midpoint(self):
        light = make_light()
        light._attr_is_on = True
        light._fade_start_level = 0.0
        light._fade_target_level = 255.0
        light._fade_duration = 10.0
        light._fade_start_time = time.monotonic() - 5.0  # 5s in
        light._fade_cancel_unsub = MagicMock()  # marks fade active

        brightness = light.brightness
        assert 120 <= brightness <= 135  # roughly 50% of 255

    def test_interpolated_at_start(self):
        light = make_light()
        light._attr_is_on = True
        light._fade_start_level = 0.0
        light._fade_target_level = 255.0
        light._fade_duration = 10.0
        light._fade_start_time = time.monotonic()  # just started
        light._fade_cancel_unsub = MagicMock()

        assert light.brightness < 10

    def test_interpolated_at_end_clamps_to_target(self):
        light = make_light()
        light._attr_is_on = True
        light._fade_start_level = 0.0
        light._fade_target_level = 200.0
        light._fade_duration = 5.0
        light._fade_start_time = time.monotonic() - 10.0  # past end
        light._fade_cancel_unsub = MagicMock()

        assert light.brightness == 200

    def test_fade_tick_snaps_at_completion(self):
        light = make_light()
        light._attr_is_on = True
        light._fade_start_level = 0.0
        light._fade_target_level = 200.0
        light._fade_duration = 5.0
        light._fade_start_time = time.monotonic() - 10.0  # elapsed > duration
        light._fade_cancel_unsub = MagicMock()

        light._fade_tick(None)

        assert light._attr_brightness == 200
        assert light._attr_is_on is True
        assert light._fade_cancel_unsub is None  # timer cancelled

    def test_fade_tick_to_zero_snaps_off(self):
        light = make_light()
        light._attr_is_on = True
        light._fade_start_level = 128.0
        light._fade_target_level = 0.0
        light._fade_duration = 5.0
        light._fade_start_time = time.monotonic() - 10.0
        light._fade_cancel_unsub = MagicMock()

        light._fade_tick(None)

        assert light._attr_brightness == 0
        assert light._attr_is_on is False

    def test_fade_tick_mid_fade_interpolates(self):
        light = make_light()
        light._attr_is_on = True
        light._fade_start_level = 0.0
        light._fade_target_level = 100.0
        light._fade_duration = 10.0
        light._fade_start_time = time.monotonic() - 5.0
        unsub = MagicMock()
        light._fade_cancel_unsub = unsub

        light._fade_tick(None)

        assert 45 <= light._attr_brightness <= 55
        assert light._fade_cancel_unsub is unsub  # still running


# ---------------------------------------------------------------------------
# Boundary snapping
# ---------------------------------------------------------------------------

class TestBoundarySnapping:
    @pytest.mark.asyncio
    async def test_turn_on_100pct_schedules_snap_to_255(self):
        """Full brightness (≥99%) schedules a call_later snap to 255."""
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)

        with patch("asyncio.get_event_loop") as mock_loop, \
             patch("custom_components.lutron_fader.light.async_track_time_interval"):
            mock_call_later = MagicMock()
            mock_loop.return_value.call_later = mock_call_later
            await light.async_turn_on(brightness=255, transition=10)

        # snap scheduled for 10 seconds later
        mock_call_later.assert_called_once_with(10, light._snap_brightness, 255)

    @pytest.mark.asyncio
    async def test_turn_on_100pct_no_transition_no_snap_scheduled(self):
        """Instant set to full brightness sets 255 directly, no call_later."""
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_call_later = MagicMock()
            mock_loop.return_value.call_later = mock_call_later
            await light.async_turn_on(brightness=255)

        mock_call_later.assert_not_called()
        assert light._attr_brightness == 255

    @pytest.mark.asyncio
    async def test_turn_off_with_fade_schedules_snap_off(self):
        """Fade-to-off schedules call_later for snap-off."""
        light = make_light()
        light._attr_is_on = True
        light._connection.set_light_level = AsyncMock(return_value=True)

        with patch("asyncio.get_event_loop") as mock_loop, \
             patch("custom_components.lutron_fader.light.async_track_time_interval"):
            mock_call_later = MagicMock()
            mock_loop.return_value.call_later = mock_call_later
            await light.async_turn_off(transition=30)

        mock_call_later.assert_called_once_with(30, light._snap_off)

    def test_snap_brightness_sets_value_and_cancels_fade(self):
        light = make_light()
        light._fade_cancel_unsub = MagicMock()

        light._snap_brightness(255)

        assert light._attr_brightness == 255
        assert light._attr_is_on is True
        assert light._fade_cancel_unsub is None

    def test_snap_brightness_sends_hub_command(self):
        """_snap_brightness must tell the hub to match the snapped level."""
        light = make_light()
        light._fade_cancel_unsub = MagicMock()

        light._snap_brightness(255)

        light.hass.async_create_task.assert_called_once()

    def test_snap_brightness_zero_sends_zero_to_hub(self):
        light = make_light()
        light._fade_cancel_unsub = MagicMock()

        light._snap_brightness(0)

        light.hass.async_create_task.assert_called_once()
        assert light._attr_is_on is False

    def test_snap_off_clears_state_and_cancels_fade(self):
        light = make_light()
        light._attr_is_on = True
        light._attr_brightness = 100
        light._fade_cancel_unsub = MagicMock()

        light._snap_off()

        assert light._attr_is_on is False
        assert light._attr_brightness == 0
        assert light._fade_cancel_unsub is None

    def test_snap_off_sends_zero_to_hub(self):
        """_snap_off must actually cut the hub to 0, not just update HA state."""
        light = make_light()
        light._attr_is_on = True
        light._fade_cancel_unsub = MagicMock()

        light._snap_off()

        light.hass.async_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# External push cancels fade
# ---------------------------------------------------------------------------

class TestExternalPushCancelsFade:
    def test_external_push_cancels_active_fade_if_different_level(self):
        """A user override (different level) cancels our active fade."""
        light = make_light()
        light._attr_is_on = True
        light._fade_cancel_unsub = MagicMock()
        light._fade_target_lutron = 0.0  # we were fading to off
        unsub = light._fade_cancel_unsub

        # User intervenes at 75% — clearly different from our 0% target
        light._handle_push("~OUTPUT,25,1,75.00", SOURCE_EXTERNAL)

        unsub.assert_called_once()
        assert light._fade_cancel_unsub is None
        assert light._attr_brightness == int((75.0 / 100.0) * 255)

    def test_external_push_ignored_when_matches_our_setpoint(self):
        """Hub echoing our own setpoint (within 2%) should not cancel the fade."""
        light = make_light()
        light._attr_is_on = True
        light._attr_brightness = 200
        light._fade_cancel_unsub = MagicMock()
        light._fade_target_lutron = 0.0  # we are fading to off

        # Hub broadcasts 0.00 — matches our target, just a setpoint echo
        light._handle_push("~OUTPUT,25,1,0.00", SOURCE_EXTERNAL)

        # Fade must still be active
        light._fade_cancel_unsub.assert_not_called()
        assert light._attr_brightness == 200  # unchanged

    def test_internal_push_does_not_update_state(self):
        """SOURCE_INTERNAL echoes are ignored by _handle_push."""
        light = make_light()
        light._attr_is_on = True
        light._attr_brightness = 50

        light._handle_push("~OUTPUT,25,1,75.00", SOURCE_INTERNAL)

        # State should not have changed from internal echo
        assert light._attr_brightness == 50

    def test_external_push_wrong_zone_ignored(self):
        light = make_light(zone_id=25)
        light._attr_brightness = 50

        light._handle_push("~OUTPUT,99,1,75.00", SOURCE_EXTERNAL)

        assert light._attr_brightness == 50

    def test_external_push_malformed_ignored(self):
        light = make_light()
        light._attr_brightness = 50

        light._handle_push("~OUTPUT,25,1", SOURCE_EXTERNAL)  # too few parts

        assert light._attr_brightness == 50


# ---------------------------------------------------------------------------
# supported_features
# ---------------------------------------------------------------------------

class TestSupportedFeatures:
    def test_transition_feature_declared(self):
        """Entity must advertise TRANSITION so HA passes the transition kwarg."""
        from homeassistant.components.light import LightEntityFeature
        light = make_light()
        assert light._attr_supported_features == LightEntityFeature.TRANSITION


# ---------------------------------------------------------------------------
# _fade_target_lutron cleared on failure
# ---------------------------------------------------------------------------

class TestFadeTargetClearedOnFailure:
    @pytest.mark.asyncio
    async def test_turn_on_failure_clears_fade_target(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=False)

        await light.async_turn_on(brightness=128, transition=30)

        assert light._fade_target_lutron is None

    @pytest.mark.asyncio
    async def test_turn_off_failure_clears_fade_target(self):
        light = make_light()
        light._attr_is_on = True
        light._connection.set_light_level = AsyncMock(return_value=False)

        await light.async_turn_off(transition=30)

        assert light._fade_target_lutron is None

    @pytest.mark.asyncio
    async def test_turn_on_success_sets_fade_target(self):
        light = make_light()
        light._connection.set_light_level = AsyncMock(return_value=True)

        with patch("asyncio.get_event_loop"), \
             patch("custom_components.lutron_fader.light.async_track_time_interval"):
            await light.async_turn_on(brightness=128, transition=30)

        assert light._fade_target_lutron == 50  # 128/255*100 ≈ 50


# ---------------------------------------------------------------------------
# Race guard: _fade_target_lutron set before command
# ---------------------------------------------------------------------------

class TestRaceGuard:
    def test_external_push_ignored_when_fade_target_set_but_tracker_not_started(self):
        """Guard works even before _start_fade_tracking is called (mid-await window)."""
        light = make_light()
        light._attr_is_on = True
        light._attr_brightness = 200
        # Simulate state just after setting _fade_target_lutron but before _start_fade_tracking
        light._fade_target_lutron = 0.0
        light._fade_cancel_unsub = None  # tracker not started yet

        light._handle_push("~OUTPUT,25,1,0.00", SOURCE_EXTERNAL)

        # Must be ignored — fade_target matches
        assert light._attr_brightness == 200

    def test_external_push_accepted_when_no_fade_target(self):
        """Without a fade target set, external pushes update state normally."""
        light = make_light()
        light._attr_is_on = True
        light._attr_brightness = 200
        light._fade_target_lutron = None

        light._handle_push("~OUTPUT,25,1,0.00", SOURCE_EXTERNAL)

        assert light._attr_is_on is False
        assert light._attr_brightness == 0


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

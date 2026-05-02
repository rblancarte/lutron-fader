"""Support for Lutron Caseta lights with fade time."""
import asyncio
import logging
import time
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
    PLATFORM_SCHEMA,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import voluptuous as vol
from datetime import timedelta

from .const import DOMAIN
from .lutron_telnet import LutronTelnetConnection, SOURCE_INTERNAL, SOURCE_EXTERNAL

_LOGGER = logging.getLogger(__name__)

# How often to push interpolated brightness updates to the UI during a fade
_FADE_REFRESH_INTERVAL = timedelta(seconds=1)

# Configuration for manually defining lights in YAML
LIGHT_SCHEMA = vol.Schema(
    {
        vol.Required("zone_id"): cv.positive_int,
        vol.Required(CONF_NAME): cv.string,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional("lights", default=[]): vol.All(cv.ensure_list, [LIGHT_SCHEMA]),
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Lutron Fader lights from YAML configuration."""
    _LOGGER.info("Setting up Lutron Fader lights from YAML")

    # Get the connection from hass.data (stored by __init__.py)
    if "yaml_connection" not in hass.data[DOMAIN]:
        _LOGGER.error("Lutron Fader connection not found in hass.data")
        return

    connection: LutronTelnetConnection = hass.data[DOMAIN]["yaml_connection"]

    # Option 1: Manual light configuration (if provided in config)
    manual_lights = config.get("lights", [])

    fader_lights = []

    # Add manually configured lights
    for light_config in manual_lights:
        zone_id = light_config["zone_id"]
        name = light_config[CONF_NAME]

        _LOGGER.info("Adding manually configured light: %s (Zone %s)", name, zone_id)

        fader_light = LutronFaderLight(
            hass=hass,
            connection=connection,
            name=name,
            zone_id=zone_id,
            unique_id=f"lutron_fader_{zone_id}",
        )
        fader_lights.append(fader_light)

    # Option 2: Use zone_mappings (if no manual config)
    if not manual_lights:
        # Check if zone_mappings were provided in YAML
        zone_mappings = hass.data[DOMAIN].get("zone_mappings", {})

        if zone_mappings:
            # Use the zone mappings from YAML
            _LOGGER.info("Using zone mappings from YAML configuration")
            for zone_name, zone_id in zone_mappings.items():
                fader_light = LutronFaderLight(
                    hass=hass,
                    connection=connection,
                    name=f"Lutron {zone_name}",
                    zone_id=zone_id,
                    unique_id=f"lutron_fader_{zone_id}",
                )
                fader_lights.append(fader_light)
        else:
            _LOGGER.warning("No zone_mappings configured in YAML")

    if fader_lights:
        _LOGGER.info("Adding %d Lutron Fader light entities", len(fader_lights))
        async_add_entities(fader_lights, True)
    else:
        _LOGGER.warning(
            "No lights configured. Add lights to your YAML config or ensure lutron_caseta integration is set up."
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lutron Fader lights from a config entry (UI-based config)."""
    _LOGGER.info("Setting up Lutron Fader lights from config entry")

    # Get our telnet connection
    connection_data = hass.data[DOMAIN][config_entry.entry_id]
    connection: LutronTelnetConnection = connection_data["connection"]

    # Get zone mappings from config entry (populated by auto_configure service)
    zone_mappings = config_entry.data.get("zone_mappings", {})

    if not zone_mappings:
        _LOGGER.info("No zone mappings found. Run auto_configure_from_report service to create entities.")
        return

    # Create light entities for each mapped zone
    fader_lights = []

    for entity_id, zone_id in zone_mappings.items():
        # Get the original entity to extract its friendly name
        state = hass.states.get(entity_id)
        if state:
            name = state.attributes.get("friendly_name", f"Zone {zone_id}")
        else:
            name = f"Zone {zone_id}"

        # Create a unique_id for this lutron_fader entity
        unique_id = f"lutron_fader_zone_{zone_id}"

        _LOGGER.info("Creating Lutron Fader entity: %s (Zone %s)", name, zone_id)

        fader_light = LutronFaderLight(
            hass=hass,
            connection=connection,
            name=name,
            zone_id=zone_id,
            unique_id=unique_id,
            original_entity_id=entity_id,
        )
        fader_lights.append(fader_light)

    if fader_lights:
        _LOGGER.info("Adding %d Lutron Fader light entities from config entry", len(fader_lights))
        async_add_entities(fader_lights, True)
    else:
        _LOGGER.warning("No lights created. Check zone_mappings in config entry.")


class LutronFaderLight(LightEntity):
    """Representation of a Lutron light with extended fade time support."""

    def __init__(
        self,
        hass: HomeAssistant,
        connection: LutronTelnetConnection,
        name: str,
        zone_id: int | None,
        unique_id: str,
        original_entity_id: str | None = None,
    ):
        """Initialize the Lutron Fader light."""
        self.hass = hass
        self._connection = connection
        self._zone_id = zone_id
        self._original_entity_id = original_entity_id

        # Entity attributes
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_features = LightEntityFeature.TRANSITION
        self._attr_should_poll = False

        # State tracking
        self._attr_is_on = False
        self._attr_brightness = 0

        # Fade interpolation state
        self._fade_start_level: float = 0.0        # 0-255
        self._fade_target_level: float = 0.0       # 0-255 (post-snap logical target)
        self._fade_target_lutron: float | None = None  # 0-100, hub setpoint we sent
        self._fade_start_time: float = 0.0
        self._fade_duration: float = 0.0
        self._fade_cancel_unsub = None              # unsubscribe handle for refresh timer

    async def async_added_to_hass(self) -> None:
        """Register push callback when entity is added."""
        self._connection.add_push_callback(self._handle_push)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister push callback when entity is removed."""
        self._connection.remove_push_callback(self._handle_push)
        self._cancel_fade_tracking()

    # ------------------------------------------------------------------
    # Fade helpers
    # ------------------------------------------------------------------

    def _start_fade_tracking(
        self, start_level: float, target_level: float, duration: float,
        lutron_target: float | None = None,
    ) -> None:
        """Begin interpolation tracking for a new fade."""
        self._cancel_fade_tracking()
        self._fade_start_level = start_level
        self._fade_target_level = target_level
        self._fade_target_lutron = lutron_target
        self._fade_start_time = time.monotonic()
        self._fade_duration = duration

        self._fade_cancel_unsub = async_track_time_interval(
            self.hass, self._fade_tick, _FADE_REFRESH_INTERVAL
        )
        _LOGGER.debug(
            "Fade tracking started: zone %s %.1f→%.1f over %.1fs",
            self._zone_id, start_level, target_level, duration,
        )

    def _cancel_fade_tracking(self) -> None:
        """Stop the periodic refresh timer."""
        if self._fade_cancel_unsub is not None:
            self._fade_cancel_unsub()
            self._fade_cancel_unsub = None
        self._fade_target_lutron = None

    @callback
    def _fade_tick(self, _now) -> None:
        """Called every second during an active fade to push interpolated state."""
        elapsed = time.monotonic() - self._fade_start_time
        if elapsed >= self._fade_duration:
            # Fade complete — snap to final value
            self._cancel_fade_tracking()
            self._attr_brightness = int(self._fade_target_level)
            self._attr_is_on = self._fade_target_level > 0
            _LOGGER.debug("Fade complete: zone %s snapped to %.0f", self._zone_id, self._fade_target_level)
        else:
            progress = elapsed / self._fade_duration
            interpolated = self._fade_start_level + (self._fade_target_level - self._fade_start_level) * progress
            self._attr_brightness = int(interpolated)
            self._attr_is_on = interpolated > 0

        self.async_write_ha_state()

    def _interpolated_brightness(self) -> int:
        """Return the current interpolated brightness (0-255) if a fade is active."""
        if self._fade_cancel_unsub is None or self._fade_duration <= 0:
            return self._attr_brightness

        elapsed = time.monotonic() - self._fade_start_time
        if elapsed >= self._fade_duration:
            return int(self._fade_target_level)

        progress = elapsed / self._fade_duration
        interpolated = self._fade_start_level + (self._fade_target_level - self._fade_start_level) * progress
        return int(interpolated)

    # ------------------------------------------------------------------
    # Push handler
    # ------------------------------------------------------------------

    def _handle_push(self, line: str, source: str) -> None:
        """Handle a push event from the hub."""
        if not line.startswith("~OUTPUT"):
            return

        parts = line.split(",")
        if len(parts) < 4:
            return

        try:
            zone_id = int(parts[1])
            level = float(parts[3])
        except (ValueError, IndexError):
            return

        if zone_id != self._zone_id:
            return

        if source == SOURCE_EXTERNAL:
            # If we have a pending or active fade, check whether this push is just the hub
            # broadcasting our own setpoint (it does so immediately on fade start, before
            # async_turn_on/off has a chance to call _start_fade_tracking).
            # Only cancel if the level is genuinely different — i.e. a real user override.
            if self._fade_target_lutron is not None:
                if abs(level - self._fade_target_lutron) < 2.0:
                    _LOGGER.debug(
                        "Zone %s hub setpoint echo %.2f%% matches our target %.2f%% — ignoring",
                        zone_id, level, self._fade_target_lutron,
                    )
                    return

            _LOGGER.debug("Zone %s external update: %.2f%%", zone_id, level)
            self._cancel_fade_tracking()
            self._attr_is_on = level > 0
            self._attr_brightness = int((level / 100.0) * 255)
            self.async_write_ha_state()
        # SOURCE_INTERNAL echoes are handled by the fade tracker; ignore here

    # ------------------------------------------------------------------
    # Standard entity methods
    # ------------------------------------------------------------------

    async def async_update(self) -> None:
        """Update the light state."""
        # If we have an original entity, mirror its state
        if self._original_entity_id:
            original_state = self.hass.states.get(self._original_entity_id)
            if original_state:
                self._attr_is_on = original_state.state == "on"
                self._attr_brightness = original_state.attributes.get("brightness", 0)

        # If we have a zone_id, query the actual state from Lutron
        elif self._zone_id is not None:
            level = await self._connection.query_light_level(self._zone_id)
            if level is not None:
                # Convert from 0-100 to 0-255
                self._attr_brightness = int((level / 100.0) * 255)
                self._attr_is_on = level > 0

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._attr_is_on

    @property
    def brightness(self) -> int | None:
        """Return the current brightness (0-255), interpolated during active fades."""
        if not self._attr_is_on:
            return 0
        return self._interpolated_brightness()

    # ------------------------------------------------------------------
    # Turn on / off
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light with optional fade time."""
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        transition = kwargs.get(ATTR_TRANSITION, 0)

        # Convert brightness from 0-255 to 0-100
        lutron_level = (brightness / 255.0) * 100

        # Boundary: clamp away from true-off; snap to 100 after fade
        snap_to_full = lutron_level >= 99.0
        if snap_to_full:
            send_level = 99
        else:
            send_level = max(1, int(lutron_level))

        fade_time = int(transition)

        _LOGGER.info(
            "Turning on %s to %.1f%% (send %d%%) with fade %ds (zone: %s)",
            self._attr_name, lutron_level, send_level, fade_time, self._zone_id,
        )

        if self._zone_id is None:
            _LOGGER.error(
                "Zone ID not configured for %s. Please configure zone_id in YAML or use the service call.",
                self._attr_name,
            )
            return

        # Set before sending so _handle_push can recognise our hub echo mid-await.
        if fade_time > 0:
            self._fade_target_lutron = 100.0 if snap_to_full else float(send_level)

        success = await self._connection.set_light_level(self._zone_id, send_level, fade_time)

        if not success:
            self._fade_target_lutron = None
            return

        if success:
            start_brightness = self._interpolated_brightness() if self._attr_is_on else 0
            target_brightness = 255 if snap_to_full else int((send_level / 100.0) * 255)

            self._attr_is_on = True
            self._attr_brightness = start_brightness

            if fade_time > 0:
                self._start_fade_tracking(
                    start_level=float(start_brightness),
                    target_level=float(target_brightness),
                    duration=float(fade_time),
                    lutron_target=100.0 if snap_to_full else float(send_level),
                )
            else:
                self._cancel_fade_tracking()
                self._attr_brightness = target_brightness

            self.async_write_ha_state()

            if snap_to_full and fade_time > 0:
                # After the fade completes, snap to 255
                asyncio.get_event_loop().call_later(
                    fade_time, self._snap_brightness, 255
                )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light with optional fade time."""
        transition = kwargs.get(ATTR_TRANSITION, 0)
        fade_time = int(transition)

        _LOGGER.info(
            "Turning off %s with fade %ds (zone: %s)",
            self._attr_name, fade_time, self._zone_id,
        )

        if self._zone_id is None:
            _LOGGER.error(
                "Zone ID not configured for %s. Please configure zone_id in YAML or use the service call.",
                self._attr_name,
            )
            return

        if fade_time > 0:
            # Set before sending so _handle_push can recognise our hub echo mid-await.
            self._fade_target_lutron = 0.0
            success = await self._connection.set_light_level(self._zone_id, 1, fade_time)
        else:
            success = await self._connection.set_light_level(self._zone_id, 0, 0)

        if not success:
            self._fade_target_lutron = None
            return

        if success:
            if fade_time > 0:
                start_brightness = float(self._interpolated_brightness() if self._attr_is_on else 0)
                self._start_fade_tracking(
                    start_level=start_brightness,
                    target_level=0.0,
                    duration=float(fade_time),
                    lutron_target=0.0,
                )
                self._attr_is_on = True  # Still visually on while fading
                self.async_write_ha_state()

                # Snap off after fade completes
                asyncio.get_event_loop().call_later(fade_time, self._snap_off)
            else:
                self._cancel_fade_tracking()
                self._attr_is_on = False
                self._attr_brightness = 0
                self.async_write_ha_state()

    @callback
    def _snap_brightness(self, value: int) -> None:
        """Snap brightness to a fixed value after a fade completes."""
        self._cancel_fade_tracking()
        self._attr_brightness = value
        self._attr_is_on = value > 0
        self.async_write_ha_state()
        if self._zone_id is not None:
            lutron_level = int((value / 255.0) * 100)
            self.hass.async_create_task(
                self._connection.set_light_level(self._zone_id, lutron_level, 0)
            )

    @callback
    def _snap_off(self) -> None:
        """Snap to fully off after a fade-to-off completes."""
        self._cancel_fade_tracking()
        self._attr_is_on = False
        self._attr_brightness = 0
        self.async_write_ha_state()
        if self._zone_id is not None:
            self.hass.async_create_task(
                self._connection.set_light_level(self._zone_id, 0, 0)
            )

    def set_zone_id(self, zone_id: int) -> None:
        """Set the zone ID for this light (for manual configuration)."""
        self._zone_id = zone_id
        _LOGGER.info("Zone ID set to %s for %s", zone_id, self._attr_name)

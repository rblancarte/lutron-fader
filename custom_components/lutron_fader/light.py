"""Support for Lutron Caseta lights with fade time."""
import logging
import time
from dataclasses import dataclass
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import voluptuous as vol
from datetime import timedelta

from .const import DOMAIN
from .lutron_telnet import (
    OUTPUT_ACTION_ZONE_LEVEL,
    SOURCE_EXTERNAL,
    LutronTelnetConnection,
    NotConnected,
)

_LOGGER = logging.getLogger(__name__)

# How often to push interpolated brightness updates to the UI during a fade
_FADE_REFRESH_INTERVAL = timedelta(seconds=1)

# A push within this many percent of our target is the hub echoing our own command
_ECHO_TOLERANCE = 2.0

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
    connection_data = hass.data[DOMAIN][config_entry.entry_id]
    connection: LutronTelnetConnection = connection_data["connection"]

    fader_lights = []

    # Primary source: zones from config flow {zone_id_str: name}
    zones = config_entry.data.get("zones", {})
    for zone_id_str, name in zones.items():
        zone_id = int(zone_id_str)
        fader_lights.append(LutronFaderLight(
            hass=hass,
            connection=connection,
            name=name,
            zone_id=zone_id,
            unique_id=f"lutron_fader_zone_{zone_id}",
        ))

    # Fallback: zone_mappings from auto_configure service {entity_id: zone_id}
    if not fader_lights:
        zone_mappings = config_entry.data.get("zone_mappings", {})
        for entity_id, zone_id in zone_mappings.items():
            state = hass.states.get(entity_id)
            name = state.attributes.get("friendly_name", f"Zone {zone_id}") if state else f"Zone {zone_id}"
            fader_lights.append(LutronFaderLight(
                hass=hass,
                connection=connection,
                name=name,
                zone_id=zone_id,
                unique_id=f"lutron_fader_zone_{zone_id}",
            ))

    if fader_lights:
        _LOGGER.info("Adding %d Lutron Fader light entities", len(fader_lights))
        async_add_entities(fader_lights, True)
    else:
        _LOGGER.info("No zones configured — re-add the integration and paste your Integration Report.")


# ----------------------------------------------------------------------
# Light states
#
#   Unavailable ──link up + level read──▶ Steady(level)      off = level 0
#   Steady / Fading ──set(level, fade)──▶ Sending(target)
#   Sending ──ack, fade=0──▶ Steady(target)
#   Sending ──ack, fade>0──▶ Fading(start, target, t0, duration)
#   Fading ──elapsed ≥ duration──▶ Steady(target)
#   Sending / Fading ──push ≠ target (Pico, app, keypad)──▶ Steady(level)
#   any ──link down──▶ Unavailable
#
# Levels are Lutron 0-100. Each state carries only its own data, so a target
# can't outlive the command or fade it belongs to.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Unavailable:
    """Hub link down, or the level hasn't been read yet."""


@dataclass(frozen=True)
class Steady:
    """At a known level."""

    level: float


@dataclass(frozen=True)
class Fading:
    """The hub accepted a timed fade; the level is interpolated until it ends."""

    start: float
    target: float
    t0: float        # time.monotonic() when the fade began
    duration: float  # seconds

    def level_at(self, now: float) -> float:
        """Return the interpolated level at monotonic time `now`."""
        progress = min((now - self.t0) / self.duration, 1.0)
        return self.start + (self.target - self.start) * progress


@dataclass(frozen=True)
class Sending:
    """A command is on its way to the hub."""

    target: float
    fade: float
    previous: Steady | Fading  # where to go back to if the hub rejects it


LightState = Unavailable | Steady | Sending | Fading


class LutronFaderLight(LightEntity):
    """Representation of a Lutron light with extended fade time support."""

    def __init__(
        self,
        hass: HomeAssistant,
        connection: LutronTelnetConnection,
        name: str,
        zone_id: int | None,
        unique_id: str,
    ):
        """Initialize the Lutron Fader light."""
        self.hass = hass
        self._connection = connection
        self._zone_id = zone_id

        # Entity attributes
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_features = LightEntityFeature.TRANSITION
        self._attr_should_poll = False

        self._state: LightState = Unavailable()
        self._tick_unsub = None  # 1s refresh timer, running only while Fading

    async def async_added_to_hass(self) -> None:
        """Register push/availability callbacks when entity is added."""
        self._connection.add_push_callback(self._handle_push)
        self._connection.add_availability_callback(self._handle_availability)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when entity is removed."""
        self._connection.remove_push_callback(self._handle_push)
        self._connection.remove_availability_callback(self._handle_availability)
        self._stop_tick()

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _transition(self, new: LightState, write: bool = True) -> None:
        """Move to `new`. The only place _state changes.

        Args:
            write: push the new state to HA; False while HA is mid-update
                (it writes the state itself afterwards)
        """
        old = self._state
        self._state = new
        _LOGGER.debug("Zone %s: %s -> %s", self._zone_id, old, new)

        if isinstance(old, Fading):
            self._stop_tick()
        if isinstance(new, Fading):
            self._tick_unsub = async_track_time_interval(
                self.hass, self._fade_tick, _FADE_REFRESH_INTERVAL
            )

        if write:
            self.async_write_ha_state()

    def _stop_tick(self) -> None:
        """Cancel the fade refresh timer if it's running."""
        if self._tick_unsub is not None:
            self._tick_unsub()
            self._tick_unsub = None

    def _display_level(self, state: LightState | None = None) -> float:
        """Return the level to show for `state` (default: the current state), 0-100."""
        state = self._state if state is None else state
        if isinstance(state, Steady):
            return state.level
        if isinstance(state, Fading):
            return state.level_at(time.monotonic())
        if isinstance(state, Sending):
            # Keep showing where we were; the hub acks in milliseconds
            return self._display_level(state.previous)
        return 0.0

    # ------------------------------------------------------------------
    # Events from the hub
    # ------------------------------------------------------------------

    @callback
    def _handle_availability(self, available: bool) -> None:
        """React to the hub connection going down or coming back."""
        if available:
            # Pushes were missed while disconnected; re-read the level
            self.async_schedule_update_ha_state(True)
        else:
            self._transition(Unavailable())

    def _handle_push(self, line: str, source: str) -> None:
        """Handle a push event from the hub."""
        # Replies to our own commands arrive as the awaited ack instead
        if source != SOURCE_EXTERNAL:
            return

        # Only ~OUTPUT,<zone>,1,<level> reports a zone level
        parts = line.split(",")
        if len(parts) < 4 or parts[0] != "~OUTPUT" or parts[2].strip() != str(OUTPUT_ACTION_ZONE_LEVEL):
            return
        try:
            zone_id = int(parts[1])
            level = float(parts[3])
        except ValueError:
            return
        if zone_id != self._zone_id:
            return

        state = self._state
        if isinstance(state, (Sending, Fading)) and abs(level - state.target) < _ECHO_TOLERANCE:
            # The hub repeating the setpoint we just sent, not a user change
            _LOGGER.debug("Zone %s echo %.2f%% of our target %.2f%%; ignoring", zone_id, level, state.target)
            return
        if isinstance(state, Unavailable) and not self._connection.available:
            return

        _LOGGER.debug("Zone %s external update: %.2f%%", zone_id, level)
        self._transition(Steady(level))

    @callback
    def _fade_tick(self, _now) -> None:
        """Called every second during a fade to push the interpolated level."""
        state = self._state
        if not isinstance(state, Fading):
            return
        if time.monotonic() - state.t0 >= state.duration:
            # The hub got there on its own
            self._transition(Steady(state.target))
        else:
            self.async_write_ha_state()

    async def async_update(self) -> None:
        """Read the level from the hub (at setup and after the link comes back)."""
        if self._zone_id is None:
            return
        try:
            level = await self._connection.query_light_level(self._zone_id)
        except HomeAssistantError as err:
            # Keep the current state; availability reflects the link
            _LOGGER.debug("Could not refresh zone %s: %s", self._zone_id, err)
            return
        # Never clobber a command in flight or a running fade
        if isinstance(self._state, (Unavailable, Steady)):
            self._transition(Steady(level), write=False)

    # ------------------------------------------------------------------
    # Entity properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Unavailable until the level is known, and while the hub link is down."""
        return not isinstance(self._state, Unavailable)

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._display_level() > 0

    @property
    def brightness(self) -> int:
        """Return the current brightness (0-255), interpolated during fades."""
        return round(self._display_level() / 100 * 255)

    # ------------------------------------------------------------------
    # Turn on / off
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light with optional fade time."""
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        # Clamp away from true-off (that's turn_off's job)
        level = min(100, max(1, round(brightness / 255 * 100)))
        await self._set(level, int(kwargs.get(ATTR_TRANSITION, 0)))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light with optional fade time."""
        await self._set(0, int(kwargs.get(ATTR_TRANSITION, 0)))

    async def _set(self, level: int, fade: int) -> None:
        """Send a level (0-100) to the hub, fading over `fade` seconds."""
        _LOGGER.info(
            "Setting %s to %d%% with fade %ds (zone: %s)",
            self._attr_name, level, fade, self._zone_id,
        )

        if self._zone_id is None:
            _LOGGER.error(
                "Zone ID not configured for %s. Please configure zone_id in YAML or use the service call.",
                self._attr_name,
            )
            return

        state = self._state
        if isinstance(state, Unavailable):
            raise NotConnected(f"{self._attr_name} is unavailable")

        # A command sent while another is in flight returns to the same settled state
        previous = state.previous if isinstance(state, Sending) else state
        sending = Sending(target=float(level), fade=float(fade), previous=previous)
        self._transition(sending)

        try:
            await self._connection.set_light_level(self._zone_id, level, fade)
        except HomeAssistantError:
            if self._state is sending:
                # HubError: the link is fine, so carry on as before. A link
                # failure: the light can't be trusted until it's read again.
                self._transition(previous if self._connection.available else Unavailable())
            raise

        if self._state is not sending:
            # Overridden (Pico, app) or superseded by a newer command while we
            # waited for the ack; that state wins
            _LOGGER.debug("Zone %s changed during command; not applying ack", self._zone_id)
            return

        if fade > 0:
            start = self._display_level(previous)
            self._transition(Fading(start=start, target=float(level), t0=time.monotonic(), duration=float(fade)))
        else:
            self._transition(Steady(float(level)))

    def set_zone_id(self, zone_id: int) -> None:
        """Set the zone ID for this light (for manual configuration)."""
        self._zone_id = zone_id
        _LOGGER.info("Zone ID set to %s for %s", zone_id, self._attr_name)

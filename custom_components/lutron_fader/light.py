"""Support for Lutron Caseta lights with fade time."""
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    PLATFORM_SCHEMA,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import voluptuous as vol

from .const import DOMAIN
from .lutron_telnet import LutronTelnetConnection

_LOGGER = logging.getLogger(__name__)

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

    # Option 2: Auto-discover from lutron_caseta (if no manual config)
    if not manual_lights:
        _LOGGER.info("No manual lights configured, attempting auto-discovery from lutron_caseta")
        
        # Get the entity registry to find existing lutron_caseta lights
        entity_registry = er.async_get(hass)

        # Find all lutron_caseta light entities
        for entity in entity_registry.entities.values():
            # Look for lutron_caseta light entities
            if entity.platform == "lutron_caseta" and entity.domain == "light":
                _LOGGER.info("Found lutron_caseta light: %s", entity.entity_id)

                # Create a fader version of this light
                # Note: Zone ID will need to be set manually via service call
                fader_light = LutronFaderLight(
                    hass=hass,
                    connection=connection,
                    name=f"{entity.original_name or entity.entity_id} Fader",
                    zone_id=None,  # Will need to be set manually
                    unique_id=f"{entity.unique_id}_fader",
                    original_entity_id=entity.entity_id,
                )
                fader_lights.append(fader_light)

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
    """Set up Lutron Fader lights from a config entry (for future UI config)."""
    _LOGGER.info("Setting up Lutron Fader lights from config entry")

    # Get our telnet connection
    connection_data = hass.data[DOMAIN][config_entry.entry_id]
    connection: LutronTelnetConnection = connection_data["connection"]

    # Get the entity registry to find existing lutron_caseta lights
    entity_registry = er.async_get(hass)

    # Find all lutron_caseta light entities
    fader_lights = []

    for entity in entity_registry.entities.values():
        # Look for lutron_caseta light entities
        if entity.platform == "lutron_caseta" and entity.domain == "light":
            _LOGGER.info("Found lutron_caseta light: %s", entity.entity_id)

            # Create a fader version of this light
            fader_light = LutronFaderLight(
                hass=hass,
                connection=connection,
                name=f"{entity.original_name or entity.entity_id} Fader",
                zone_id=None,  # Will need to be configured
                unique_id=f"{entity.unique_id}_fader",
                original_entity_id=entity.entity_id,
            )
            fader_lights.append(fader_light)

    if fader_lights:
        _LOGGER.info("Adding %d Lutron Fader light entities", len(fader_lights))
        async_add_entities(fader_lights, True)
    else:
        _LOGGER.warning(
            "No lutron_caseta lights found. Make sure lutron_caseta integration is set up first."
        )


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
        self._attr_should_poll = True

        # State tracking
        self._attr_is_on = False
        self._attr_brightness = 0

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
        """Return the brightness of this light (0-255)."""
        return self._attr_brightness if self._attr_is_on else 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light with optional fade time."""
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        transition = kwargs.get(ATTR_TRANSITION, 0)

        # Convert brightness from 0-255 to 0-100
        lutron_brightness = int((brightness / 255.0) * 100)

        # Convert transition to seconds
        fade_time = int(transition)

        _LOGGER.info(
            "Turning on %s to %s%% with fade time %s seconds (zone: %s)",
            self._attr_name,
            lutron_brightness,
            fade_time,
            self._zone_id,
        )

        if self._zone_id is None:
            _LOGGER.error(
                "Zone ID not configured for %s. Please configure zone_id in YAML or use the service call.",
                self._attr_name,
            )
            return

        # Send the telnet command
        success = await self._connection.set_light_level(
            self._zone_id,
            lutron_brightness,
            fade_time,
        )

        if success:
            self._attr_is_on = True
            self._attr_brightness = brightness
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light with optional fade time."""
        transition = kwargs.get(ATTR_TRANSITION, 0)
        fade_time = int(transition)

        _LOGGER.info(
            "Turning off %s with fade time %s seconds (zone: %s)",
            self._attr_name,
            fade_time,
            self._zone_id,
        )

        if self._zone_id is None:
            _LOGGER.error(
                "Zone ID not configured for %s. Please configure zone_id in YAML or use the service call.",
                self._attr_name,
            )
            return

        # Send the telnet command
        success = await self._connection.set_light_level(
            self._zone_id,
            0,
            fade_time,
        )

        if success:
            self._attr_is_on = False
            self._attr_brightness = 0
            self.async_write_ha_state()

    def set_zone_id(self, zone_id: int) -> None:
        """Set the zone ID for this light (for manual configuration)."""
        self._zone_id = zone_id
        _LOGGER.info("Zone ID set to %s for %s", zone_id, self._attr_name)
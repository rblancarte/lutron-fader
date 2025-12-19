"""Lutron Fader integration - adds fade time support to Lutron Caseta."""
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_BRIGHTNESS,
    ATTR_FADE_TIME,
    ATTR_ZONE_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
    SERVICE_FADE_TO,
    SERVICE_LONG_FADE,
)
from .lutron_telnet import LutronTelnetConnection

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["light"]

# YAML configuration schema
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): cv.string,
                vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Lutron Fader component from YAML."""
    hass.data.setdefault(DOMAIN, {})
    
    # If no YAML config, just return (maybe using config flow instead)
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
    
    # Create Telnet connection
    connection = LutronTelnetConnection(
        host=conf[CONF_HOST],
        port=conf[CONF_PORT],
        username=conf[CONF_USERNAME],
        password=conf[CONF_PASSWORD],
    )
    
    # Test connection
    _LOGGER.info("Testing connection to Lutron hub at %s", conf[CONF_HOST])
    if not await connection.connect():
        _LOGGER.error("Failed to connect to Lutron hub at %s", conf[CONF_HOST])
        return False
    
    _LOGGER.info("Successfully connected to Lutron hub")
    await connection.disconnect()
    
    # Store connection in hass.data with a special key for YAML config
    hass.data[DOMAIN]["yaml_connection"] = connection
    hass.data[DOMAIN]["yaml_config"] = conf
    
    # Set up the light platform via discovery (for YAML)
    await hass.helpers.discovery.async_load_platform(
        Platform.LIGHT, DOMAIN, {}, config
    )
    
    # Register services
    await _async_setup_services(hass, connection)
    
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lutron Fader from a config entry (UI-based config)."""
    # Create the telnet connection
    connection = LutronTelnetConnection(
        host=entry.data["host"],
        port=entry.data.get("port", 23),
        username=entry.data.get("username", "lutron"),
        password=entry.data.get("password", "integration"),
    )

    # Store the connection in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "connection": connection,
        "entry": entry,
    }

    # Register services (if not already registered from YAML)
    if "yaml_connection" not in hass.data[DOMAIN]:
        await _async_setup_services(hass, connection)

    # Forward the setup to the light platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Disconnect from the hub
    connection_data = hass.data[DOMAIN].pop(entry.entry_id)
    connection = connection_data["connection"]
    await connection.disconnect()

    # Unregister services (only if this is the last entry and no YAML config)
    if not hass.data[DOMAIN] or (
        len(hass.data[DOMAIN]) == 1 and "yaml_connection" in hass.data[DOMAIN]
    ):
        hass.services.async_remove(DOMAIN, SERVICE_FADE_TO)
        hass.services.async_remove(DOMAIN, SERVICE_LONG_FADE)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_setup_services(
    hass: HomeAssistant, connection: LutronTelnetConnection
) -> None:
    """Set up the custom services for Lutron Fader."""
    
    async def handle_fade_to(call: ServiceCall) -> None:
        """Handle the fade_to service call."""
        zone_id = call.data[ATTR_ZONE_ID]
        brightness = call.data[ATTR_BRIGHTNESS]
        fade_time = call.data.get(ATTR_FADE_TIME, 0)

        _LOGGER.info(
            "Fade service called: zone=%s, brightness=%s, fade_time=%s",
            zone_id,
            brightness,
            fade_time,
        )

        await connection.set_light_level(zone_id, brightness, fade_time)

    async def handle_long_fade(call: ServiceCall) -> None:
        """Handle the long_fade service call."""
        zone_id = call.data[ATTR_ZONE_ID]
        brightness = call.data[ATTR_BRIGHTNESS]
        duration = call.data.get("duration", 1800)  # Default 30 minutes

        _LOGGER.info(
            "Long fade service called: zone=%s, brightness=%s, duration=%s seconds",
            zone_id,
            brightness,
            duration,
        )

        await connection.set_light_level(zone_id, brightness, duration)

    # Register services with schemas for validation
    hass.services.async_register(
        DOMAIN,
        SERVICE_FADE_TO,
        handle_fade_to,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ZONE_ID): cv.positive_int,
                vol.Required(ATTR_BRIGHTNESS): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100)
                ),
                vol.Optional(ATTR_FADE_TIME, default=0): cv.positive_int,
            }
        ),
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_LONG_FADE,
        handle_long_fade,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ZONE_ID): cv.positive_int,
                vol.Required(ATTR_BRIGHTNESS): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100)
                ),
                vol.Optional("duration", default=1800): cv.positive_int,
            }
        ),
    )
    
    _LOGGER.info("Lutron Fader services registered")
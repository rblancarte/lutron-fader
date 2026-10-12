"""Lutron Fader integration - adds fade time support to Lutron Caseta."""
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, discovery, entity_registry as er
from homeassistant.helpers.typing import ConfigType



from .config_flow import parse_integration_report
from .const import (
    ATTR_BRIGHTNESS,
    ATTR_ENTITY_ID,
    ATTR_FADE_TIME,
    ATTR_REPORT_TEXT,
    ATTR_ZONE_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_ZONE_MAPPINGS,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
    SERVICE_FADE_TO,
    SERVICE_PARSE_REPORT,
    SERVICE_DISCOVER_ENTITIES,
    SERVICE_AUTO_CONFIGURE,
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
                vol.Optional(CONF_ZONE_MAPPINGS, default={}): {
                    cv.string: cv.positive_int
                },
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

    # Automatically pick the first zone from zone_mappings for ping
    zone_mappings = conf.get(CONF_ZONE_MAPPINGS, {})
    ping_zone = 1  # Default to zone 1
    if zone_mappings:
        # Use the first zone from zone_mappings
        ping_zone = next(iter(zone_mappings.values()))
        _LOGGER.info("Using zone %s for keep-alive pings", ping_zone)

    # Create Telnet connection
    connection = LutronTelnetConnection(
        host=conf[CONF_HOST],
        port=conf[CONF_PORT],
        username=conf[CONF_USERNAME],
        password=conf[CONF_PASSWORD],
        ping_zone=ping_zone,
    )
    
    # Test connection
    _LOGGER.info("Testing connection to Lutron hub at %s", conf[CONF_HOST])
    if not await connection.connect():
        _LOGGER.error("Failed to connect to Lutron hub at %s", conf[CONF_HOST])
        return False
    
    # Stay connected so push updates (Pico, app) flow from boot
    _LOGGER.info("Successfully connected to Lutron hub")

    # Store connection in hass.data with a special key for YAML config
    hass.data[DOMAIN]["yaml_connection"] = connection
    hass.data[DOMAIN]["yaml_config"] = conf
    hass.data[DOMAIN]["zone_mappings"] = conf.get(CONF_ZONE_MAPPINGS, {})
    
    # Set up the light platform via discovery
 
    await discovery.async_load_platform(
        hass, "light", DOMAIN, {}, config
    )
    
    # Register services
    await _async_setup_services(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lutron Fader from a config entry (UI-based config)."""
    # Create the telnet connection
    connection = LutronTelnetConnection(
        host=entry.data["host"],
        port=entry.data.get("port", 23),
        username=entry.data.get("username", "lutron"),
        password=entry.data.get("password", "integration"),
        ping_zone=entry.data.get("ping_zone", 1),
    )

    # Store the connection in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "connection": connection,
        "entry": entry,
    }

    # Register services (no-op if YAML or another entry already did)
    await _async_setup_services(hass)

    # Forward the setup to the light platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Connect eagerly so the reader loop starts at boot
    await connection.connect()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    # Disconnect from the hub
    connection_data = hass.data[DOMAIN].pop(entry.entry_id)
    await connection_data["connection"].disconnect()

    # Unregister services only if no other entry and no YAML config still needs them
    other_entries = any(
        e.entry_id in hass.data[DOMAIN] for e in hass.config_entries.async_entries(DOMAIN)
    )
    if not other_entries and "yaml_connection" not in hass.data[DOMAIN]:
        for svc in (SERVICE_FADE_TO, SERVICE_PARSE_REPORT, SERVICE_DISCOVER_ENTITIES, SERVICE_AUTO_CONFIGURE):
            hass.services.async_remove(DOMAIN, svc)

    return True


def _get_connection(hass: HomeAssistant) -> LutronTelnetConnection | None:
    """Return the live hub connection (YAML first, then any loaded config entry)."""
    domain_data = hass.data.get(DOMAIN, {})
    if "yaml_connection" in domain_data:
        return domain_data["yaml_connection"]
    for entry in hass.config_entries.async_entries(DOMAIN):
        entry_data = domain_data.get(entry.entry_id)
        if entry_data:
            return entry_data["connection"]
    return None


def _fader_entity_for_zone(registry: er.EntityRegistry, zone_id: int) -> str | None:
    """Return this integration's light entity for a zone, if one exists."""
    # Config-entry lights use lutron_fader_zone_<id>; YAML lights use lutron_fader_<id>
    for unique_id in (f"{DOMAIN}_zone_{zone_id}", f"{DOMAIN}_{zone_id}"):
        entity_id = registry.async_get_entity_id("light", DOMAIN, unique_id)
        if entity_id:
            return entity_id
    return None


def _zone_from_fader_unique_id(unique_id: str) -> int | None:
    """Parse the zone ID out of a lutron_fader light's unique_id."""
    suffix = unique_id.rsplit("_", 1)[-1]
    return int(suffix) if suffix.isdigit() else None


async def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up the custom services for Lutron Fader (once per HA instance)."""
    if hass.services.has_service(DOMAIN, SERVICE_FADE_TO):
        return

    def resolve_target(call: ServiceCall) -> tuple[int, str | None]:
        """Return (zone_id, lutron_fader light entity_id or None) for a service call."""
        registry = er.async_get(hass)

        # If zone_id is provided directly, use it
        if ATTR_ZONE_ID in call.data:
            zone_id = call.data[ATTR_ZONE_ID]
            return zone_id, _fader_entity_for_zone(registry, zone_id)

        if ATTR_ENTITY_ID not in call.data:
            raise ServiceValidationError("Either zone_id or entity_id must be provided")

        entity_id = call.data[ATTR_ENTITY_ID]

        # One of our own lights: the zone is in its unique_id
        reg_entry = registry.async_get(entity_id)
        if reg_entry and reg_entry.platform == DOMAIN:
            zone_id = _zone_from_fader_unique_id(reg_entry.unique_id)
            if zone_id is not None:
                return zone_id, entity_id

        # A lutron_caseta light: look it up in zone_mappings from auto_configure_from_report
        zone_mappings = {}
        for entry in hass.config_entries.async_entries(DOMAIN):
            zone_mappings.update(entry.data.get("zone_mappings", {}))

        if entity_id in zone_mappings:
            zone_id = zone_mappings[entity_id]
            _LOGGER.debug("Resolved entity_id %s to zone_id %s", entity_id, zone_id)
            return zone_id, _fader_entity_for_zone(registry, zone_id)

        raise ServiceValidationError(
            f"Entity {entity_id} is not a Lutron Fader light and is not in the zone "
            "mappings. Use a Lutron Fader light, pass zone_id, or run "
            "auto_configure_from_report first."
        )

    async def handle_fade_to(call: ServiceCall) -> None:
        """Handle the fade_to service call."""
        zone_id, fader_entity_id = resolve_target(call)
        brightness = call.data[ATTR_BRIGHTNESS]
        fade_time = call.data.get(ATTR_FADE_TIME, 0)

        _LOGGER.info(
            "Fade service called: zone=%s, brightness=%s, fade_time=%s, entity=%s",
            zone_id,
            brightness,
            fade_time,
            fader_entity_id,
        )

        if fader_entity_id:
            # Route through the entity so its state and fade tracking stay in sync
            if brightness == 0:
                await hass.services.async_call(
                    "light", "turn_off",
                    {ATTR_ENTITY_ID: fader_entity_id, "transition": fade_time},
                    blocking=True,
                )
            else:
                await hass.services.async_call(
                    "light", "turn_on",
                    {ATTR_ENTITY_ID: fader_entity_id, "brightness_pct": brightness, "transition": fade_time},
                    blocking=True,
                )
            return

        connection = _get_connection(hass)
        if connection is None:
            raise HomeAssistantError("Lutron Fader has no hub connection")

        success = await connection.set_light_level(zone_id, brightness, fade_time)
        if not success:
            raise HomeAssistantError(
                f"Lutron hub did not acknowledge fade command for zone {zone_id}"
            )

    async def handle_discover_lutron_entities(call: ServiceCall) -> None:
        """Discover Lutron Caseta entities from the official integration."""
        entity_registry = er.async_get(hass)

        _LOGGER.info("=" * 60)
        _LOGGER.info("SCANNING FOR LUTRON CASETA ENTITIES")
        _LOGGER.info("=" * 60)

        # Get zone mappings from hass.data if available (from Integration Report)
        zone_mappings = hass.data.get(DOMAIN, {}).get("zone_mappings", {})

        # Create a reverse lookup: zone_id -> zone_name from Integration Report
        zone_id_to_name = {}
        for safe_name, zone_id in zone_mappings.items():
            # This is the mapping from parse_integration_report
            zone_id_to_name[zone_id] = safe_name

        lutron_lights = []
        entity_to_zone_mapping = {}

        for entity in entity_registry.entities.values():
            # Check if it belongs to the lutron_caseta integration
            if entity.platform == "lutron_caseta":
                # Get the entity state
                state = hass.states.get(entity.entity_id)

                if state:
                    entity_name = state.attributes.get("friendly_name", "Unknown")
                    entity_info = {
                        "entity_id": entity.entity_id,
                        "name": entity_name,
                        "unique_id": entity.unique_id,
                        "domain": state.domain,
                        "device_class": state.attributes.get("device_class"),
                        "supported_features": state.attributes.get("supported_features"),
                        "has_brightness": "brightness" in state.attributes,
                        "zone_id": None,
                    }

                    # Try to match entity name with Integration Report zones
                    for zone_id, zone_name in zone_id_to_name.items():
                        # Convert zone_name back to friendly format for comparison
                        # zone_name is like "master_bedroom_ron_lamp"
                        # entity_name is like "Master Bedroom Ron Lamp"
                        friendly_zone_name = zone_name.replace('_', ' ').title()

                        if entity_name.lower() == friendly_zone_name.lower():
                            entity_info["zone_id"] = zone_id
                            entity_to_zone_mapping[entity.entity_id] = zone_id
                            break

                    _LOGGER.info("Found entity: %s", entity.entity_id)
                    _LOGGER.info("  Name: %s", entity_info["name"])
                    _LOGGER.info("  Domain: %s", entity_info["domain"])
                    _LOGGER.info("  Unique ID: %s", entity_info["unique_id"])
                    _LOGGER.info("  Has brightness: %s", entity_info["has_brightness"])
                    _LOGGER.info("  Zone ID: %s", entity_info["zone_id"] if entity_info["zone_id"] else "NOT MATCHED")
                    _LOGGER.info("  Device class: %s", entity_info["device_class"])
                    _LOGGER.info("  State: %s", state.state)
                    _LOGGER.info("")

                    if state.domain == "light" and entity_info["has_brightness"]:
                        lutron_lights.append(entity_info)

        _LOGGER.info("=" * 60)
        _LOGGER.info("FOUND %d DIMMABLE LUTRON LIGHTS", len(lutron_lights))

        matched_count = sum(1 for light in lutron_lights if light["zone_id"] is not None)
        _LOGGER.info("MATCHED %d LIGHTS TO ZONE IDS", matched_count)
        _LOGGER.info("=" * 60)

        # Log the mapping
        if entity_to_zone_mapping:
            _LOGGER.info("")
            _LOGGER.info("ENTITY TO ZONE MAPPING:")
            for entity_id, zone_id in sorted(entity_to_zone_mapping.items(), key=lambda x: x[1]):
                _LOGGER.info("  %s -> Zone %s", entity_id, zone_id)
            _LOGGER.info("")

        # Create a notification
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Lutron Entities Discovered",
                "message": f"Found {len(lutron_lights)} dimmable Lutron lights. Matched {matched_count} to zone IDs. Check the logs for details.",
            },
        )

    async def handle_parse_integration_report(call: ServiceCall) -> None:
        """Handle the parse_integration_report service call."""
        report_text = call.data[ATTR_REPORT_TEXT]

        _LOGGER.info("Parsing Integration Report...")

        zones = parse_integration_report(report_text)
        for zone_id, zone_name in zones.items():
            _LOGGER.info("Found zone %s: %s", zone_id, zone_name)

        # Log the YAML configuration
        if zones:
            _LOGGER.info("=" * 60)
            _LOGGER.info("DISCOVERED ZONES - Add to your configuration.yaml:")
            _LOGGER.info("=" * 60)
            _LOGGER.info("lutron_fader:")
            _LOGGER.info("  host: YOUR_HUB_IP")
            _LOGGER.info("  zone_mappings:")
            for zone_id, zone_name in sorted(zones.items()):
                # Create a safe key from the zone name
                safe_name = zone_name.lower().replace(' ', '_').replace('-', '_')
                safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
                _LOGGER.info("    %s: %s  # %s", safe_name, zone_id, zone_name)
            _LOGGER.info("=" * 60)

            # Create a persistent notification for the user
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Lutron Integration Report Parsed",
                    "message": f"Found {len(zones)} zones. Check the logs for the YAML configuration to add to configuration.yaml.",
                },
            )
        else:
            _LOGGER.warning("No zones found in the Integration Report")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Lutron Integration Report - No Zones Found",
                    "message": "Could not parse any zones from the report. Please check the format and try again.",
                },
            )

    # Register services with schemas for validation
    hass.services.async_register(
        DOMAIN,
        SERVICE_FADE_TO,
        handle_fade_to,
        schema=vol.Schema(
            {
                vol.Exclusive(ATTR_ZONE_ID, "zone_or_entity"): cv.positive_int,
                vol.Exclusive(ATTR_ENTITY_ID, "zone_or_entity"): cv.entity_id,
                vol.Required(ATTR_BRIGHTNESS): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100)
                ),
                vol.Optional(ATTR_FADE_TIME, default=0): cv.positive_int,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PARSE_REPORT,
        handle_parse_integration_report,
        schema=vol.Schema(
            {
                vol.Required(ATTR_REPORT_TEXT): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DISCOVER_ENTITIES,
        handle_discover_lutron_entities,
        schema=vol.Schema({}),
    )

    async def handle_auto_configure_from_report(call: ServiceCall) -> None:
        """Parse Integration Report AND match entities in one step."""
        report_text = call.data[ATTR_REPORT_TEXT]

        _LOGGER.info("=" * 60)
        _LOGGER.info("AUTO-CONFIGURING FROM INTEGRATION REPORT")
        _LOGGER.info("=" * 60)

        # STEP 1: Parse the Integration Report
        zones = parse_integration_report(report_text)

        if not zones:
            _LOGGER.error("No zones found in Integration Report")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Auto-Configure Failed",
                    "message": "Could not parse any zones from the Integration Report.",
                },
            )
            return

        _LOGGER.info("Found %d zones in Integration Report", len(zones))

        # STEP 2: Match with Lutron Caseta entities
        entity_registry = er.async_get(hass)
        entity_to_zone_mapping = {}
        matched_lights = []

        for entity in entity_registry.entities.values():
            if entity.platform == "lutron_caseta":
                state = hass.states.get(entity.entity_id)

                if state and state.domain == "light" and "brightness" in state.attributes:
                    entity_name = state.attributes.get("friendly_name", "")

                    # Try to match with zones
                    for zone_id, zone_name in zones.items():
                        if entity_name.lower() == zone_name.lower():
                            entity_to_zone_mapping[entity.entity_id] = zone_id
                            matched_lights.append({
                                "entity_id": entity.entity_id,
                                "name": entity_name,
                                "zone_id": zone_id,
                            })
                            break

        # STEP 3: Save zone mappings to config entry and update ping_zone
        # Find the config entry for this integration
        config_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            config_entry = entry
            break  # Use the first (and likely only) entry

        if config_entry and entity_to_zone_mapping:
            # Store the zone mappings in the config entry data
            new_data = {**config_entry.data, "zone_mappings": entity_to_zone_mapping}

            # Set ping_zone to the first matched zone ID
            first_zone_id = min(entity_to_zone_mapping.values())
            new_data["ping_zone"] = first_zone_id

            hass.config_entries.async_update_entry(config_entry, data=new_data)
            _LOGGER.info("Saved zone mappings to config entry and set ping_zone to %d", first_zone_id)

            # Update the connection's ping zone
            connection_data = hass.data[DOMAIN].get(config_entry.entry_id)
            if connection_data:
                connection_data["connection"].ping_zone = first_zone_id
                _LOGGER.info("Updated active connection ping_zone to %d", first_zone_id)

        # STEP 4: Log results
        _LOGGER.info("")
        _LOGGER.info("=" * 60)
        _LOGGER.info("AUTO-CONFIGURATION RESULTS")
        _LOGGER.info("=" * 60)
        _LOGGER.info("Total zones in report: %d", len(zones))
        _LOGGER.info("Dimmable lights found: %d", len([e for e in entity_registry.entities.values() if e.platform == "lutron_caseta" and hass.states.get(e.entity_id) and hass.states.get(e.entity_id).domain == "light"]))
        _LOGGER.info("Successfully matched: %d", len(matched_lights))
        _LOGGER.info("")

        if matched_lights:
            _LOGGER.info("MATCHED ENTITIES:")
            for light in sorted(matched_lights, key=lambda x: x["zone_id"]):
                _LOGGER.info("  ✓ Zone %d: %s (%s)", light["zone_id"], light["name"], light["entity_id"])
            _LOGGER.info("")

        # Find unmatched zones
        matched_zone_ids = set(light["zone_id"] for light in matched_lights)
        unmatched_zones = {zid: zname for zid, zname in zones.items() if zid not in matched_zone_ids}

        if unmatched_zones:
            _LOGGER.warning("UNMATCHED ZONES (no corresponding HA entity found):")
            for zone_id, zone_name in sorted(unmatched_zones.items()):
                _LOGGER.warning("  ✗ Zone %d: %s", zone_id, zone_name)
            _LOGGER.info("")

        _LOGGER.info("=" * 60)

        # Create notification
        save_status = "Saved to config." if config_entry and entity_to_zone_mapping else "Not saved (no config entry found)."
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Lutron Auto-Configuration Complete",
                "message": f"Found {len(zones)} zones. Matched {len(matched_lights)} lights. {save_status} Check logs for details.",
            },
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_AUTO_CONFIGURE,
        handle_auto_configure_from_report,
        schema=vol.Schema(
            {
                vol.Required(ATTR_REPORT_TEXT): cv.string,
            }
        ),
    )

    _LOGGER.info("Lutron Fader services registered")
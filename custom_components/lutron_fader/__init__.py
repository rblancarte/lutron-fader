"""Lutron Fader: shows the progress of native Lutron light fades.

Lutron hubs report only the *target* of a fade, so Home Assistant shows a
light's end value the moment a fade starts. This integration never commands
lights or talks to the hub. It watches Home Assistant for fades sent to Lutron
lights (any light.turn_on / light.turn_off with a transition, from a card,
automation, script or voice) and publishes each fade's progress as a
sensor.<light>_fade.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import LightEntityFeature, brightness_supported
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ENTITY_MATCH_ALL, EVENT_CALL_SERVICE, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids

from .const import DOMAIN, TRACKED_PLATFORMS

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.SENSOR]

ATTR_TRANSITION = "transition"
LIGHT_SERVICES = ("turn_on", "turn_off")


def is_fadeable(entry: er.RegistryEntry) -> bool:
    """Return True for an enabled Lutron light that can dim and fade.

    On/off-only lights (a switch exposed as a light) or lights without
    transition support have no fade to show.
    """
    if entry.domain != "light" or entry.platform not in TRACKED_PLATFORMS or entry.disabled:
        return False
    color_modes = (entry.capabilities or {}).get("supported_color_modes")
    return bool(entry.supported_features & LightEntityFeature.TRANSITION) and brightness_supported(color_modes)


class FadeRouter:
    """Finds the tracked lights and routes fade requests to their sensors."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.lights: dict[str, str] = {}  # light entity_id -> entity registry id
        self.sensors: dict[str, Any] = {}  # light entity_id -> FadeSensor

    def discover(self) -> None:
        """Find every Lutron light that can fade."""
        registry = er.async_get(self.hass)
        self.lights = {
            entry.entity_id: entry.id for entry in registry.entities.values() if is_fadeable(entry)
        }

    @callback
    def on_service_call(self, event: Event) -> None:
        """Route a light.turn_on/turn_off with a transition to the targeted lights."""
        data = event.data.get("service_data") or {}
        try:
            transition = float(data[ATTR_TRANSITION])
        except (KeyError, TypeError, ValueError):
            return

        selection = TargetSelection(data)
        if ENTITY_MATCH_ALL in selection.entity_ids:
            targets = set(self.sensors)
        else:
            # Resolves areas, devices, floors and labels to entities
            selected = async_extract_referenced_entity_ids(self.hass, selection)
            targets = (selected.referenced | selected.indirectly_referenced) & self.sensors.keys()

        for light_id in targets:
            self.sensors[light_id].handle_call(transition, event.context.id)


@callback
def _is_light_fade(event_data: dict[str, Any]) -> bool:
    """Cheap pre-filter run on every service call in HA."""
    return (
        event_data.get("domain") == "light"
        and event_data.get("service") in LIGHT_SERVICES
        and ATTR_TRANSITION in (event_data.get("service_data") or {})
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up fade tracking for every Lutron light."""
    router = FadeRouter(hass)
    router.discover()
    entry.runtime_data = router

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_CALL_SERVICE, router.on_service_call, event_filter=_is_light_fade)
    )

    @callback
    def on_registry_updated(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """Reload when the set of fadeable lights may have changed."""
        data = event.data
        entity_id = data["entity_id"]
        if data["action"] == "remove":
            relevant = entity_id in router.lights
        else:
            reg_entry = er.async_get(hass).async_get(entity_id)
            fadeable = reg_entry is not None and is_fadeable(reg_entry)
            # Added, removed from tracking, renamed, or newly fadeable (its
            # capabilities can arrive after the light first registers)
            relevant = (
                fadeable != (entity_id in router.lights)
                or data.get("old_entity_id") in router.lights
            )
        if relevant:
            _LOGGER.debug("Tracked light %s changed (%s); reloading", entity_id, data["action"])
            hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def is_light_registry_event(data: dict[str, Any]) -> bool:
        return data["entity_id"].startswith("light.") or str(data.get("old_entity_id", "")).startswith("light.")

    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, on_registry_updated, event_filter=is_light_registry_event
        )
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop tracking."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate from 1.x (Telnet lights) to 2.x (fade tracker)."""
    if entry.version == 1:
        # 1.x created its own light per zone over Telnet; those are gone now
        registry = er.async_get(hass)
        old_lights = [
            reg_entry.entity_id
            for reg_entry in registry.entities.values()
            if reg_entry.platform == DOMAIN and reg_entry.domain == "light"
        ]
        for entity_id in old_lights:
            registry.async_remove(entity_id)
        hass.config_entries.async_update_entry(entry, data={}, title="Lutron Fader", version=2)
        _LOGGER.info("Migrated Lutron Fader to fade tracking; removed %d old lights", len(old_lights))
    return True

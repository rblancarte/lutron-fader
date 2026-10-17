"""Fade-progress sensors: one per tracked Lutron light."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_OFF
from homeassistant.core import (
    Event,
    EventStateChangedData,
    EventStateReportedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_state_report_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from .const import TICK_INTERVAL
from .tracker import FadeTracker, Fading, Idle

_LOGGER = logging.getLogger(__name__)

ATTR_LIGHT_ENTITY_ID = "light_entity_id"


def light_level(state: State | None) -> float | None:
    """Return a light's brightness (0-255; 0 when off), or None if unavailable."""
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    if state.state == STATE_OFF:
        return 0.0
    brightness = state.attributes.get("brightness")
    return 255.0 if brightness is None else float(brightness)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a fade sensor for every tracked light found at setup."""
    router = entry.runtime_data
    sensors = [FadeSensor(hass, light_id, reg_id) for light_id, reg_id in router.lights.items()]
    for sensor in sensors:
        router.sensors[sensor.light_entity_id] = sensor
    _LOGGER.info("Tracking fades for %d lights", len(sensors))
    async_add_entities(sensors)


class _FadeExtraData(ExtraStoredData):
    """The running fade, saved across restarts."""

    def __init__(self, fade: dict[str, Any]) -> None:
        self.fade = fade

    def as_dict(self) -> dict[str, Any]:
        return self.fade


class FadeSensor(SensorEntity, RestoreEntity):
    """Shows whether a light is fading and, if so, where it is in the fade."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "fading"]
    _attr_icon = "mdi:transition"
    _attr_translation_key = "fade"
    # Changes every second during a fade; keep it out of history
    _unrecorded_attributes = frozenset({
        "brightness", "brightness_pct", "start_pct", "target_pct",
        "started_at", "ends_at", "progress",
    })

    def __init__(self, hass: HomeAssistant, light_entity_id: str, light_registry_id: str) -> None:
        self.hass = hass
        self.light_entity_id = light_entity_id
        self._tracker = FadeTracker()
        self._tick_unsub = None

        state = hass.states.get(light_entity_id)
        name = state.name if state else light_entity_id.split(".", 1)[1].replace("_", " ").title()
        self._attr_name = f"{name} Fade"
        self._attr_unique_id = f"{light_registry_id}_fade"
        # light.<x> -> sensor.<x>_fade. Set explicitly: HA would otherwise
        # prefix the area, doubling it (sensor.bedroom_bedroom_lamp_fade)
        self.entity_id = f"sensor.{light_entity_id.split('.', 1)[1]}_fade"
        # Sit on the light's own device (as HA's statistics helper does)
        self.device_entry = async_entity_id_to_device(hass, light_entity_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Restore a fade in progress and start watching the light."""
        await super().async_added_to_hass()

        extra = await self.async_get_last_extra_data()
        fade = extra.as_dict() if extra else {}
        if fade:
            try:
                self._tracker.restore(
                    start=fade["start"],
                    target=fade["target"],
                    started_at=datetime.fromisoformat(fade["started_at"]),
                    ends_at=datetime.fromisoformat(fade["ends_at"]),
                    light_level=light_level(self.hass.states.get(self.light_entity_id)),
                    now=dt_util.utcnow(),
                )
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.debug("Ignoring unreadable saved fade for %s: %s", self.light_entity_id, err)
            if self._tracker.fading:
                _LOGGER.debug("Resumed fade for %s: %s", self.light_entity_id, self._tracker.state)
        self._sync_tick()

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self.light_entity_id], self._on_light_changed)
        )
        # Unchanged re-reports matter too: see FadeTracker.on_light_report
        self.async_on_remove(
            async_track_state_report_event(self.hass, [self.light_entity_id], self._on_light_reported)
        )

    async def async_will_remove_from_hass(self) -> None:
        self._stop_tick()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @callback
    def handle_call(self, transition: float, context_id: str | None) -> None:
        """A light.turn_on/turn_off with a transition was sent to this light."""
        level = light_level(self.hass.states.get(self.light_entity_id))
        if level is None:
            return
        self._tracker.on_call(level, transition, context_id, dt_util.utcnow())
        _LOGGER.debug("%s: fade requested (%ss): %s", self.light_entity_id, transition, self._tracker.state)
        self._sync_tick()
        self.async_write_ha_state()

    @callback
    def _on_light_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        level = light_level(new_state)
        before = self._tracker.state
        if self._tracker.on_light_state(level, dt_util.utcnow()):
            _LOGGER.debug(
                "%s: %s -> %s (light now %s, context %s)",
                self.light_entity_id, before, self._tracker.state, level,
                new_state.context.id if new_state else None,
            )
            self._sync_tick()
            self.async_write_ha_state()

    @callback
    def _on_light_reported(self, event: Event[EventStateReportedData]) -> None:
        if not self._tracker.fading:
            return
        new_state = event.data["new_state"]
        if self._tracker.on_light_report(light_level(new_state), dt_util.utcnow()):
            _LOGGER.debug(
                "%s: light re-reported its target (context %s); fade overridden",
                self.light_entity_id, new_state.context.id if new_state else None,
            )
            self._sync_tick()
            self.async_write_ha_state()

    @callback
    def _tick(self, _now: datetime) -> None:
        if self._tracker.on_tick(dt_util.utcnow()):
            _LOGGER.debug("%s: fade ended", self.light_entity_id)
            self._sync_tick()
        self.async_write_ha_state()

    def _sync_tick(self) -> None:
        """Run the refresh timer exactly while a fade is pending or running."""
        active = not isinstance(self._tracker.state, Idle)
        if active and self._tick_unsub is None:
            self._tick_unsub = async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=TICK_INTERVAL)
            )
        elif not active:
            self._stop_tick()

    def _stop_tick(self) -> None:
        if self._tick_unsub is not None:
            self._tick_unsub()
            self._tick_unsub = None

    # ------------------------------------------------------------------
    # Entity properties
    # ------------------------------------------------------------------

    @property
    def native_value(self) -> str:
        return self._tracker.state_name()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_LIGHT_ENTITY_ID: self.light_entity_id, **self._tracker.attributes(dt_util.utcnow())}

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        state = self._tracker.state
        if isinstance(state, Fading):
            return _FadeExtraData({
                "start": state.start,
                "target": state.target,
                "started_at": state.started_at.isoformat(),
                "ends_at": state.ends_at.isoformat(),
            })
        return _FadeExtraData({})

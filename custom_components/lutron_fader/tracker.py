"""Fade tracking: the per-light state machine.

Lutron hubs (and most bridges) report only the *target* of a native fade, so
Home Assistant shows the end value the moment a fade starts. A FadeTracker
watches one light: it learns of a fade from the service call that started it,
confirms the target from the light's next state change, and calculates the
level along the way.

    Idle ──call with transition──▶ Pending(start, started_at, duration)
    Pending ──light reports a new level──▶ Fading(start, target, started_at, ends_at)
    Pending ──light already there, or no change within the timeout──▶ Idle
    Fading ──now ≥ ends_at──▶ Idle
    Fading ──light changes to ≠ target, or unavailable (override)──▶ Idle
    Fading ──new call with transition──▶ Pending(start = current calculated level)

No Home Assistant imports, so it can be tested on its own. Levels are HA
brightness (0-255); times are timezone-aware wall clock, so a fade can be
restored after a restart.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .const import ECHO_TOLERANCE, PENDING_TIMEOUT


@dataclass(frozen=True)
class Idle:
    """No fade being tracked."""


@dataclass(frozen=True)
class Pending:
    """A fade was requested; waiting for the light to report its target."""

    start: float          # level when the call was made
    started_at: datetime
    duration: float       # seconds
    context_id: str | None  # the call's context, kept for diagnostics


@dataclass(frozen=True)
class Fading:
    """The light accepted a fade; its level is calculated until it ends."""

    start: float
    target: float
    started_at: datetime
    ends_at: datetime

    def progress(self, now: datetime) -> float:
        """Return how far along the fade is, 0.0-1.0."""
        total = (self.ends_at - self.started_at).total_seconds()
        if total <= 0:
            return 1.0
        return min(max((now - self.started_at).total_seconds() / total, 0.0), 1.0)

    def level_at(self, now: datetime) -> float:
        """Return the calculated level (0-255) at `now`."""
        return self.start + (self.target - self.start) * self.progress(now)


TrackerState = Idle | Pending | Fading


def _pct(level: float) -> int:
    return round(level / 255 * 100)


class FadeTracker:
    """Tracks native fades for one light. `_state` changes only in `_transition`."""

    def __init__(self) -> None:
        self._state: TrackerState = Idle()

    @property
    def state(self) -> TrackerState:
        return self._state

    @property
    def fading(self) -> bool:
        return isinstance(self._state, Fading)

    def _transition(self, new: TrackerState) -> bool:
        """Move to `new`; return True if the state changed."""
        changed = new != self._state
        self._state = new
        return changed

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_call(self, light_level: float, duration: float, context_id: str | None, now: datetime) -> bool:
        """A turn_on/turn_off with a transition was sent to this light.

        Args:
            light_level: the light's current brightness per HA (0 when off).
                Ignored mid-fade: HA already shows the old target by then.
            duration: the transition in seconds; 0 just cancels tracking.
        """
        if duration <= 0:
            return self._transition(Idle())
        state = self._state
        start = state.level_at(now) if isinstance(state, Fading) else light_level
        return self._transition(Pending(start, now, float(duration), context_id))

    def on_light_state(self, level: float | None, now: datetime) -> bool:
        """The light reported a new state.

        Args:
            level: its brightness (0 when off), or None if unavailable.
        """
        state = self._state
        if isinstance(state, Idle):
            return False
        if level is None:
            return self._transition(Idle())

        if isinstance(state, Pending):
            if abs(level - state.start) <= ECHO_TOLERANCE:
                # Already at the target: nothing to fade
                return self._transition(Idle())
            ends_at = state.started_at + timedelta(seconds=state.duration)
            if now >= ends_at:
                return self._transition(Idle())
            return self._transition(Fading(state.start, level, state.started_at, ends_at))

        # Fading: the light repeating its target is just the fade confirming
        if abs(level - state.target) <= ECHO_TOLERANCE:
            return False
        # Anything else is an override (Pico, app, keypad, instant command)
        return self._transition(Idle())

    def on_tick(self, now: datetime) -> bool:
        """Periodic check: end a fade that has run its course, or a stale Pending."""
        state = self._state
        if isinstance(state, Fading) and now >= state.ends_at:
            return self._transition(Idle())
        if isinstance(state, Pending) and (now - state.started_at).total_seconds() >= PENDING_TIMEOUT:
            return self._transition(Idle())
        return False

    def restore(self, start: float, target: float, started_at: datetime, ends_at: datetime,
                light_level: float | None, now: datetime) -> bool:
        """Resume a fade saved before a restart, if it's still believable.

        Only if it hasn't ended and the light still reports the fade's target.
        """
        if (light_level is None or now >= ends_at
                or abs(light_level - target) > ECHO_TOLERANCE):
            return self._transition(Idle())
        return self._transition(Fading(start, target, started_at, ends_at))

    # ------------------------------------------------------------------
    # What the sensor shows
    # ------------------------------------------------------------------

    def state_name(self) -> str:
        return "fading" if isinstance(self._state, Fading) else "idle"

    def attributes(self, now: datetime) -> dict[str, Any]:
        """Return the fade details for the sensor (empty when not fading)."""
        state = self._state
        if not isinstance(state, Fading):
            return {}
        level = state.level_at(now)
        return {
            "brightness": round(level),
            "brightness_pct": _pct(level),
            "start_pct": _pct(state.start),
            "target_pct": _pct(state.target),
            "started_at": state.started_at.isoformat(),
            "ends_at": state.ends_at.isoformat(),
            "progress": round(state.progress(now) * 100),
        }

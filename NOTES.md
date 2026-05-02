# Development Notes

## Monitor Loop & Real-Time State

### What We Learned From Testing

The Lutron hub pushes `~OUTPUT` messages immediately when any zone changes,
regardless of source (HA, Lutron app, Pico remote, keypad, scene). The message
reflects the **target** level, not current — so during a fade you get the
destination immediately, not incremental updates.

Zone level monitoring (type 5) is **enabled by default** for user-level Telnet
login — no `#MONITORING` command needed.

Example push messages:
```
~OUTPUT,28,1,0.00       # zone 28 fading to 0%
~OUTPUT,22,1,100.00     # zone 22 set to 100%
~DEVICE,23,2,3          # Pico button press
~DEVICE,23,2,4          # Pico button release
```

### Plan: Monitor Loop

After authenticating (`GNET>` prompt received), start a background task that
continuously reads lines from the Telnet connection and dispatches state updates.

**Implementation steps:**

1. Add a `_monitor_loop` coroutine to `LutronTelnetConnection` that reads lines
   and calls registered callbacks when `~OUTPUT` lines arrive.

2. Replace `_ping_loop` with `_monitor_loop` — pings are redundant if we're
   already reading a continuous stream from the hub.

3. Add a zone→entity registry: a dict mapping zone IDs to `LutronFaderLight`
   instances, populated at setup time. The monitor loop uses this to call
   `async_write_ha_state()` on the right entity when a `~OUTPUT` arrives.

4. Update `manifest.json` `iot_class` from `local_polling` to `local_push`
   (it's already set correctly — just needs the monitor loop to back it up).

5. Set `should_poll = False` and remove `async_update` polling — state comes
   from the monitor loop exclusively.

### Plan: Fade Progress Tracking (Option 3)

Since the hub sends the target immediately but fades happen over time, track
progress internally:

- When a fade command is issued, record:
  - `start_level` (current brightness)
  - `target_level` (from command)
  - `start_time` (now)
  - `fade_duration` (seconds)

- On each HA state request, interpolate:
  `current = start + (target - start) * min(elapsed / duration, 1.0)`

- If a new `~OUTPUT` arrives for that zone before the fade completes:
  - Cancel the fade tracking
  - Use the new `~OUTPUT` target as the new state immediately
  - This handles Pico remotes, app overrides, keypads, etc.

This gives smooth in-progress display in the UI and correct state after
any external override.

### Setup Paths

Two paths for zone configuration — both partially built:

**Path 1: Integration Report (Recommended)**
Paste the Lutron Integration Report from the app (Settings → Advanced →
Integration → Send Integration Report). Already partially implemented via
`SERVICE_PARSE_REPORT` and `auto_configure_from_report` in `__init__.py`.

Advantages:
- Zone IDs, names, and area/room names all provided
- Device type known (light, fan, shade) — correct entity platform can be created
- One-time setup, no network scanning needed

This is the path to prioritize and make reliable first.

**Path 2: Zone Discovery (Experimental)**
`discover_zones()` in `lutron_telnet.py` pings zones 1–100 and checks for
responses. Already implemented but limited:
- No device type info — assumes everything is a light
- Slow (100 queries)
- Useful only if user doesn't have access to their integration report

This path should remain available but clearly marked experimental, and should
defer to the report path when possible.

**Action:** When parsing the integration report, use device type metadata to
route zones to the correct entity platform (light, fan, shade) rather than
defaulting everything to light.

### Future: Fan Support
Zone 30 is the Living Room ceiling fan. The hub treats it as a dimmer output
(0-100% speed) but it should be a `fan` entity in HA, not a `light`. Adding
fan platform support would follow the same telnet pattern but needs a separate
`LutronFaderFan` entity class and `fan` platform registration.

### Out-of-Scope for Now
- `#MONITORING` command appears unsupported or read-only on this hub firmware
  (returns `~ERROR,Enum=(6, 0x00000006)`) — not needed since type 5 is default.
- Retry logic on command failure (separate TODO item).

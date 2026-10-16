"""Constants for the Lutron Fader integration."""

DOMAIN = "lutron_fader"

# Fade tracking
TRACKED_PLATFORMS = ("lutron_caseta", "lutron_caseta_pro", "lutron")  # light platforms to track
PENDING_TIMEOUT = 5   # seconds to wait for a light to report a requested fade's target
TICK_INTERVAL = 1     # seconds between sensor updates while a fade runs
ECHO_TOLERANCE = 3    # brightness units (0-255) within which a reported level matches

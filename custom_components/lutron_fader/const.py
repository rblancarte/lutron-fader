"""Constants for the Lutron Fader integration."""

DOMAIN = "lutron_fader"

# Fade tracking
TRACKED_PLATFORMS = ("lutron_caseta", "lutron_caseta_pro", "lutron")  # light platforms to track
PENDING_TIMEOUT = 5   # seconds to wait for a light to report a requested fade's target
TICK_INTERVAL = 1     # seconds between sensor updates while a fade runs
# Brightness units (0-255) within which a reported level counts as the same level.
# Lutron works in whole percents, and neighbouring percents are only 2-3 units
# apart (99% -> 252, 100% -> 255), while a genuine echo comes back through the
# same conversion and is equal. So this must stay below 2.
ECHO_TOLERANCE = 1
REPORT_GRACE = 3      # seconds after a fade starts during which re-reports of its target are ignored

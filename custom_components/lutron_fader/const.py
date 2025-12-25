"""Constants for the Lutron Fader integration."""

# Integration domain
DOMAIN = "lutron_fader"

# Configuration keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_ZONE_MAPPINGS = "zone_mappings"

# Default values
DEFAULT_PORT = 23
DEFAULT_USERNAME = "lutron"
DEFAULT_PASSWORD = "integration"

# Service names
SERVICE_FADE_TO = "fade_to"
SERVICE_LONG_FADE = "long_fade"

# Service parameters / Attributes
ATTR_ZONE_ID = "zone_id"
ATTR_BRIGHTNESS = "brightness"
ATTR_TARGET_BRIGHTNESS_PCT = "target_brightness_pct"  # Alternative name
ATTR_FADE_TIME = "fade_time"
ATTR_DURATION = "duration"
ATTR_DURATION_SECONDS = "duration_seconds"  # More explicit

# Platforms
PLATFORMS = ["light"]


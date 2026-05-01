"""Stub out Home Assistant modules so tests run without a full HA install."""
import sys
import enum
from unittest.mock import MagicMock

# Every HA submodule that any integration file imports must be listed here
_STUBS = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.light",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.data_entry_flow",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.discovery",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.typing",
]

for mod in _STUBS:
    sys.modules.setdefault(mod, MagicMock())

# Patch specific constants / classes the integration references by name

class ColorMode(str, enum.Enum):
    BRIGHTNESS = "brightness"

light_mod = sys.modules["homeassistant.components.light"]
light_mod.ATTR_BRIGHTNESS = "brightness"
light_mod.ATTR_TRANSITION = "transition"
light_mod.ColorMode = ColorMode
light_mod.LightEntity = object
light_mod.PLATFORM_SCHEMA = MagicMock()
light_mod.PLATFORM_SCHEMA.extend = MagicMock(return_value=MagicMock())

const_mod = sys.modules["homeassistant.const"]
const_mod.CONF_NAME = "name"
const_mod.CONF_HOST = "host"
const_mod.CONF_PORT = "port"
const_mod.CONF_USERNAME = "username"
const_mod.CONF_PASSWORD = "password"
const_mod.Platform = MagicMock()

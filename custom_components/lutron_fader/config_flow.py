"""Config flow for Lutron Fader: one click, nothing to configure."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class LutronFaderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add fade tracking for every Lutron light."""

    # 2: fade tracker (1.x connected to the hub over Telnet; see async_migrate_entry)
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm and create the single entry."""
        if user_input is not None:
            return self.async_create_entry(title="Lutron Fader", data={})
        return self.async_show_form(step_id="user")

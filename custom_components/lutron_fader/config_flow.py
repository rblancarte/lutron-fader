"""Config flow for Lutron Fader integration."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
)
from .lutron_telnet import LutronTelnetConnection

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
        vol.Optional("ping_zone", default=1): int,
    }
)

STEP_REPORT_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("report_text", default=""): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    connection = LutronTelnetConnection(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        ping_zone=data.get("ping_zone", 1),
    )

    if not await connection.connect():
        raise CannotConnect

    await connection.disconnect()

    return {"title": f"Lutron Fader ({data[CONF_HOST]})"}


def parse_integration_report(report_text: str) -> dict[int, str]:
    """Parse an integration report (JSON or CSV) and return {zone_id: name}."""
    zones: dict[int, str] = {}

    try:
        report_data = json.loads(report_text)
        if "LIPIdList" in report_data and "Zones" in report_data["LIPIdList"]:
            for zone in report_data["LIPIdList"]["Zones"]:
                zone_id = zone.get("ID")
                zone_name = zone.get("Name")
                area_name = zone.get("Area", {}).get("Name", "")
                if zone_id and zone_name:
                    full_name = f"{area_name} {zone_name}".strip() if area_name else zone_name
                    zones[int(zone_id)] = full_name
        return zones
    except (json.JSONDecodeError, TypeError):
        pass

    # CSV fallback
    for line in report_text.strip().split("\n"):
        if not line.strip() or "INTEGRATION ID" in line.upper():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            try:
                zone_id = int(parts[0])
                zone_name = parts[1]
                zones[zone_id] = zone_name
            except (ValueError, IndexError):
                pass

    return zones


class LutronFaderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lutron Fader."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._connection_data: dict[str, Any] = {}
        self._title: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                self._connection_data = user_input
                self._title = info["title"]
                return await self.async_step_report()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_report(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user to paste their Lutron Integration Report to discover zones."""
        errors: dict[str, str] = {}

        if user_input is not None:
            report_text = user_input.get("report_text", "").strip()
            zones: dict[int, str] = {}

            if report_text:
                zones = parse_integration_report(report_text)
                if not zones:
                    errors["base"] = "report_parse_failed"

            if not errors:
                data = {**self._connection_data}
                if zones:
                    # JSON keys must be strings; we restore int keys on read
                    data["zones"] = {str(k): v for k, v in zones.items()}
                return self.async_create_entry(title=self._title, data=data)

        return self.async_show_form(
            step_id="report",
            data_schema=STEP_REPORT_DATA_SCHEMA,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

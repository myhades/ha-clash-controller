"""Config flow for Clash Controller."""

from __future__ import annotations

import logging
import asyncio
import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .api import ClashAPI, APITimeoutError, APIAuthError, APIClientError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class ClashControllerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Clash Controller."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial (and only) step."""

        errors: dict[str, str] = {}

        if user_input is None:
            user_input = {}

        api_url = user_input.get("api_url", "")
        token = user_input.get("bearer_token", "")
        use_ssl = user_input.get("use_ssl", False)
        allow_unsafe = user_input.get("allow_unsafe", False)

        if user_input:

            # Normalize the API URL to connect and generate unique ID
            if api_url.startswith("http://") or api_url.startswith("https://"):
                if use_ssl and api_url.startswith("http://"):
                    api_url = api_url.replace("http://", "https://", 1)
                elif not use_ssl and api_url.startswith("https://"):
                    api_url = api_url.replace("https://", "http://", 1)
            else:
                api_url = f"https://{api_url}" if use_ssl else f"http://{api_url}"
            if not api_url.endswith('/'):
                api_url += '/'
            user_input["api_url"] = api_url
            unique_id = re.sub(r"[^a-zA-Z0-9]", "_", api_url.strip().lower().rstrip("_"))
            
            # Validate unique ID
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await ClashAPI(api_url, token, allow_unsafe).connected(suppress_errors=False)
            except APIAuthError:
                errors["base"] = "invalid_token"
            except APITimeoutError:
                errors["base"] = "timed_out"
            except APIClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            
            if "base" not in errors:
                return self.async_create_entry(title=api_url, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_url", default=api_url): str,
                vol.Required("bearer_token", default=token): str,
                vol.Optional("use_ssl", default=use_ssl): bool,
                vol.Optional("allow_unsafe", default=allow_unsafe): bool,
            }),
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return ClashControllerOptionsFlow(config_entry)

class ClashControllerOptionsFlow(OptionsFlow):
    """Handle options for Clash Controller."""
    # TODO: Add options for token.

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            options = self.config_entry.options | user_input
            return self.async_create_entry(title="", data=options)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): (vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL))),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)

"""Config flow for Clash Controller."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .api import ClashAPI, APITimeoutError, APIAuthError, APIClientError
from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    CONF_CONCURRENT_CONNECTIONS,
    DEFAULT_CONCURRENT_CONNECTIONS,
    MIN_CONCURRENT_CONNECTIONS,
    MAX_CONCURRENT_CONNECTIONS,
)

_LOGGER = logging.getLogger(__name__)

class ClashControllerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Clash Controller."""

    def _normalize_url(self, api_url: str, use_ssl: bool):
        if api_url.startswith("http://") or api_url.startswith("https://"):
            if use_ssl and api_url.startswith("http://"):
                api_url = api_url.replace("http://", "https://", 1)
            elif not use_ssl and api_url.startswith("https://"):
                api_url = api_url.replace("https://", "http://", 1)
        else:
            api_url = f"https://{api_url}" if use_ssl else f"http://{api_url}"
        if not api_url.endswith('/'):
            api_url += '/'
        return api_url

    async def _test_connection(api: ClashAPI):
        errors = {}
        try:
            await api.connected(suppress_errors=False)
        except APIAuthError:
            errors["base"] = "invalid_token"
        except APITimeoutError:
            errors["base"] = "timed_out"
        except APIClientError:
            errors["base"] = "cannot_connect"
        except Exception:
            errors["base"] = "unknown"
        return errors

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial (and only) step."""

        errors = {}

        if user_input is None:
            user_input = {}

        api_url = user_input.get("api_url", "")
        token = user_input.get("bearer_token", "")
        use_ssl = user_input.get("use_ssl", False)
        allow_unsafe = user_input.get("allow_unsafe", False)

        if user_input:

            api_url = self._normalize_url(api_url, use_ssl)
            user_input["api_url"] = api_url
            unique_id = re.sub(r"[^a-zA-Z0-9]", "_", api_url.strip().lower().rstrip("_"))
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            errors = await self._test_connection(ClashAPI(api_url, token, allow_unsafe))
            if "base" not in errors:
                return self.async_create_entry(title=api_url, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_url", default=api_url): cv.string,
                vol.Required("bearer_token", default=token): cv.string,
                vol.Optional("use_ssl", default=use_ssl): cv.boolean,
                vol.Optional("allow_unsafe", default=allow_unsafe): cv.boolean,
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

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):
        """Handle options flow."""

        if user_input is not None:

            options = dict(self.config_entry.options)
            options[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
            options[CONF_CONCURRENT_CONNECTIONS] = user_input[CONF_CONCURRENT_CONNECTIONS]

            if user_input.get("bearer_token"):
                data = dict(self.config_entry.data)
                data["bearer_token"] = user_input["bearer_token"]
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)

            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL)),
                vol.Required(
                    CONF_CONCURRENT_CONNECTIONS,
                    default=self.options.get(CONF_CONCURRENT_CONNECTIONS, DEFAULT_CONCURRENT_CONNECTIONS),
                ): vol.All(vol.Coerce(int), vol.Clamp(min=MIN_CONCURRENT_CONNECTIONS)),
                vol.Optional("bearer_token"): cv.string,
            })
        )
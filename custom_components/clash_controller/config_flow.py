"""Config flow for Clash Controller."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from clash_controller_api import (
    APIAuthError,
    APIClientError,
    APIConnectionError,
    APITimeoutError,
    ClashAPI,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ALLOW_UNSAFE,
    CONF_API_URL,
    CONF_BEAR_TOKEN,
    CONF_CONCURRENT_CONNECTIONS,
    CONF_STREAMING_DETECTION,
    CONF_STREAMING_PROXY,
    CONF_USE_SSL,
    DEFAULT_CONCURRENT_CONNECTIONS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STREAMING_DETECTION,
    DOMAIN,
    MIN_CONCURRENT_CONNECTIONS,
    MIN_SCAN_INTERVAL,
)
from .streaming import (
    InvalidStreamingProxyError,
    StreamingDetector,
    StreamingProxyAuthError,
    StreamingProxyConnectionError,
    StreamingProxyTimeoutError,
    parse_streaming_proxy,
)

_LOGGER = logging.getLogger(__name__)


async def _test_connection(api: ClashAPI):
    errors = {}
    try:
        await api.async_validate_connection()
    except APIAuthError:
        errors["base"] = "invalid_token"
    except APITimeoutError:
        errors["base"] = "timed_out"
    except (APIClientError, APIConnectionError):
        errors["base"] = "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error validating controller connection")
        errors["base"] = "unknown"
    return errors


async def _test_streaming_proxy(
    hass: HomeAssistant, proxy_address: str
) -> dict[str, str]:
    """Validate a streaming proxy entered in the options flow."""
    try:
        proxy = parse_streaming_proxy(proxy_address)
    except InvalidStreamingProxyError:
        return {"base": "invalid_proxy"}

    detector = StreamingDetector(async_get_clientsession(hass), proxy)
    try:
        await detector.async_validate_proxy()
    except StreamingProxyAuthError:
        return {"base": "invalid_proxy_auth"}
    except StreamingProxyTimeoutError:
        return {"base": "proxy_timed_out"}
    except StreamingProxyConnectionError:
        return {"base": "cannot_connect_proxy"}
    except Exception:
        _LOGGER.exception("Unexpected error validating streaming proxy")
        return {"base": "unknown"}
    return {}


class ClashControllerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Clash Controller."""

    MINOR_VERSION = 2

    def _normalize_url(self, api_url: str, use_ssl: bool):
        if api_url.startswith("http://") or api_url.startswith("https://"):
            if use_ssl and api_url.startswith("http://"):
                api_url = api_url.replace("http://", "https://", 1)
            elif not use_ssl and api_url.startswith("https://"):
                api_url = api_url.replace("https://", "http://", 1)
        else:
            api_url = f"https://{api_url}" if use_ssl else f"http://{api_url}"
        if not api_url.endswith("/"):
            api_url += "/"
        return api_url

    async def _set_unique_id(self, api_url: str):
        unique_id = re.sub(r"[^a-zA-Z0-9]", "_", api_url.strip().lower().rstrip("_"))
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return unique_id

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial (and only) step."""

        errors = {}

        if user_input is None:
            user_input = {}

        api_url = user_input.get(CONF_API_URL, "")
        token = user_input.get(CONF_BEAR_TOKEN, "")
        use_ssl = user_input.get(CONF_USE_SSL, False)
        allow_unsafe = user_input.get(CONF_ALLOW_UNSAFE, False)

        if user_input:
            api_url = self._normalize_url(api_url, use_ssl)
            user_input[CONF_API_URL] = api_url
            api = ClashAPI(
                api_url,
                token,
                session=async_get_clientsession(self.hass, verify_ssl=not allow_unsafe),
            )

            await self._set_unique_id(api_url)

            errors = await _test_connection(api)
            if "base" not in errors:
                return self.async_create_entry(title=api_url, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_URL, default=api_url): cv.string,
                    vol.Required(CONF_BEAR_TOKEN, default=token): cv.string,
                    vol.Optional(CONF_USE_SSL, default=use_ssl): cv.boolean,
                    vol.Optional(CONF_ALLOW_UNSAFE, default=allow_unsafe): cv.boolean,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication for an existing entry."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and store replacement credentials."""
        errors: dict[str, str] = {}
        config_entry = self._get_reauth_entry()

        if user_input is not None:
            token = user_input[CONF_BEAR_TOKEN]
            allow_unsafe = config_entry.data.get(CONF_ALLOW_UNSAFE, False)
            api = ClashAPI(
                config_entry.data[CONF_API_URL],
                token,
                session=async_get_clientsession(self.hass, verify_ssl=not allow_unsafe),
            )
            errors = await _test_connection(api)
            if not errors:
                return self.async_update_reload_and_abort(
                    config_entry,
                    data_updates={CONF_BEAR_TOKEN: token},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_BEAR_TOKEN): cv.string}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> ClashControllerOptionsFlow:
        """Return the options flow handler."""
        return ClashControllerOptionsFlow()


class ClashControllerOptionsFlow(OptionsFlowWithReload):
    """Handle options for Clash Controller."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options flow."""

        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_STREAMING_DETECTION, False):
                errors = await _test_streaming_proxy(
                    self.hass, user_input.get(CONF_STREAMING_PROXY, "")
                )
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        else:
            user_input = dict(self.config_entry.options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL)),
                    vol.Required(
                        CONF_CONCURRENT_CONNECTIONS,
                        default=user_input.get(
                            CONF_CONCURRENT_CONNECTIONS, DEFAULT_CONCURRENT_CONNECTIONS
                        ),
                    ): vol.All(
                        vol.Coerce(int), vol.Clamp(min=MIN_CONCURRENT_CONNECTIONS)
                    ),
                    vol.Optional(
                        CONF_STREAMING_DETECTION,
                        default=user_input.get(
                            CONF_STREAMING_DETECTION, DEFAULT_STREAMING_DETECTION
                        ),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_STREAMING_PROXY,
                        default=user_input.get(CONF_STREAMING_PROXY, ""),
                    ): cv.string,
                }
            ),
            errors=errors,
        )

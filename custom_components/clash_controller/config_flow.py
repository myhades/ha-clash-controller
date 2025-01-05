"""Config flow for Clash Controller."""
from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol
import aiohttp
import asyncio
import logging
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class ClashControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Clash Controller."""

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is None:
            user_input = {}

        api_url = user_input.get("api_url", "")
        token = user_input.get("bearer_token", "")
        use_ssl = user_input.get("use_ssl", False)
        allow_unsafe = user_input.get("allow_unsafe", False)

        if user_input:

            # Normalize the API URL
            if api_url.startswith("http://") or api_url.startswith("https://"):
                if use_ssl and api_url.startswith("http://"):
                    api_url = api_url.replace("http://", "https://", 1)
                elif not use_ssl and api_url.startswith("https://"):
                    api_url = api_url.replace("https://", "http://", 1)
            else:
                api_url = f"https://{api_url}" if use_ssl else f"http://{api_url}"


            # Ensure the URL ends with a trailing slash
            if not api_url.endswith('/'):
                api_url += '/'

            try:
                # Validate connection to the Clash API
                await self._test_api_connection(api_url, token, allow_unsafe)
                # If no error, store the entry
                return self.async_create_entry(title=api_url, data=user_input)
            except aiohttp.ClientError as e:
                if "Unauthorized" in str(e):
                    errors["base"] = "invalid_token"
                else:
                    errors["base"] = "cannot_connect"
                _LOGGER.error(f"Connection error occurred when trying to connect to clash's RESTful API: {e}")
            except Exception as e:
                errors["base"] = "unknown"
                _LOGGER.error(f"Unknown error occurred when trying to connect to clash's RESTful API: {e}")

        # Configure the form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_url", default=api_url): str,
                vol.Required("bearer_token", default=token): str,
                vol.Optional("use_ssl", default=use_ssl): bool,
                vol.Optional("allow_unsafe", default=allow_unsafe): bool,
            }),
            description_placeholders={"info": "setup_tips"},
            errors=errors
        )

    async def _test_api_connection(self, api_url, token, allow_unsafe):
        """Test the connection to the Clash API."""
        ssl_context = None
        if allow_unsafe:
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            headers = {"Authorization": f"Bearer {token}"}
            async with session.get(f"{api_url}version", headers=headers, timeout=10) as response:
                if response.status == 401:
                    raise aiohttp.ClientError("Unauthorized: Invalid Bearer Token")
                if response.status != 200:
                    raise aiohttp.ClientError(f"Invalid response status: {response.status}")
                data = await response.json()
                if "version" not in data:
                    raise aiohttp.ClientError("Missing 'version' in response")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return ClashControllerOptionsFlow(config_entry)


class ClashControllerOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Clash Controller."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("polling_interval", default=30): int,
            }),
        )

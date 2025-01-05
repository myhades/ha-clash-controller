from homeassistant.helpers.aiohttp_client import async_get_clientsession
from typing import Any, Dict, Optional
import logging
import aiohttp

_LOGGER = logging.getLogger(__name__)

class ClashAPI:
    """A utility class to interact with the Clash API."""

    def __init__(self, hass, base_url: str, token: str, allow_unsafe: bool = False):
        """
        Initialize the ClashAPI instance.
        """
        self._hass = hass
        self.base_url = base_url
        self.token = token
        self.allow_unsafe = allow_unsafe
        self._session = async_get_clientsession(hass, verify_ssl=not allow_unsafe)

    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Any:
        """
        Perform an HTTP request.
        """
        url = f"{self.base_url}{endpoint.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            if method.upper() == "GET":
                response = await self._session.get(url, headers=headers)
            elif method.upper() == "PUT":
                response = await self._session.put(url, json=data, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return await self._handle_response(response)

        except aiohttp.ClientError as e:
            _LOGGER.error(f"Clash API {method} request to {url} failed: {e}")
            raise

    async def _handle_response(self, response: aiohttp.ClientResponse) -> Any:
        """
        Handle the HTTP response.
        """
        if response.status == 401:
            raise aiohttp.ClientError("Unauthorized: Invalid Bearer Token")
        if response.status != 200:
            raise aiohttp.ClientError(f"Invalid response status: {response.status}")

        try:
            return await response.json()
        except Exception as e:
            raise aiohttp.ClientError(f"Failed to parse JSON response: {e}")

    async def get(self, endpoint: str) -> Any:
        """Perform a GET request."""
        return await self._request("GET", endpoint)

    async def put(self, endpoint: str, data: Dict) -> Any:
        """Perform a PUT request."""
        return await self._request("PUT", endpoint, data=data)

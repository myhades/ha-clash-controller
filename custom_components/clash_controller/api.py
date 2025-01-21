"""API class for Clash Controller."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Optional
import ssl
import asyncio
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

class DeviceType(StrEnum):
    """Device types."""

    GROUP_SENSOR = "proxy_group_sensor"
    GROUP_SELECTOR = "proxy_group_selector"
    OTHER = "other"

@dataclass
class Device:
    """Clash API device."""

    device_unique_id: str
    name: str
    device_type: DeviceType

class ClashAPI:
    """A utility class to interact with the Clash API."""

    def __init__(self, host: str, token: str, allow_unsafe: bool = False):
        """
        Initialize the ClashAPI instance.
        """
        self.host = host
        self.token = token
        self.allow_unsafe = allow_unsafe
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _create_session(self):
        """
        Create/Recreate a session with given configuration.
        """

        ssl_context = None
        if self.allow_unsafe:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        new_session = None
        try:
            new_session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context),
                timeout=aiohttp.ClientTimeout(total=15),
            )
            _LOGGER.debug("Session created successfully.")
            self._session = new_session
        except Exception as err:
            _LOGGER.error(f"Failed to create session: {err}")
            if new_session:
                await new_session.close()
            raise APIClientError("Error creating HTTP session.") from err


    async def _request(self, method: str, endpoint: str, params: dict = None, json_data: dict = None):
        """
        General method for making requests.
        """

        if self._session is None:
            await self._create_session()  # Lazy initialization

        url = f"{self.host}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        
        try:
            async with self._session.request(method, url, params=params, json=json_data, headers=headers) as response:
                _LOGGER.debug(f"HTTP {method} request to {url} got response code {response.status}.")
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                _LOGGER.error("Authentication failed for API request.")
                raise APIAuthError("Invalid API credentials.")
            else:
                _LOGGER.error(f"API request got an invalid response: {err}")
                raise APIClientError("API invalid response.") from err
        except asyncio.TimeoutError as err:
            _LOGGER.error(f"API request timeout: {err}")
            raise APITimeoutError("API connection timeout.") from err
        except Exception as err:
            _LOGGER.error(f"API request generic failure: {err}")
            raise APIClientError("API client error.") from err

    
    async def connected(self, suppress_errors: bool = True) -> bool:
        """
        Check if the API connection is successful by sending a simple request.
        """
        endpoint = "version"
        try:
            response = await self._request("GET", endpoint)
            if ("version" not in response) and (not suppress_errors):
                _LOGGER.error(f"Missing version key in response. Is this endpoint running Clash?")
                raise APIClientError("Version key missing.")
            return "version" in response
        except Exception:
            if suppress_errors:
                return False
            raise
    
    def get_device(self) -> Device:
        """Generate a device object."""
        return Device(
            device_unique_id=re.sub(r"[^a-zA-Z0-9]", "_", self.host.strip().lower().rstrip("_")) + "_device",
            name="Clash@" + self.host,
        )
    
    async def disconnect(self):
        """
        Close the session when done.
        """
        if self._session:
            await self._session.close()

class APIAuthError(Exception):
    """Exception class for auth error."""

class APIClientError(Exception):
    """Exception class for generic client error."""

class APITimeoutError(Exception):
    """Exception class for timeout error."""
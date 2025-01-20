"""API class for Clash Controller."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Optional
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

@dataclass
class Device:
    """Clash API device."""

    device_unique_id: str
    name: str

class ClashAPI:
    """A utility class to interact with the Clash API."""

    def __init__(self, host: str, token: str, use_ssl: bool = False, allow_unsafe: bool = False):
        """
        Initialize the ClashAPI instance.
        """
        self.host = host
        self.token = token
        self.use_ssl = use_ssl
        self.allow_unsafe = allow_unsafe
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _create_session(self):
        """
        Create/Recreate a session with given configuration.
        """
        if self._session:
            await self._session.close()

        ssl_context = None
        if self.allow_unsafe:
            ssl_context = False

        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl_context),
            timeout=aiohttp.ClientTimeout(total=15)
    )

    async def close(self):
        """
        Close the session when done.
        """
        if self._session:
            await self._session.close()

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
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            # Handle connection or HTTP errors
            return None
        except asyncio.TimeoutError:
            # Handle timeout errors
            return None

    async def connected(self) -> bool:
        """
        Check if the API connection is successful by sending a simple request.
        """
        endpoint = "version"
        response = await self._request("GET", endpoint)
        
        if response is None:
            return False
        if response.get("status") == 200:
            return True
        return False
    
    def get_devices(self) -> list[Device]:
        """Get devices on api."""
        return Device(
            device_unique_id=self._get_device_unique_id(),
            name="Clash@" + self.host,
        )
    
    def _get_device_unique_id(self) -> str:
        return re.sub(r"[^a-zA-Z0-9]", "_", self.host.strip().lower().rstrip("_")) + "_device"
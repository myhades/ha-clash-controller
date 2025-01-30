"""API class for Clash Controller."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Optional
import asyncio
import json
import re
import ssl
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

class ClashAPI:
    """A utility class to interact with the Clash API."""

    def __init__(self, host: str, token: str, allow_unsafe: bool = False):
        """
        Initialize the ClashAPI instance.
        """
        self.host = host
        self.token = token
        self.allow_unsafe = allow_unsafe
        self.device_id = re.sub(r"[^a-zA-Z0-9]", "_", self.host.strip().lower().rstrip("_")) + "_device"
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
            _LOGGER.error(f"Failed to create HTTP session: {err}")
            if new_session:
                await new_session.close()
            raise APIClientError("Error creating HTTP session.") from err

    async def _request(
        self, method: str, endpoint: str, params: dict = None, json_data: dict = None, read_line: int = 0
        ):
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

        _LOGGER.debug(f"Making {method} request to {url}, read line: {read_line}.")

        try:
            async with self._session.request(method, url, params=params, json=json_data, headers=headers) as response:
                response.raise_for_status()
                try:
                    if read_line > 0:
                        line_counter = 0
                        async for line in response.content:
                            line_counter += 1
                            if line_counter == read_line:
                                return json.loads(line.decode('utf-8').strip())
                    else:
                        return await response.json()
                except (json.JSONDecodeError, UnicodeDecodeError) as err:
                    _LOGGER.error(f"Error decoding JSON: {err}")
                    raise APIClientError("Failed to parse JSON response.") from err
                except Exception as err:
                    _LOGGER.error(f"Unexpected error parsing line: {err}")
                    raise APIClientError("Error processing API response.") from err
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
            _LOGGER.error(f"API request generic failure: {err}", exc_info=True)
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

    async def get_version(self) -> str:
        """
        Get the version string.
        """
        try:
            version_info = await self._request("GET", "version")
        except Exception:
            return None
        return {
            "meta": "Meta Core" if version_info.get("meta") is True else "Non-Meta Core",
            "version": version_info.get("version", "unknown"),
        }

    async def disconnect(self):
        """
        Manually close the session.
        """
        if self._session:
            await self._session.close()
        self._session = None

    async def fetch_data(self) -> dict:
        """
        Get all data needed to update the entities.
        """
        payload: dict[str, Any] = {}
        
        payload['memory'] = await self._request("GET", "memory", read_line=2)
        payload['traffic'] = await self._request("GET", "traffic", read_line=1)
        payload['connections'] = await self._request("GET", "connections")
        payload['group'] = await self._request("GET", "group")
        _LOGGER.debug(f"Data fetched: {list(payload.keys())}")

        return payload
    
class APIAuthError(Exception):
    """Exception class for auth error."""

class APIClientError(Exception):
    """Exception class for generic client error."""

class APITimeoutError(Exception):
    """Exception class for timeout error."""
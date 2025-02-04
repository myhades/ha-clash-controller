"""API class for Clash Controller."""

from typing import Optional
import asyncio
import json
import logging
import re
import ssl

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
    
    async def _establish_session(self):
        """
        Establish a session with given configuration.
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
            if new_session:
                await new_session.close()
            raise APIClientError(f"Error creating HTTP session: {err}") from err

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        json_data: dict = None,
        read_line: int = 0
        ):
        """
        General method for making requests.
        """
        if self._session is None:
            await self._establish_session()
            
        url = f"{self.host}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        _LOGGER.debug(f"Making {method} request to {url}, read line: {read_line}.")

        try:
            async with self._session.request(method, url, params=params, json=json_data, headers=headers) as response:
                response.raise_for_status()
                if response.status == 204:
                    return None
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
                    raise APIClientError(f"Error parsing JSON: {err}") from err
                except Exception as err:
                    raise APIClientError(f"Unexpected error parsing API response: {err}") from err
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                raise APIAuthError("Invalid API credentials.")
            else:
                raise APIClientError(f"API request got an invalid response: {err}") from err
        except asyncio.TimeoutError as err:
            raise APITimeoutError(f"API request timed out: {err}") from err
        except Exception as err:
            raise APIClientError(f"API request generic failure: {err}") from err

    async def async_request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        json_data: dict = None,
        read_line: int = 0,
        suppress_errors: bool = True,
        ) -> dict:
        """
        General async request method.
        """
        try:
            response = await self._request(method, endpoint, params=params, json_data=json_data, read_line=read_line)
        except Exception:
            if suppress_errors:
                return {}
            raise
        return response or {}

    async def connected(self, suppress_errors: bool = True) -> bool:
        """
        Check if the API connection is successful by sending a simple request.
        """
        try:
            response = await self._request("GET", "version")
            if ("version" not in response) and (not suppress_errors):
                raise APIClientError("Missing version key in response. Is this endpoint running Clash?")
            if "version" not in response:
                return False
        except Exception:
            if suppress_errors:
                return False
            raise
        return True

    async def get_version(self) -> dict:
        """
        Get the version string.
        """
        response = await self.async_request("GET", "version")
        return {
            "meta": "Meta Core" if response and response.get("meta") is True else "Non-Meta Core",
            "version": response.get("version", "unknown"),
        }

    async def fetch_data(self) -> dict:
        """
        Get all data needed to update the entities.
        """
        payload_keys = ["memory", "traffic", "connections", "group"]
        endpoints = [
            ("memory", {"read_line": 2}),
            ("traffic", {"read_line": 1}),
            ("connections", {}),
            ("group", {})
        ]
        results = await asyncio.gather(*[
            self.async_request("GET", endpoint, **params)
            for endpoint, params in endpoints
        ], return_exceptions=True)
        return dict(zip(payload_keys, results))

class APIAuthError(Exception):
    """Exception class for auth error."""

class APIClientError(Exception):
    """Exception class for generic client error."""

class APITimeoutError(Exception):
    """Exception class for timeout error."""
"""API class for Clash Controller."""

from typing import Optional
import asyncio
import json
import logging
import random
import re
import ssl
import time

import aiohttp

_LOGGER = logging.getLogger(__name__)

SERVICE_TABLE = {
    "netflix": {
        "name": "Netflix",
        "icon": "mdi:netflix",
        "url": "https://www.netflix.com/title/81280792",
        "code_table":{
            200: "unlocked",
            403: "blocked",
            404: "original_only",
            000: "unavailable",
        },
    },
}

class ClashAPI:
    """A utility class to interact with the Clash API."""

    MAX_RETRIES = 3
    BACKOFF_BASE = 1

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

        async def handle_response_format(response, read_line: int):
            line_counter = 0
            if response.status == 204:
                return None
            if read_line < 1:
                return await response.json()
            async for line in response.content:
                line_counter += 1
                if line_counter == read_line:
                    return json.loads(line.decode('utf-8').strip())

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
                try:
                    return await handle_response_format(response, read_line=read_line)
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
        except aiohttp.ClientConnectionError as err:
            raise APIConnectionError(f"API request connection error: {err}") from err
        except Exception as err:
            raise APIClientError(f"API request generic failure: {err}") from err

    async def close_session(self):
        """
        Safely close the session.
        """

        if self._session is not None:
            try:
                await self._session.close()
                _LOGGER.debug("Session closed successfully.")
            except Exception as err:
                _LOGGER.warning(f"Failed to close session: {err}")
            finally:
                self._session = None

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
            response = await self._request(
                    method, endpoint,
                    params=params,
                    json_data=json_data,
                    read_line=read_line,
                )
        except Exception:
            if suppress_errors:
                return {}
            raise
        return response or {}
    
    async def async_retryable_request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        json_data: dict = None,
        read_line: int = 0,
        suppress_errors: bool = True,
    ) -> dict:
        """
        General async request method, with retry and backoff for connectivity issues.
        """
        last_exc = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await self._request(
                    method, endpoint,
                    params=params,
                    json_data=json_data,
                    read_line=read_line,
                )
                return response or {}
            except (APITimeoutError, APIConnectionError) as err:
                last_exc = err
                _LOGGER.debug(
                    "Request %s %s failed timed out on attempt %d/%d",
                    method, endpoint, attempt, self.MAX_RETRIES
                )
                if attempt < self.MAX_RETRIES:
                    backoff = self.BACKOFF_BASE * (2 ** (attempt - 1))
                    jitter = random.uniform(0, backoff * 0.1)
                    await asyncio.sleep(backoff + jitter)
                else:
                    break
            except Exception as err:
                last_exc = err
                break
        if suppress_errors:
            return {}
        raise last_exc

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

    async def get_url_status(self, url: str, headers: dict = {}) -> dict:
        """
        Get the status code and latency to the given URL.
        """

        async with aiohttp.ClientSession() as session:
            try:
                start_time = time.monotonic()
                async with session.get(url, headers=headers, timeout=10) as response:
                    response.raise_for_status()
                    duration = time.monotonic() - start_time
                    return {"latency": duration, "status_code": response.status}
            except aiohttp.ClientResponseError as err:
                duration = time.monotonic() - start_time
                return {"latency": duration, "status_code": err.status}
            except asyncio.TimeoutError:
                return {"latency": -1, "status_code": 000}
            except Exception as err:
                _LOGGER.error(f"Error getting status code for {url}: {err}")
                return {"latency": -1, "status_code": 000}

    async def fetch_data(self, streaming_detection: bool = False) -> dict:
        """
        Get all data needed to update the entities.
        """

        async def fetch_streaming_service_data():
            results = await asyncio.gather(*[
                self.get_url_status(details["url"])
                for service, details in SERVICE_TABLE.items()
            ], return_exceptions=True)
            return dict(zip((s for s in SERVICE_TABLE), results))
        
        endpoints = [
            ("memory", {"read_line": 2}),
            ("traffic", {"read_line": 1}),
            ("connections", {}),
            ("proxies", {})
        ]
        results = await asyncio.gather(*[
            self.async_retryable_request("GET", endpoint, **params)
            for endpoint, params in endpoints
        ], return_exceptions=True)
        data = dict(zip((e[0] for e in endpoints), results))

        if streaming_detection:
            streaming_data = await fetch_streaming_service_data()
            data["streaming"] = streaming_data
            _LOGGER.debug(f"Streaming detection data: {streaming_data}")

        return data

class APIAuthError(Exception):
    """Exception class for auth error."""

class APIClientError(Exception):
    """Exception class for generic client error."""

class APITimeoutError(Exception):
    """Exception class for timeout error."""

class APIConnectionError(Exception):
    """Exception class for connection error."""
"""API class for Clash Controller."""

from __future__ import annotations

from typing import Any, Optional
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
        "code_table": {
            200: "unlocked",
            403: "blocked",
            404: "original_only",
            000: "unavailable",
        },
    },
}


class ClashAPI:
    """A utility class to interact with the Clash API."""

    MAX_RETRIES = 2
    BACKOFF_BASE = 1

    def __init__(
        self,
        host: str,
        token: str,
        allow_unsafe: bool = False,
        available_endpoints: Optional[list[tuple[str, dict[str, Any]]]] = None,
        capabilities: Optional[dict[str, bool]] = None,
    ):
        """Initialize the ClashAPI instance."""
        self.host = host
        self.token = token
        self.allow_unsafe = allow_unsafe
        self.device_id = (
            re.sub(r"[^a-zA-Z0-9]", "_", self.host.strip().lower().rstrip("_"))
            + "_device"
        )
        self._session: Optional[aiohttp.ClientSession] = None
        self._status_session: Optional[aiohttp.ClientSession] = None
        self._available_endpoints: Optional[list[tuple[str, dict[str, Any]]]] = (
            available_endpoints
        )
        self._capabilities: Optional[dict[str, bool]] = (
            dict(capabilities) if capabilities else None
        )

    @property
    def available_endpoints(self) -> Optional[list[tuple[str, dict[str, Any]]]]:
        """Return currently available entity polling endpoints."""
        return self._available_endpoints

    @property
    def capabilities(self) -> Optional[dict[str, bool]]:
        """Return endpoint capability matrix."""
        return self._capabilities

    def _request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _ws_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _build_ws_url(self, endpoint: str) -> str:
        if self.host.startswith("https://"):
            base = "wss://" + self.host[len("https://") :]
        elif self.host.startswith("http://"):
            base = "ws://" + self.host[len("http://") :]
        else:
            base = self.host
        return f"{base}{endpoint}"

    async def _establish_session(self):
        """Establish a session with given configuration."""
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
            self._session = new_session
            _LOGGER.debug("Session created successfully.")
        except Exception as err:
            if new_session:
                await new_session.close()
            raise APIClientError(f"Error creating HTTP session: {err}") from err

    async def _establish_status_session(self):
        """Establish a dedicated session for third-party URL probes."""
        new_session = None
        try:
            new_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
            )
            self._status_session = new_session
        except Exception as err:
            if new_session:
                await new_session.close()
            raise APIClientError(f"Error creating status probe session: {err}") from err

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        read_line: int = 0,
    ) -> Any:
        """General method for making requests."""

        async def handle_response_format(response: aiohttp.ClientResponse) -> Any:
            if response.status == 204:
                return None
            if read_line < 1:
                return await response.json()
            line_counter = 0
            async for line in response.content:
                line_counter += 1
                if line_counter == read_line:
                    return json.loads(line.decode("utf-8").strip())
            return None

        if self._session is None:
            await self._establish_session()

        url = f"{self.host}{endpoint}"
        _LOGGER.debug("Making %s request to %s, read line: %s.", method, url, read_line)

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json_data,
                headers=self._request_headers(),
            ) as response:
                response.raise_for_status()
                try:
                    return await handle_response_format(response)
                except (json.JSONDecodeError, UnicodeDecodeError) as err:
                    raise APIClientError(f"Error parsing JSON: {err}") from err
                except Exception as err:
                    raise APIClientError(
                        f"Unexpected error parsing API response: {err}"
                    ) from err
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                raise APIAuthError("Invalid API credentials.") from err
            raise APIClientError(f"API request got an invalid response: {err}") from err
        except asyncio.TimeoutError as err:
            await self.close_session()
            raise APITimeoutError(f"API request timed out: {err}") from err
        except aiohttp.ClientConnectionError as err:
            await self.close_session()
            raise APIConnectionError(f"API request connection error: {err}") from err
        except Exception as err:
            await self.close_session()
            raise APIClientError(f"API request generic failure: {err}") from err

    async def async_ws_request(
        self,
        endpoint: str,
        suppress_errors: bool = True,
        timeout: int = 3,
    ) -> dict[str, Any]:
        """Read one JSON message from websocket endpoint."""
        if self._session is None:
            await self._establish_session()

        ws_url = self._build_ws_url(endpoint)
        try:
            async with self._session.ws_connect(
                ws_url,
                headers=self._ws_headers(),
                heartbeat=30,
                timeout=timeout,
            ) as websocket:
                message = await websocket.receive(timeout=timeout)
                if message.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(message.data.strip())
                    return payload if isinstance(payload, dict) else {}
                if message.type == aiohttp.WSMsgType.BINARY:
                    payload = json.loads(message.data.decode("utf-8").strip())
                    return payload if isinstance(payload, dict) else {}
                raise APIClientError(
                    f"Unexpected websocket message type for {endpoint}: {message.type}"
                )
        except Exception:
            if suppress_errors:
                return {}
            raise

    async def _probe_http_endpoint(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        read_line: int = 0,
        accept_statuses: tuple[int, ...] = (),
        probe_timeout: float = 4.0,
    ) -> bool:
        if self._session is None:
            await self._establish_session()

        url = f"{self.host}{endpoint}"
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json_data,
                headers=self._request_headers(),
                timeout=aiohttp.ClientTimeout(total=probe_timeout),
            ) as response:
                if 200 <= response.status < 300:
                    if read_line > 0:
                        line_counter = 0
                        async for line in response.content:
                            line_counter += 1
                            if line_counter == read_line:
                                json.loads(line.decode("utf-8").strip())
                                return True
                        return False
                    else:
                        response.release()
                    return True
                return response.status in accept_statuses
        except Exception:
            return False

    async def _probe_ws_endpoint(self, endpoint: str, timeout: float = 1.5) -> bool:
        try:
            payload = await asyncio.wait_for(
                self.async_ws_request(
                    endpoint,
                    suppress_errors=False,
                    timeout=timeout,
                ),
                timeout=timeout + 1.0,
            )
            return bool(payload)
        except Exception:
            return False

    async def async_detect_capabilities(
        self, force: bool = False
    ) -> dict[str, bool]:
        """Probe API endpoints and websocket support."""
        if self._capabilities is not None and not force:
            return self._capabilities

        probe_tasks = {
            "proxies": self._probe_http_endpoint("GET", "proxies"),
            "connections": self._probe_http_endpoint("GET", "connections"),
            "traffic": self._probe_http_endpoint("GET", "traffic", read_line=1),
            "memory": self._probe_http_endpoint("GET", "memory", read_line=2),
            "configs": self._probe_http_endpoint("GET", "configs"),
            "rules": self._probe_http_endpoint("GET", "rules"),
            "group": self._probe_http_endpoint("GET", "group"),
            "providers_proxies": self._probe_http_endpoint("GET", "providers/proxies"),
            "providers_rules": self._probe_http_endpoint("GET", "providers/rules"),
            "dns_query": self._probe_http_endpoint(
                "GET",
                "dns/query",
                params={"name": "example.com", "type": "A"},
            ),
            "cache_fakeip_flush": self._probe_http_endpoint(
                "GET",
                "cache/fakeip/flush",
                accept_statuses=(405,),
            ),
            "cache_dns_flush": self._probe_http_endpoint(
                "GET",
                "cache/dns/flush",
                accept_statuses=(405,),
            ),
            "restart": self._probe_http_endpoint(
                "GET",
                "restart",
                accept_statuses=(405,),
            ),
        }

        probe_names = list(probe_tasks.keys())
        probe_results = await asyncio.gather(*probe_tasks.values(), return_exceptions=True)
        capabilities: dict[str, bool] = {}
        for name, result in zip(probe_names, probe_results):
            capabilities[name] = bool(result) if not isinstance(result, Exception) else False

        capabilities["group_detail"] = capabilities.get("group", False)
        capabilities["group_delay"] = capabilities.get("group", False) and capabilities.get(
            "proxies", False
        )
        capabilities["proxy_delay"] = capabilities.get("proxies", False)
        capabilities["provider_healthcheck"] = capabilities.get(
            "providers_proxies", False
        )
        capabilities["provider_proxy_healthcheck"] = capabilities.get(
            "providers_proxies", False
        )

        capabilities["ws_traffic"] = (
            await self._probe_ws_endpoint("traffic")
            if capabilities.get("traffic")
            else False
        )
        capabilities["ws_memory"] = (
            await self._probe_ws_endpoint("memory")
            if capabilities.get("memory")
            else False
        )
        capabilities["ws_connections"] = (
            await self._probe_ws_endpoint("connections?interval=1")
            if capabilities.get("connections")
            else False
        )
        capabilities["ws_logs"] = False

        self._capabilities = capabilities
        self._available_endpoints = []
        if capabilities.get("memory"):
            self._available_endpoints.append(("memory", {"read_line": 2}))
        if capabilities.get("traffic"):
            self._available_endpoints.append(("traffic", {"read_line": 1}))
        if capabilities.get("connections"):
            self._available_endpoints.append(("connections", {}))
        if capabilities.get("proxies"):
            self._available_endpoints.append(("proxies", {}))

        supported = ", ".join(
            name for name, enabled in capabilities.items() if enabled
        )
        if supported:
            _LOGGER.debug("Detected capabilities for %s: %s", self.host, supported)

        return capabilities

    async def close_session(self):
        """Safely close sessions."""
        if self._session is not None:
            try:
                await self._session.close()
                _LOGGER.debug("Session closed successfully.")
            except Exception as err:
                _LOGGER.warning(f"Failed to close session: {err}")
            finally:
                self._session = None

        if self._status_session is not None:
            try:
                await self._status_session.close()
            except Exception as err:
                _LOGGER.warning(f"Failed to close status probe session: {err}")
            finally:
                self._status_session = None

    async def async_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        read_line: int = 0,
        suppress_errors: bool = True,
    ) -> dict[str, Any]:
        """General async request method."""
        try:
            response = await self._request(
                method,
                endpoint,
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
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        read_line: int = 0,
        suppress_errors: bool = True,
    ) -> dict[str, Any]:
        """Async request with retry and backoff for connectivity issues."""
        last_exc = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await self._request(
                    method,
                    endpoint,
                    params=params,
                    json_data=json_data,
                    read_line=read_line,
                )
                return response or {}
            except (APITimeoutError, APIConnectionError) as err:
                last_exc = err
                _LOGGER.debug(
                    "Request %s %s timed out on attempt %d/%d",
                    method,
                    endpoint,
                    attempt,
                    self.MAX_RETRIES,
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
        """Check if API connection is successful by reading /version."""
        try:
            response = await self._request("GET", "version")
            if ("version" not in response) and (not suppress_errors):
                raise APIClientError(
                    "Missing version key in response. Is this endpoint running Clash?"
                )
            if "version" not in response:
                return False
        except Exception:
            if suppress_errors:
                return False
            raise
        return True

    @staticmethod
    def _parse_semver(version: str) -> tuple[int, int, int] | None:
        match = re.search(r"(?:v)?(\d+)\.(\d+)\.(\d+)", version)
        if not match:
            return None
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @classmethod
    def _infer_core_model(cls, response: dict[str, Any]) -> str:
        reported_name = response.get("name") or response.get("core") or response.get("product")
        if isinstance(reported_name, str) and reported_name.strip():
            normalized = reported_name.strip()
            lowered = normalized.lower()
            if "mihomo" in lowered:
                return "Mihomo"
            if "clash.meta" in lowered or ("meta" in lowered and "mihomo" not in lowered):
                return "Clash Meta"
            if "clash" in lowered:
                return "Clash"
            return normalized

        is_meta = response.get("meta") is True
        version = str(response.get("version", "")).strip()
        lowered_version = version.lower()
        if not is_meta:
            return "Clash Compatible Core"
        if "mihomo" in lowered_version:
            return "Mihomo"
        if "clash.meta" in lowered_version:
            return "Clash Meta"
        parsed_version = cls._parse_semver(lowered_version)
        if parsed_version:
            # Clash.Meta ended before mihomo took over; newer semver lines are mihomo.
            return "Mihomo" if parsed_version >= (1, 17, 0) else "Clash Meta"
        return "Meta Core"

    async def get_version(self) -> dict[str, str]:
        """Get normalized core version data."""
        response = await self.async_request("GET", "version")
        is_meta = response.get("meta") is True
        model = self._infer_core_model(response)
        return {
            "meta": "Meta Core" if is_meta else "Non-Meta Core",
            "model": model,
            "version": response.get("version", "unknown"),
        }

    async def get_url_status(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, float | int]:
        """Get the status code and latency to a third-party URL."""
        try:
            if self._status_session is None:
                await self._establish_status_session()
        except Exception as err:
            _LOGGER.debug("Error creating status probe session: %s", err)
            return {"latency": -1, "status_code": 000}

        request_headers = headers or {}
        start_time = time.monotonic()
        try:
            async with self._status_session.get(url, headers=request_headers) as response:
                duration = time.monotonic() - start_time
                return {"latency": duration, "status_code": response.status}
        except asyncio.TimeoutError:
            return {"latency": -1, "status_code": 000}
        except aiohttp.ClientError as err:
            duration = time.monotonic() - start_time
            _LOGGER.debug("Error getting status code for %s: %s", url, err)
            return {"latency": duration, "status_code": 000}
        except Exception as err:
            _LOGGER.error(f"Error getting status code for {url}: {err}")
            return {"latency": -1, "status_code": 000}

    async def async_detect_available_endpoints(self) -> list[tuple[str, dict[str, Any]]]:
        """Backward-compatible wrapper for old startup flow."""
        await self.async_detect_capabilities()
        return self._available_endpoints or []

    async def _fetch_endpoint_with_fallback(
        self,
        key: str,
        endpoint: str,
        params: dict[str, Any] | None,
        read_line: int,
        ws_endpoint: str | None,
        suppress_errors: bool,
    ) -> dict[str, Any]:
        if ws_endpoint and self._capabilities and self._capabilities.get(f"ws_{key}", False):
            try:
                ws_response = await asyncio.wait_for(
                    self.async_ws_request(
                        ws_endpoint,
                        suppress_errors=True,
                        timeout=3,
                    ),
                    timeout=4,
                )
            except Exception:
                ws_response = {}
            if ws_response:
                return ws_response
            self._capabilities[f"ws_{key}"] = False

        return await self.async_retryable_request(
            "GET",
            endpoint,
            params=params,
            read_line=read_line,
            suppress_errors=suppress_errors,
        )

    async def fetch_data(
        self,
        streaming_detection: bool = False,
        suppress_errors: bool = True,
    ) -> dict[str, Any]:
        """Get all endpoint data needed by the coordinator."""

        async def fetch_streaming_service_data():
            results = await asyncio.gather(
                *[
                    self.get_url_status(details["url"])
                    for details in SERVICE_TABLE.values()
                ],
                return_exceptions=True,
            )
            if not suppress_errors:
                for result in results:
                    if isinstance(result, Exception):
                        raise result
                    if not result:
                        raise APIClientError("Missing streaming detection data")
            return dict(zip((service for service in SERVICE_TABLE), results))

        capabilities = await self.async_detect_capabilities()
        read_line_map = {
            endpoint: int(params.get("read_line", 0))
            for endpoint, params in (self._available_endpoints or [])
        }
        endpoint_specs: list[dict[str, Any]] = []

        if capabilities.get("traffic"):
            endpoint_specs.append(
                {
                    "key": "traffic",
                    "endpoint": "traffic",
                    "params": None,
                    "read_line": read_line_map.get("traffic", 1),
                    "ws_endpoint": "traffic",
                }
            )
        if capabilities.get("memory"):
            endpoint_specs.append(
                {
                    "key": "memory",
                    "endpoint": "memory",
                    "params": None,
                    "read_line": read_line_map.get("memory", 2),
                    "ws_endpoint": "memory",
                }
            )
        if capabilities.get("connections"):
            endpoint_specs.append(
                {
                    "key": "connections",
                    "endpoint": "connections",
                    "params": None,
                    "read_line": 0,
                    "ws_endpoint": "connections?interval=1",
                }
            )
        if capabilities.get("proxies"):
            endpoint_specs.append(
                {
                    "key": "proxies",
                    "endpoint": "proxies",
                    "params": None,
                    "read_line": 0,
                    "ws_endpoint": None,
                }
            )
        if capabilities.get("configs"):
            endpoint_specs.append(
                {
                    "key": "configs",
                    "endpoint": "configs",
                    "params": None,
                    "read_line": 0,
                    "ws_endpoint": None,
                }
            )
        if capabilities.get("providers_proxies"):
            endpoint_specs.append(
                {
                    "key": "providers_proxies",
                    "endpoint": "providers/proxies",
                    "params": None,
                    "read_line": 0,
                    "ws_endpoint": None,
                }
            )
        if capabilities.get("providers_rules"):
            endpoint_specs.append(
                {
                    "key": "providers_rules",
                    "endpoint": "providers/rules",
                    "params": None,
                    "read_line": 0,
                    "ws_endpoint": None,
                }
            )

        results = await asyncio.gather(
            *[
                self._fetch_endpoint_with_fallback(
                    key=spec["key"],
                    endpoint=spec["endpoint"],
                    params=spec["params"],
                    read_line=spec["read_line"],
                    ws_endpoint=spec["ws_endpoint"],
                    suppress_errors=suppress_errors,
                )
                for spec in endpoint_specs
            ],
            return_exceptions=True,
        )

        data: dict[str, Any] = {}
        for spec, result in zip(endpoint_specs, results):
            key = spec["key"]
            if isinstance(result, Exception):
                if not suppress_errors:
                    raise result
                continue
            if result:
                data[key] = result
            elif not suppress_errors:
                raise APIClientError(f"Missing data from {key} endpoint")

        if streaming_detection:
            streaming_data = await fetch_streaming_service_data()
            data["streaming"] = streaming_data
            _LOGGER.debug("Streaming detection data: %s", streaming_data)

        return data


class APIAuthError(Exception):
    """Exception class for auth error."""


class APIClientError(Exception):
    """Exception class for generic client error."""


class APITimeoutError(Exception):
    """Exception class for timeout error."""


class APIConnectionError(Exception):
    """Exception class for connection error."""

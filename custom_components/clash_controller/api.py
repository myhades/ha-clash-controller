"""API class for Clash Controller."""

from __future__ import annotations

from typing import Any, Optional
import asyncio
import json
import logging
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

POLLING_CAPABILITY_KEYS = (
    "proxies",
    "connections",
    "traffic",
    "memory",
    "configs",
    "providers_proxies",
    "providers_rules",
)


class ClashAPI:
    """A utility class to interact with the Clash API."""

    def __init__(
        self,
        host: str,
        token: str,
        allow_unsafe: bool = False,
        available_endpoints: Optional[list[tuple[str, dict[str, Any]]]] = None,
        capabilities: Optional[dict[str, bool]] = None,
        session: aiohttp.ClientSession | None = None,
        status_session: aiohttp.ClientSession | None = None,
    ):
        """Initialize the ClashAPI instance."""
        self.host = host
        self.token = token
        self.allow_unsafe = allow_unsafe
        self.device_id = (
            re.sub(r"[^a-zA-Z0-9]", "_", self.host.strip().lower().rstrip("_"))
            + "_device"
        )
        self._session = session
        self._status_session = status_session
        self._owns_session = session is None
        self._owns_status_session = status_session is None
        self._session_lock = asyncio.Lock()
        self._status_session_lock = asyncio.Lock()
        self._available_endpoints: Optional[list[tuple[str, dict[str, Any]]]] = (
            available_endpoints
        )
        self._capabilities: Optional[dict[str, bool]] = (
            dict(capabilities) if capabilities else None
        )
        self._transport_preferences: dict[str, str] = {}
        self._version_response: dict[str, Any] | None = None

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
        async with self._session_lock:
            if self._session is not None and not self._session.closed:
                return
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
        async with self._status_session_lock:
            if self._status_session is not None and not self._status_session.closed:
                return
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
                # Some compatible controllers, notably sing-box, return JSON
                # with a text/plain content type.
                return await response.json(content_type=None)
            line_counter = 0
            async for line in response.content:
                line_counter += 1
                if line_counter == read_line:
                    return json.loads(line.decode("utf-8").strip())
            return None

        if self._session is None:
            await self._establish_session()
        elif self._session.closed:
            raise APIClientError("HTTP session is closed")

        url = f"{self.host}{endpoint}"
        _LOGGER.debug("Making %s request to %s, read line: %s.", method, url, read_line)

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json_data,
                headers=self._request_headers(),
                timeout=aiohttp.ClientTimeout(total=15),
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
            raise APITimeoutError(f"API request timed out: {err}") from err
        except aiohttp.ClientConnectionError as err:
            raise APIConnectionError(f"API request connection error: {err}") from err
        except Exception as err:
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
        elif self._session.closed:
            raise APIClientError("HTTP session is closed")

        ws_url = self._build_ws_url(endpoint)
        ws_timeout: Any = timeout
        client_ws_timeout = getattr(aiohttp, "ClientWSTimeout", None)
        if client_ws_timeout is not None:
            ws_timeout = client_ws_timeout(ws_receive=timeout, ws_close=timeout)
        websocket: aiohttp.ClientWebSocketResponse | None = None
        try:
            websocket = await self._session.ws_connect(
                ws_url,
                headers=self._ws_headers(),
                timeout=ws_timeout,
            )
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
        finally:
            if websocket is not None and not websocket.closed:
                try:
                    await asyncio.wait_for(websocket.close(), timeout=0.5)
                except TimeoutError:
                    # A compatible core may not complete the close handshake.
                    websocket._response.close()  # noqa: SLF001
                except asyncio.CancelledError:
                    websocket._response.close()  # noqa: SLF001
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
        elif self._session.closed:
            raise APIClientError("HTTP session is closed")

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
        if self._capabilities and not force:
            return self._capabilities

        previous_capabilities = (
            dict(self._capabilities) if self._capabilities else None
        )
        previous_endpoints = list(self._available_endpoints or [])

        probe_tasks = {
            "proxies": self._probe_http_endpoint("GET", "proxies"),
            "connections": self._probe_http_endpoint("GET", "connections"),
            "traffic": self._probe_http_endpoint("GET", "traffic", read_line=1),
            "memory_first": self._probe_http_endpoint("GET", "memory", read_line=1),
            "memory_second": self._probe_http_endpoint("GET", "memory", read_line=2),
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
        http_capabilities: dict[str, bool] = {}
        for name, result in zip(probe_names, probe_results):
            http_capabilities[name] = (
                bool(result) if not isinstance(result, Exception) else False
            )

        ws_results = await asyncio.gather(
            self._probe_ws_endpoint("traffic"),
            self._probe_ws_endpoint("memory"),
            self._probe_ws_endpoint("connections?interval=1"),
            return_exceptions=True,
        )
        ws_traffic, ws_memory, ws_connections = (
            bool(result) if not isinstance(result, Exception) else False
            for result in ws_results
        )

        memory_first = http_capabilities.pop("memory_first", False)
        memory_second = http_capabilities.pop("memory_second", False)
        http_traffic = http_capabilities.get("traffic", False)
        http_connections = http_capabilities.get("connections", False)
        http_memory = memory_first or memory_second
        capabilities: dict[str, bool] = dict(http_capabilities)
        capabilities["http_traffic"] = http_traffic
        capabilities["http_memory"] = http_memory
        capabilities["http_connections"] = http_connections
        capabilities["traffic"] = http_traffic or ws_traffic
        capabilities["memory"] = http_memory or ws_memory
        capabilities["connections"] = http_connections or ws_connections

        capabilities["group_detail"] = capabilities.get("group", False)
        # A controller can expose group delay without a /group collection.
        # Groups and their members are discoverable through /proxies.
        capabilities["group_delay"] = capabilities.get("proxies", False)
        capabilities["proxy_delay"] = capabilities.get("proxies", False)
        provider_payload: dict[str, Any] = {}
        if capabilities.get("providers_proxies"):
            provider_payload = await self.async_request("GET", "providers/proxies")
        providers = provider_payload.get("providers", {})
        has_providers = isinstance(providers, dict) and bool(providers)
        capabilities["provider_healthcheck"] = has_providers
        capabilities["provider_proxy_healthcheck"] = has_providers
        capabilities["ws_traffic"] = ws_traffic
        capabilities["ws_memory"] = ws_memory
        capabilities["ws_connections"] = ws_connections
        capabilities["ws_logs"] = False

        if previous_capabilities and not any(
            capabilities.get(key, False) for key in POLLING_CAPABILITY_KEYS
        ):
            _LOGGER.debug(
                "Capability probing returned no polling endpoints for %s; "
                "retaining the previous result",
                self.host,
            )
            self._capabilities = previous_capabilities
            self._available_endpoints = previous_endpoints
            return previous_capabilities

        self._capabilities = capabilities
        self._transport_preferences.clear()
        self._available_endpoints = []
        if memory_first or memory_second:
            self._available_endpoints.append(
                ("memory", {"read_line": 2 if memory_second else 1})
            )
        if http_capabilities.get("traffic"):
            self._available_endpoints.append(("traffic", {"read_line": 1}))
        if http_capabilities.get("connections"):
            self._available_endpoints.append(("connections", {}))
        if http_capabilities.get("proxies"):
            self._available_endpoints.append(("proxies", {}))

        supported = ", ".join(
            name for name, enabled in capabilities.items() if enabled
        )
        if supported:
            _LOGGER.debug("Detected capabilities for %s: %s", self.host, supported)

        return capabilities

    async def async_close(self) -> None:
        """Close only sessions owned by this API client."""
        async with self._session_lock:
            if self._owns_session and self._session is not None:
                try:
                    await self._session.close()
                    _LOGGER.debug("Session closed successfully.")
                except Exception as err:
                    _LOGGER.warning("Failed to close session: %s", err)
                finally:
                    self._session = None

        async with self._status_session_lock:
            if self._owns_status_session and self._status_session is not None:
                try:
                    await self._status_session.close()
                except Exception as err:
                    _LOGGER.warning("Failed to close status probe session: %s", err)
                finally:
                    self._status_session = None

    async def close_session(self) -> None:
        """Close owned sessions for backward compatibility."""
        await self.async_close()

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
            self._version_response = dict(response)
        except Exception:
            if suppress_errors:
                return False
            raise
        return True

    @staticmethod
    def _infer_core_model(
        response: dict[str, Any],
        hello: dict[str, Any] | None = None,
    ) -> str:
        """Return a conservative display name without driving behavior."""
        reported_values = [
            response.get("name"),
            response.get("core"),
            response.get("product"),
            response.get("version"),
        ]
        reported = " ".join(
            value.strip()
            for value in reported_values
            if isinstance(value, str) and value.strip()
        )
        lowered = reported.lower()

        if "sing-box" in lowered:
            return "sing-box"
        if "clash-rs" in lowered or (hello or {}).get("hello") == "clash-rs":
            return "clash-rs"
        if "mihomo" in lowered:
            return "Mihomo"
        if "clash.meta" in lowered:
            return "Clash Meta"
        if response.get("premium") is True and response.get("meta") is not True:
            return "Clash Premium"
        if response.get("meta") is True:
            return "Meta-compatible core"
        return "Clash-compatible core"

    async def get_version(self) -> dict[str, str]:
        """Get normalized core version data."""
        response = self._version_response
        if response is None:
            response = await self.async_request("GET", "version")
        is_meta = response.get("meta") is True
        model = self._infer_core_model(response)
        if model == "Clash-compatible core":
            hello = await self.async_request("GET", "")
            model = self._infer_core_model(response, hello)
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
            elif self._status_session.closed:
                raise APIClientError("Status probe session is closed")
        except Exception as err:
            _LOGGER.debug("Error creating status probe session: %s", err)
            return {"latency": -1, "status_code": 000}

        request_headers = headers or {}
        start_time = time.monotonic()
        try:
            async with self._status_session.get(
                url,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
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
        capabilities = self._capabilities or {}
        http_supported = capabilities.get(
            f"http_{key}", capabilities.get(key, False)
        )
        ws_supported = bool(
            ws_endpoint and capabilities.get(f"ws_{key}", False)
        )
        preferred = self._transport_preferences.get(key)
        if preferred not in {"http", "ws"}:
            preferred = "ws" if ws_supported else "http"

        transports = [preferred]
        alternate = "http" if preferred == "ws" else "ws"
        if alternate == "http" and http_supported:
            transports.append(alternate)
        elif alternate == "ws" and ws_supported:
            transports.append(alternate)

        last_error: Exception | None = None
        for transport in transports:
            try:
                if transport == "ws":
                    response = await asyncio.wait_for(
                        self.async_ws_request(
                            ws_endpoint or endpoint,
                            suppress_errors=False,
                            timeout=3,
                        ),
                        timeout=4,
                    )
                else:
                    response = await self.async_request(
                        "GET",
                        endpoint,
                        params=params,
                        read_line=read_line,
                        suppress_errors=False,
                    )
                if response:
                    self._transport_preferences[key] = transport
                    return response
                last_error = APIClientError(
                    f"Empty {transport.upper()} response from {endpoint}"
                )
            except Exception as err:
                last_error = err
                _LOGGER.debug(
                    "%s transport failed for %s; trying fallback if available: %s",
                    transport.upper(),
                    endpoint,
                    err,
                )

        if suppress_errors:
            return {}
        if last_error is not None:
            raise last_error
        raise APIClientError(f"No supported transport for {endpoint}")

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

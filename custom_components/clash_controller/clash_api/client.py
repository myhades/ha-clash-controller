"""Client for Clash-compatible controller APIs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Optional
import asyncio
import json
import logging
import re
import ssl

import aiohttp

_LOGGER = logging.getLogger(__name__)

POLLING_CAPABILITY_KEYS = (
    "proxies",
    "connections",
    "traffic",
    "memory",
    "configs",
    "providers_proxies",
    "providers_rules",
)


class FetchResult(Mapping[str, Any]):
    """Data and endpoint failures collected during one polling cycle."""

    __slots__ = ("data", "errors")

    def __init__(
        self,
        data: dict[str, Any],
        errors: dict[str, ClashAPIError],
    ) -> None:
        self.data = data
        self.errors = errors

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


class EndpointCapability:
    """Result of probing one API transport endpoint."""

    __slots__ = ("error", "status_code", "supported")

    def __init__(
        self,
        supported: bool,
        *,
        error: ClashAPIError | None = None,
        status_code: int | None = None,
    ) -> None:
        self.supported = supported
        self.error = error
        self.status_code = status_code


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
        self._owns_session = session is None
        self._session_lock = asyncio.Lock()
        self._available_endpoints: Optional[list[tuple[str, dict[str, Any]]]] = (
            available_endpoints
        )
        self._capabilities: Optional[dict[str, bool]] = (
            dict(capabilities) if capabilities else None
        )
        self._transport_preferences: dict[str, str] = {}
        self._capability_outcomes: dict[str, EndpointCapability] = {}
        self._version_response: dict[str, Any] | None = None

    @property
    def available_endpoints(self) -> Optional[list[tuple[str, dict[str, Any]]]]:
        """Return currently available entity polling endpoints."""
        return self._available_endpoints

    @property
    def capabilities(self) -> Optional[dict[str, bool]]:
        """Return endpoint capability matrix."""
        return self._capabilities

    @property
    def capability_outcomes(self) -> dict[str, EndpointCapability]:
        """Return detailed results from the latest capability probe."""
        return self._capability_outcomes

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
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                raise APIAuthError("Invalid API credentials.") from err
            raise APIClientError(
                f"Websocket request got an invalid response: {err}"
            ) from err
        except asyncio.TimeoutError as err:
            raise APITimeoutError(f"Websocket request timed out: {err}") from err
        except aiohttp.ClientConnectionError as err:
            raise APIConnectionError(
                f"Websocket request connection error: {err}"
            ) from err
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise APIClientError(f"Error parsing websocket JSON: {err}") from err
        except aiohttp.ClientError as err:
            raise APIClientError(f"Websocket request failed: {err}") from err
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
    ) -> EndpointCapability:
        try:
            if self._session is None:
                await self._establish_session()
            elif self._session.closed:
                raise APIClientError("HTTP session is closed")

            url = f"{self.host}{endpoint}"
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
                                return EndpointCapability(True)
                        return EndpointCapability(False)
                    else:
                        response.release()
                    return EndpointCapability(True)
                if response.status in accept_statuses:
                    return EndpointCapability(True, status_code=response.status)
                if response.status in {404, 405}:
                    return EndpointCapability(False, status_code=response.status)
                if response.status in {401, 403}:
                    return EndpointCapability(
                        False,
                        error=APIAuthError("Invalid API credentials."),
                        status_code=response.status,
                    )
                return EndpointCapability(
                    False,
                    error=APIClientError(
                        f"Capability probe returned HTTP {response.status}"
                    ),
                    status_code=response.status,
                )
        except APITimeoutError as err:
            return EndpointCapability(False, error=err)
        except APIConnectionError as err:
            return EndpointCapability(False, error=err)
        except APIClientError as err:
            return EndpointCapability(False, error=err)
        except asyncio.TimeoutError as err:
            return EndpointCapability(
                False,
                error=APITimeoutError(f"Capability probe timed out: {err}"),
            )
        except aiohttp.ClientConnectionError as err:
            return EndpointCapability(
                False,
                error=APIConnectionError(
                    f"Capability probe connection error: {err}"
                ),
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            return EndpointCapability(
                False,
                error=APIClientError(f"Invalid capability probe response: {err}"),
            )
        except aiohttp.ClientError as err:
            return EndpointCapability(
                False,
                error=APIClientError(f"Capability probe failed: {err}"),
            )

    async def _probe_ws_endpoint(
        self, endpoint: str, timeout: float = 1.5
    ) -> EndpointCapability:
        try:
            payload = await asyncio.wait_for(
                self.async_ws_request(
                    endpoint,
                    timeout=timeout,
                ),
                timeout=timeout + 1.0,
            )
            return EndpointCapability(bool(payload))
        except ClashAPIError as err:
            return EndpointCapability(False, error=err)
        except asyncio.TimeoutError as err:
            return EndpointCapability(
                False,
                error=APITimeoutError(f"Capability probe timed out: {err}"),
            )

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
        probe_outcomes: dict[str, EndpointCapability] = {}
        http_capabilities: dict[str, bool] = {}
        for name, result in zip(probe_names, probe_results):
            if isinstance(result, EndpointCapability):
                outcome = result
            elif isinstance(result, ClashAPIError):
                outcome = EndpointCapability(False, error=result)
            elif isinstance(result, BaseException):
                raise result
            else:
                outcome = EndpointCapability(bool(result))
            probe_outcomes[name] = outcome
            http_capabilities[name] = outcome.supported

        ws_results = await asyncio.gather(
            self._probe_ws_endpoint("traffic"),
            self._probe_ws_endpoint("memory"),
            self._probe_ws_endpoint("connections?interval=1"),
            return_exceptions=True,
        )
        ws_capabilities: dict[str, bool] = {}
        for name, result in zip(
            ("ws_traffic", "ws_memory", "ws_connections"), ws_results
        ):
            if isinstance(result, EndpointCapability):
                outcome = result
            elif isinstance(result, ClashAPIError):
                outcome = EndpointCapability(False, error=result)
            elif isinstance(result, BaseException):
                raise result
            else:
                outcome = EndpointCapability(bool(result))
            probe_outcomes[name] = outcome
            ws_capabilities[name] = outcome.supported
        ws_traffic = ws_capabilities["ws_traffic"]
        ws_memory = ws_capabilities["ws_memory"]
        ws_connections = ws_capabilities["ws_connections"]

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
            try:
                provider_payload = await self.async_request("GET", "providers/proxies")
            except ClashAPIError as err:
                probe_outcomes["provider_healthcheck"] = EndpointCapability(
                    False, error=err
                )
        providers = provider_payload.get("providers", {})
        has_providers = isinstance(providers, dict) and bool(providers)
        if "provider_healthcheck" not in probe_outcomes:
            probe_outcomes["provider_healthcheck"] = EndpointCapability(has_providers)
        capabilities["provider_healthcheck"] = has_providers
        capabilities["provider_proxy_healthcheck"] = has_providers
        capabilities["ws_traffic"] = ws_traffic
        capabilities["ws_memory"] = ws_memory
        capabilities["ws_connections"] = ws_connections
        capabilities["ws_logs"] = False

        polling_probe_names = {
            "proxies",
            "connections",
            "traffic",
            "memory_first",
            "memory_second",
            "configs",
            "providers_proxies",
            "providers_rules",
            "ws_traffic",
            "ws_memory",
            "ws_connections",
        }
        polling_probe_failed = any(
            outcome.error is not None
            for name, outcome in probe_outcomes.items()
            if name in polling_probe_names
        )
        self._capability_outcomes = probe_outcomes
        if previous_capabilities and polling_probe_failed and not any(
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
    ) -> dict[str, Any]:
        """General async request method."""
        response = await self._request(
            method,
            endpoint,
            params=params,
            json_data=json_data,
            read_line=read_line,
        )
        return response or {}

    async def connected(self) -> bool:
        """Check if API connection is successful by reading /version."""
        response = await self._request("GET", "version")
        if "version" not in response:
            raise APIClientError(
                "Missing version key in response. Is this endpoint running Clash?"
            )
        self._version_response = dict(response)
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
                    )
                if response:
                    self._transport_preferences[key] = transport
                    return response
                last_error = APIClientError(
                    f"Empty {transport.upper()} response from {endpoint}"
                )
            except ClashAPIError as err:
                last_error = err
                _LOGGER.debug(
                    "%s transport failed for %s; trying fallback if available: %s",
                    transport.upper(),
                    endpoint,
                    err,
                )

        if last_error is not None:
            raise last_error
        raise APIClientError(f"No supported transport for {endpoint}")

    async def fetch_data(self) -> FetchResult:
        """Get all endpoint data needed by the coordinator."""

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
                )
                for spec in endpoint_specs
            ],
            return_exceptions=True,
        )

        data: dict[str, Any] = {}
        errors: dict[str, ClashAPIError] = {}
        for spec, result in zip(endpoint_specs, results):
            key = spec["key"]
            if isinstance(result, ClashAPIError):
                errors[key] = result
                continue
            if isinstance(result, BaseException):
                raise result
            if result:
                data[key] = result
            else:
                errors[key] = APIClientError(
                    f"Missing data from {key} endpoint"
                )

        return FetchResult(data, errors)


class ClashAPIError(Exception):
    """Base exception for Clash API failures."""


class APIAuthError(ClashAPIError):
    """Exception class for auth error."""


class APIClientError(ClashAPIError):
    """Exception class for generic client error."""


class APIConnectionError(ClashAPIError):
    """Exception class for connection error."""


class APITimeoutError(APIConnectionError):
    """Exception class for timeout error."""

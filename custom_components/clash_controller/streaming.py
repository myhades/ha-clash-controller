"""Streaming service availability detection."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp
from yarl import URL

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
            0: "unavailable",
        },
    },
}


class InvalidStreamingProxyError(ValueError):
    """Raised when a streaming proxy address is malformed."""


class StreamingProxyConnectionError(Exception):
    """Raised when the configured streaming proxy cannot be reached."""


class StreamingProxyAuthError(StreamingProxyConnectionError):
    """Raised when the configured streaming proxy rejects authentication."""


class StreamingProxyTimeoutError(StreamingProxyConnectionError):
    """Raised when the configured streaming proxy times out."""


@dataclass(frozen=True, slots=True)
class StreamingProxy:
    """Normalized HTTP proxy details."""

    url: URL
    headers: dict[str, str] | None = None


def parse_streaming_proxy(value: str) -> StreamingProxy:
    """Parse a user-provided HTTP proxy address."""
    raw_value = value.strip()
    if not raw_value:
        raise InvalidStreamingProxyError

    try:
        proxy = URL(raw_value if "://" in raw_value else f"http://{raw_value}")
        port = proxy.explicit_port
    except (TypeError, ValueError) as err:
        raise InvalidStreamingProxyError from err

    if (
        proxy.scheme != "http"
        or proxy.host is None
        or port is None
        or proxy.path not in {"", "/"}
        or proxy.query_string
        or proxy.fragment
    ):
        raise InvalidStreamingProxyError

    username = proxy.user
    password = proxy.password
    if (username is None) is not (password is None) or username == "":
        raise InvalidStreamingProxyError

    headers = (
        {"Proxy-Authorization": aiohttp.encode_basic_auth(username, password or "")}
        if username is not None
        else None
    )
    return StreamingProxy(
        url=URL.build(scheme="http", host=proxy.host, port=port),
        headers=headers,
    )


class StreamingDetector:
    """Check streaming services through an injected HTTP session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        proxy: StreamingProxy,
    ) -> None:
        self._session = session
        self._proxy = proxy

    async def async_validate_proxy(self) -> None:
        """Verify that the proxy can reach the streaming test endpoint."""
        try:
            async with self._session.get(
                SERVICE_TABLE["netflix"]["url"],
                proxy=self._proxy.url,
                proxy_headers=self._proxy.headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 407:
                    raise StreamingProxyAuthError
        except asyncio.TimeoutError as err:
            raise StreamingProxyTimeoutError from err
        except aiohttp.ClientError as err:
            if getattr(err, "status", None) == 407:
                raise StreamingProxyAuthError from err
            raise StreamingProxyConnectionError from err

    async def async_get_url_status(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, float | int]:
        """Get the status code and latency to a third-party URL."""
        request_headers = headers or {}
        start_time = time.monotonic()
        try:
            async with self._session.get(
                url,
                headers=request_headers,
                proxy=self._proxy.url,
                proxy_headers=self._proxy.headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                duration = time.monotonic() - start_time
                return {
                    "latency": duration,
                    "status_code": 0 if response.status == 407 else response.status,
                }
        except asyncio.TimeoutError:
            return {"latency": -1, "status_code": 0}
        except aiohttp.ClientError as err:
            duration = time.monotonic() - start_time
            _LOGGER.debug("Error getting status code for %s: %s", url, err)
            return {"latency": duration, "status_code": 0}

    async def async_fetch_data(self) -> dict[str, Any]:
        """Fetch availability data for configured streaming services."""
        results = await asyncio.gather(
            *[
                self.async_get_url_status(details["url"])
                for details in SERVICE_TABLE.values()
            ]
        )
        return dict(zip(SERVICE_TABLE, results))

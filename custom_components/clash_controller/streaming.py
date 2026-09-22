"""Streaming service availability detection."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import aiohttp
from yarl import URL

_LOGGER = logging.getLogger(__name__)

STATE_AVAILABLE = "available"
STATE_LIMITED = "limited"
STATE_BLOCKED = "blocked"
STATE_UNKNOWN = "unknown"
STREAMING_STATES = [STATE_AVAILABLE, STATE_LIMITED, STATE_BLOCKED, STATE_UNKNOWN]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": _USER_AGENT,
}


@dataclass(frozen=True, slots=True)
class StreamingService:
    """Static definition for a streaming service sensor."""

    name: str
    url: str
    checker: str
    enabled_default: bool = False


SERVICE_TABLE: dict[str, StreamingService] = {
    "netflix": StreamingService(
        name="Netflix",
        url="https://www.netflix.com/title/81280792",
        checker="_async_check_netflix",
        enabled_default=True,
    ),
    "youtube_premium": StreamingService(
        name="YouTube Premium",
        url="https://www.youtube.com/premium",
        checker="_async_check_youtube_premium",
    ),
    "prime_video": StreamingService(
        name="Prime Video",
        url="https://www.primevideo.com/",
        checker="_async_check_prime_video",
    ),
    "bbc_iplayer": StreamingService(
        name="BBC iPlayer",
        url=(
            "https://open.live.bbc.co.uk/mediaselector/6/select/version/2.0/"
            "mediaset/pc/vpid/bbc_one_london/format/json/jsfunc/JS_callbacks0"
        ),
        checker="_async_check_bbc_iplayer",
    ),
    "paramount_plus": StreamingService(
        name="Paramount+",
        url="https://www.paramountplus.com/",
        checker="_async_check_paramount_plus",
    ),
    "peacock": StreamingService(
        name="Peacock",
        url="https://www.peacocktv.com/",
        checker="_async_check_peacock",
    ),
    "max": StreamingService(
        name="Max",
        url="https://www.max.com/",
        checker="_async_check_max",
    ),
    "dazn": StreamingService(
        name="DAZN",
        url="https://startup.core.indazn.com/misl/v5/Startup",
        checker="_async_check_dazn",
    ),
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


@dataclass(frozen=True, slots=True)
class StreamingResponse:
    """Response data shared by service-specific checkers."""

    status_code: int
    latency: float
    url: str
    body: str = ""
    error: str | None = None
    response_headers: str = ""


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
        self._checker_errors: dict[str, type[Exception]] = {}

    async def async_validate_proxy(self) -> None:
        """Verify that the proxy can reach the streaming test endpoint."""
        try:
            async with self._session.get(
                SERVICE_TABLE["netflix"].url,
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

    async def _async_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> StreamingResponse:
        """Send a request and retain only the data required by checkers."""
        start_time = time.monotonic()
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data,
                proxy=self._proxy.url,
                proxy_headers=self._proxy.headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                body = await response.text(errors="replace")
                return StreamingResponse(
                    status_code=response.status,
                    latency=time.monotonic() - start_time,
                    url=str(response.url),
                    body=body,
                    error="proxy_authentication" if response.status == 407 else None,
                    response_headers="\n".join(
                        f"{name}: {value}"
                        for hop in (*response.history, response)
                        for name, value in hop.headers.items()
                    ),
                )
        except asyncio.TimeoutError:
            return StreamingResponse(
                status_code=0,
                latency=time.monotonic() - start_time,
                url=url,
                error="timeout",
            )
        except aiohttp.ClientError as err:
            _LOGGER.debug("Error checking streaming URL %s: %s", url, err)
            proxy_auth_failed = getattr(err, "status", None) == 407
            return StreamingResponse(
                status_code=407 if proxy_auth_failed else 0,
                latency=time.monotonic() - start_time,
                url=url,
                error="proxy_authentication" if proxy_auth_failed else "connection_error",
            )

    @staticmethod
    def _result(
        response: StreamingResponse,
        state: str,
        **attributes: Any,
    ) -> dict[str, Any]:
        """Build the normalized result exposed by every checker."""
        result: dict[str, Any] = {
            "state": state,
            "latency": response.latency,
            "status_code": response.status_code,
        }
        if response.error is not None:
            result["reason"] = response.error
        result.update(attributes)
        return result

    async def _async_check_netflix(self) -> dict[str, Any]:
        responses = await asyncio.gather(
            *(
                self._async_request("GET", url, headers=_BROWSER_HEADERS)
                for url in (
                    SERVICE_TABLE["netflix"].url,
                    "https://www.netflix.com/title/70143836",
                )
            )
        )
        for response in responses:
            if response.error is not None:
                return self._result(response, STATE_UNKNOWN)
        for response in responses:
            if response.status_code == 403:
                return self._result(response, STATE_BLOCKED)
            if response.status_code != 200 or not response.body.strip():
                return self._result(response, STATE_UNKNOWN)

        response = responses[0]
        attributes: dict[str, Any] = {
            "latency": max(item.latency for item in responses),
        }
        if all("Oh no!" in item.body for item in responses):
            return self._result(
                response, STATE_LIMITED, access_level="originals_only", **attributes
            )
        region_match = re.search(
            r'"id"\s*:\s*"([A-Za-z]{2})"\s*,\s*"countryName"\s*:',
            response.body,
        )
        if region_match:
            attributes["region"] = region_match.group(1).upper()
        return self._result(
            response, STATE_AVAILABLE, access_level="full_catalog", **attributes
        )

    async def _async_check_youtube_premium(self) -> dict[str, Any]:
        response = await self._async_request(
            "GET", SERVICE_TABLE["youtube_premium"].url, headers=_BROWSER_HEADERS
        )
        body = response.body
        region_match = re.search(r'"INNERTUBE_CONTEXT_GL"\s*:\s*"([^"]+)"', body)
        region = region_match.group(1).upper() if region_match else None
        if "www.google.cn" in body:
            return self._result(response, STATE_BLOCKED, region="CN")
        if "premium is not available in your country" in body.lower():
            return self._result(response, STATE_BLOCKED, **self._region(region))
        if "ad-free" in body.lower():
            return self._result(response, STATE_AVAILABLE, **self._region(region))
        return self._result(response, STATE_UNKNOWN, **self._region(region))

    async def _async_check_prime_video(self) -> dict[str, Any]:
        response = await self._async_request(
            "GET", SERVICE_TABLE["prime_video"].url, headers=_BROWSER_HEADERS
        )
        region_match = re.search(r'"currentTerritory"\s*:\s*"([^"]+)"', response.body)
        region = region_match.group(1).upper() if region_match else None
        restricted = re.search(
            r'"?isServiceRestricted"?\s*:\s*true', response.body, re.IGNORECASE
        )
        if restricted:
            return self._result(response, STATE_BLOCKED, **self._region(region))
        if region is not None:
            return self._result(response, STATE_AVAILABLE, region=region)
        return self._result(response, STATE_UNKNOWN)

    async def _async_check_bbc_iplayer(self) -> dict[str, Any]:
        response = await self._async_request(
            "GET", SERVICE_TABLE["bbc_iplayer"].url, headers=_BROWSER_HEADERS
        )
        body = response.body.lower()
        if "geolocation" in body:
            return self._result(response, STATE_BLOCKED)
        if "vs-hls-push-uk" in body:
            return self._result(response, STATE_AVAILABLE, region="GB")
        return self._result(response, STATE_UNKNOWN)

    async def _async_check_paramount_plus(self) -> dict[str, Any]:
        response = await self._async_request(
            "GET", SERVICE_TABLE["paramount_plus"].url, headers=_BROWSER_HEADERS
        )
        path_parts = [part for part in URL(response.url).path.split("/") if part]
        path_prefix = path_parts[0].upper() if path_parts else ""
        if path_prefix == "INTL":
            return self._result(response, STATE_BLOCKED, redirect_url=response.url)
        if response.status_code == 200:
            region = path_prefix if len(path_prefix) == 2 else "US"
            return self._result(
                response,
                STATE_AVAILABLE,
                region=region,
                redirect_url=response.url,
            )
        return self._result(response, STATE_UNKNOWN, redirect_url=response.url)

    async def _async_check_peacock(self) -> dict[str, Any]:
        response = await self._async_request(
            "GET", SERVICE_TABLE["peacock"].url, headers=_BROWSER_HEADERS
        )
        if "unavailable" in response.url.lower():
            return self._result(response, STATE_BLOCKED, redirect_url=response.url)
        if response.status_code == 200:
            return self._result(response, STATE_AVAILABLE, redirect_url=response.url)
        return self._result(response, STATE_UNKNOWN, redirect_url=response.url)

    async def _async_check_max(self) -> dict[str, Any]:
        response = await self._async_request(
            "GET", SERVICE_TABLE["max"].url, headers=_BROWSER_HEADERS
        )
        region_match = re.search(
            r"countryCode=([A-Z]{2})",
            response.response_headers + "\n" + response.body,
        )
        if region_match is None:
            return self._result(response, STATE_UNKNOWN)
        region = region_match.group(1)
        supported_regions = {
            match.upper()
            for match in re.findall(r'"url"\s*:\s*"/([a-z]{2})/[a-z]{2}"', response.body)
        }
        supported_regions.add("US")
        return self._result(
            response,
            STATE_AVAILABLE if region in supported_regions else STATE_BLOCKED,
            region=region,
        )

    async def _async_check_dazn(self) -> dict[str, Any]:
        headers = {
            **_BROWSER_HEADERS,
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.dazn.com",
            "Referer": "https://www.dazn.com/",
            "X-Session-Id": str(uuid4()),
        }
        response = await self._async_request(
            "POST",
            SERVICE_TABLE["dazn"].url,
            headers=headers,
            json_data={
                "Version": "2",
                "LandingPageKey": "generic",
                "Languages": "en-US",
                "Platform": "web",
                "Manufacturer": "",
                "PromoCode": "",
                "PlatformAttributes": {},
            },
        )
        if "security policy has been breached" in response.body.lower():
            return self._result(response, STATE_BLOCKED, reason="security_policy")
        try:
            payload = json.loads(response.body)
        except (TypeError, ValueError):
            return self._result(response, STATE_UNKNOWN)
        if not isinstance(payload, dict):
            return self._result(response, STATE_UNKNOWN)
        region_data = payload.get("Region", payload)
        if not isinstance(region_data, dict):
            return self._result(response, STATE_UNKNOWN)
        allowed = region_data.get("isAllowed")
        region = region_data.get("GeolocatedCountry")
        attributes = self._region(region.upper() if isinstance(region, str) else None)
        if allowed is True:
            return self._result(response, STATE_AVAILABLE, **attributes)
        if allowed is False:
            return self._result(response, STATE_BLOCKED, **attributes)
        return self._result(response, STATE_UNKNOWN, **attributes)

    @staticmethod
    def _region(region: str | None) -> dict[str, str]:
        """Return an optional region attribute without exposing null values."""
        return {"region": region} if region else {}

    async def async_fetch_data(
        self, services: Collection[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """Fetch availability data for enabled streaming services."""
        selected = [
            service
            for service in SERVICE_TABLE
            if services is None or service in services
        ]

        async def check_service(service: str) -> dict[str, Any]:
            try:
                checker = getattr(self, SERVICE_TABLE[service].checker)
                result = await checker()
            except Exception as err:
                if self._checker_errors.get(service) is not type(err):
                    _LOGGER.exception("Unexpected error checking streaming service %s", service)
                else:
                    _LOGGER.debug(
                        "Streaming checker %s still failing: %s", service, type(err).__name__
                    )
                self._checker_errors[service] = type(err)
                return {"state": STATE_UNKNOWN, "reason": "checker_error"}
            if self._checker_errors.pop(service, None) is not None:
                _LOGGER.info("Streaming checker %s recovered", service)
            return result

        results = await asyncio.gather(*(check_service(service) for service in selected))
        return dict(zip(selected, results))

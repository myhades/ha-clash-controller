"""Streaming service availability detection."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

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
            0: "unavailable",
        },
    },
}


class StreamingDetector:
    """Check streaming services through an injected HTTP session."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

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
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                duration = time.monotonic() - start_time
                return {"latency": duration, "status_code": response.status}
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

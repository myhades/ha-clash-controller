"""Controllable localhost proxy used to inject controller API failures."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

import aiohttp
from aiohttp import web


@dataclass(frozen=True)
class Fault:
    """One endpoint fault injected before forwarding to the real core."""

    mode: Literal["status", "malformed", "drop"]
    status: int = 500


class ControllerFaultProxy:
    """Forward controller traffic while allowing endpoint-specific failures."""

    def __init__(self, target_url: str) -> None:
        self.target_url = target_url.rstrip("/")
        self.url = ""
        self._faults: dict[str, Fault] = {}
        self._session: aiohttp.ClientSession | None = None

    def app(self) -> web.Application:
        """Build the aiohttp application hosted by the pytest server."""
        application = web.Application()
        application.router.add_route("*", "/{endpoint:.*}", self._handle)
        return application

    def set_status(self, endpoint: str, status: int = 500) -> None:
        """Return a fixed HTTP error for an endpoint."""
        self._faults[endpoint.lstrip("/")] = Fault("status", status)

    def set_malformed(self, endpoint: str) -> None:
        """Return non-JSON content with a successful status."""
        self._faults[endpoint.lstrip("/")] = Fault("malformed")

    def set_drop(self, endpoint: str) -> None:
        """Drop the client transport before sending a response."""
        self._faults[endpoint.lstrip("/")] = Fault("drop")

    def clear(self, endpoint: str | None = None) -> None:
        """Remove one fault or reset the proxy."""
        if endpoint is None:
            self._faults.clear()
        else:
            self._faults.pop(endpoint.lstrip("/"), None)

    async def close(self) -> None:
        """Close the forwarding client."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _client(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        endpoint = request.match_info["endpoint"]
        if fault := self._faults.get(endpoint):
            if fault.mode == "status":
                return web.json_response({"test_fault": endpoint}, status=fault.status)
            if fault.mode == "malformed":
                return web.Response(text="not-json", content_type="text/plain")
            if request.transport is not None:
                request.transport.abort()
            raise ConnectionResetError(f"injected connection drop for {endpoint}")

        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._forward_websocket(request, endpoint)
        return await self._forward_http(request, endpoint)

    def _forward_headers(self, request: web.Request) -> dict[str, str]:
        return {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "content-length", "connection", "upgrade"}
        }

    async def _forward_http(
        self, request: web.Request, endpoint: str
    ) -> web.StreamResponse:
        client = await self._client()
        body = await request.read()
        upstream = await client.request(
            request.method,
            f"{self.target_url}/{endpoint}",
            params=request.query,
            data=body or None,
            headers=self._forward_headers(request),
        )
        response = web.StreamResponse(
            status=upstream.status,
            headers={
                key: value
                for key, value in upstream.headers.items()
                if key.lower()
                not in {"content-length", "transfer-encoding", "connection"}
            },
        )
        await response.prepare(request)
        try:
            async for chunk in upstream.content.iter_chunked(64 * 1024):
                await response.write(chunk)
            await response.write_eof()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            upstream.close()
        return response

    async def _forward_websocket(
        self, request: web.Request, endpoint: str
    ) -> web.WebSocketResponse:
        client = await self._client()
        frontend = web.WebSocketResponse()
        await frontend.prepare(request)
        target = f"{self.target_url}/{endpoint}".replace("http://", "ws://", 1).replace(
            "https://", "wss://", 1
        )
        try:
            async with client.ws_connect(
                target,
                headers=self._forward_headers(request),
            ) as backend:
                message = await backend.receive()
                if message.type is aiohttp.WSMsgType.TEXT:
                    await frontend.send_str(message.data)
                elif message.type is aiohttp.WSMsgType.BINARY:
                    await frontend.send_bytes(message.data)
        finally:
            await frontend.close()
        return frontend

"""API contracts using local responses; no external core or internet."""

import asyncio
from collections import Counter

import aiohttp
import pytest
from aiohttp import web

from custom_components.clash_controller.clash_api import (
    APIAuthError,
    APIClientError,
    APIConnectionError,
    APITimeoutError,
    ClashAPI,
    EndpointCapability,
)
from custom_components.clash_controller.streaming import StreamingDetector

pytestmark = pytest.mark.enable_socket


@pytest.mark.parametrize(
    ("payload", "hello", "model"),
    [
        ({"name": "mihomo"}, None, "Mihomo"),
        ({"name": "clash.meta"}, None, "Clash Meta"),
        ({"premium": True}, None, "Clash Premium"),
        ({"meta": True, "version": "v1.16.5"}, None, "Meta-compatible core"),
        ({"meta": True, "version": "v1.17.0"}, None, "Meta-compatible core"),
        ({"version": "1.0"}, {"hello": "clash-rs"}, "clash-rs"),
        ({"version": "sing-box 1.14"}, None, "sing-box"),
        ({"name": "Clash"}, None, "Clash-compatible core"),
    ],
)
def test_core_identity(payload, hello, model):
    assert ClashAPI._infer_core_model(payload, hello) == model


@pytest.mark.parametrize(
    ("body", "line", "expected"),
    [
        ('{"value": 1}', 0, {"value": 1}),
        ('{"value": 1}\n{"value": 2}\n', 1, {"value": 1}),
        ('{"value": 1}\n{"value": 2}\n', 2, {"value": 2}),
    ],
)
async def test_response_reading(aiohttp_server, body, line, expected):
    async def handler(request):
        assert request.headers["Authorization"] == "Bearer token"
        return web.Response(text=body, content_type="text/plain")

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    api = ClashAPI(str(server.make_url("/")), "token")
    try:
        assert await api.async_request("GET", "", read_line=line) == expected
    finally:
        await api.async_close()


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, "{}", APIAuthError),
        (500, "{}", APIClientError),
        (404, "{}", APIClientError),
        (200, "invalid", APIClientError),
    ],
)
async def test_http_errors(aiohttp_server, status, body, error):
    async def handler(request):
        return web.Response(status=status, text=body)

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    api = ClashAPI(str(server.make_url("/")), "")
    try:
        with pytest.raises(error):
            await api.async_request("GET", "")
        outcome = await api._probe_http_endpoint("GET", "", read_line=1)
        assert not outcome.supported
        if status == 404:
            assert outcome.error is None
            assert outcome.status_code == 404
        else:
            assert isinstance(outcome.error, error)
    finally:
        await api.async_close()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (asyncio.TimeoutError(), APITimeoutError),
        (aiohttp.ClientConnectionError(), APIConnectionError),
        (asyncio.CancelledError(), asyncio.CancelledError),
    ],
)
async def test_transport_errors_and_cancellation(failure, expected):
    class Session:
        closed = False

        def request(self, *args, **kwargs):
            raise failure

    api = ClashAPI("http://localhost/", "", session=Session())
    with pytest.raises(expected):
        await api.async_request("GET", "version")


async def test_capability_cache_and_probe_outcomes(monkeypatch):
    api = ClashAPI("http://localhost/", "", capabilities={})
    mode = "supported"
    calls = Counter()

    async def http(method, endpoint, **kwargs):
        calls[endpoint] += 1
        if mode == "failed":
            return EndpointCapability(False, error=APIConnectionError("offline"))
        return EndpointCapability(endpoint in {"proxies", "configs"}, status_code=404)

    async def ws(endpoint, **kwargs):
        return EndpointCapability(mode == "supported")

    monkeypatch.setattr(api, "_probe_http_endpoint", http)
    monkeypatch.setattr(api, "_probe_ws_endpoint", ws)
    initial = dict(await api.async_detect_capabilities())
    assert initial["traffic"] and initial["ws_traffic"] and not initial["http_traffic"]
    assert api.capability_outcomes["rules"].error is None
    before = calls.copy()
    assert await api.async_detect_capabilities() == initial
    assert calls == before
    mode = "failed"
    assert await api.async_detect_capabilities(force=True) == initial
    assert api.capability_outcomes["proxies"].error is not None
    mode = "unsupported"
    refreshed = await api.async_detect_capabilities(force=True)
    assert not refreshed["traffic"] and refreshed["proxies"]


async def test_polling_fallback_and_partial_errors(monkeypatch):
    api = ClashAPI(
        "http://localhost/",
        "",
        capabilities={
            "traffic": True,
            "http_traffic": True,
            "ws_traffic": True,
            "proxies": True,
        },
    )
    calls = []
    broken = {"ws"}

    async def ws(*args, **kwargs):
        calls.append("ws")
        if "ws" in broken:
            raise APITimeoutError("ws")
        return {"up": 0, "down": 1}

    async def http(method, endpoint, **kwargs):
        calls.append(endpoint)
        if endpoint == "proxies" or "http" in broken:
            raise APIConnectionError(endpoint)
        return {"up": 0, "down": 1}

    monkeypatch.setattr(api, "async_ws_request", ws)
    monkeypatch.setattr(api, "async_request", http)
    result = await api.fetch_data()
    assert result.data == {"traffic": {"up": 0, "down": 1}}
    assert set(result.errors) == {"proxies"}
    assert Counter(calls) == Counter(["ws", "traffic", "proxies"])
    calls.clear()
    await api.fetch_data()
    assert Counter(calls) == Counter(["traffic", "proxies"])
    broken = {"http"}
    calls.clear()
    assert "traffic" in (await api.fetch_data()).data
    assert Counter(calls) == Counter(["traffic", "ws", "proxies"])
    broken = {"http", "ws"}
    calls.clear()
    assert set((await api.fetch_data()).errors) == {"traffic", "proxies"}
    assert Counter(calls) == Counter(["ws", "traffic", "proxies"])


@pytest.mark.parametrize("owned", [True, False])
async def test_session_ownership(aiohttp_server, owned):
    async def handler(request):
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    async with aiohttp.ClientSession() as shared:
        api = ClashAPI(str(server.make_url("/")), "", session=None if owned else shared)
        await api.async_request("GET", "")
        session = api._session
        await api.async_close()
        await api.async_close()
        assert session.closed is owned
        assert not shared.closed


@pytest.mark.parametrize("mode", ["text", "binary", "timeout", "cancel"])
async def test_websocket_read_and_cleanup(aiohttp_server, mode):
    closed = asyncio.Event()
    ready = asyncio.Event()

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        ready.set()
        if mode == "text":
            await ws.send_str('{"up": 1}')
        elif mode == "binary":
            await ws.send_bytes(b'{"up": 1}')
        try:
            async for _ in ws:
                pass
        finally:
            closed.set()
        return ws

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    async with aiohttp.ClientSession() as shared:
        api = ClashAPI(str(server.make_url("/")), "", session=shared)
        task = asyncio.create_task(
            api.async_ws_request("", timeout=0.05 if mode == "timeout" else 1)
        )
        await ready.wait()
        if mode == "cancel":
            task.cancel()
        if mode in {"timeout", "cancel"}:
            with pytest.raises(
                APITimeoutError if mode == "timeout" else asyncio.CancelledError
            ):
                await task
        else:
            assert await task == {"up": 1}
        await asyncio.wait_for(closed.wait(), 2)
        assert not shared.closed


@pytest.mark.parametrize("status", [200, 403, 404])
async def test_streaming_status(aiohttp_server, status):
    async def handler(request):
        return web.Response(status=status)

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    async with aiohttp.ClientSession() as session:
        result = await StreamingDetector(session).async_get_url_status(
            str(server.make_url("/"))
        )
        assert result["status_code"] == status
        assert result["latency"] >= 0

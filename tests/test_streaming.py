"""Streaming detector contracts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.clash_controller.streaming import (
    InvalidStreamingProxyError,
    StreamingDetector,
    StreamingProxyAuthError,
    StreamingProxyConnectionError,
    StreamingProxyTimeoutError,
    parse_streaming_proxy,
)


@pytest.mark.parametrize(
    ("value", "url", "username", "password"),
    [
        ("proxy.local:7890", "http://proxy.local:7890", None, None),
        ("http://proxy.local:7890", "http://proxy.local:7890", None, None),
        (
            "http://user%40name:p%3A%40ss@proxy.local:7890",
            "http://proxy.local:7890",
            "user@name",
            "p:@ss",
        ),
        ("[fd00::1]:7890", "http://[fd00::1]:7890", None, None),
    ],
)
def test_parse_streaming_proxy(value, url, username, password):
    proxy = parse_streaming_proxy(value)

    assert str(proxy.url) == url
    assert proxy.headers == (
        {"Proxy-Authorization": aiohttp.encode_basic_auth(username, password)}
        if username is not None
        else None
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "proxy.local",
        "https://proxy.local:7890",
        "user@proxy.local:7890",
        "proxy.local:7890/path",
        "proxy.local:7890?query=value",
    ],
)
def test_reject_invalid_streaming_proxy(value):
    with pytest.raises(InvalidStreamingProxyError):
        parse_streaming_proxy(value)


@pytest.mark.parametrize("status", [200, 403, 404, 407])
async def test_streaming_status_uses_proxy(status):
    response = AsyncMock()
    response.__aenter__.return_value = SimpleNamespace(status=status)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.return_value = response
    proxy = parse_streaming_proxy("user:password@proxy.local:7890")

    result = await StreamingDetector(session, proxy).async_get_url_status(
        "https://streaming.example/title"
    )

    assert result["status_code"] == (0 if status == 407 else status)
    assert result["latency"] >= 0
    assert session.get.call_args.kwargs["proxy"] == proxy.url
    assert session.get.call_args.kwargs["proxy_headers"] == proxy.headers


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (asyncio.TimeoutError(), StreamingProxyTimeoutError),
        (aiohttp.ClientConnectionError(), StreamingProxyConnectionError),
    ],
)
async def test_proxy_validation_errors(side_effect, error):
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.side_effect = side_effect
    detector = StreamingDetector(session, parse_streaming_proxy("proxy.local:7890"))

    with pytest.raises(error):
        await detector.async_validate_proxy()


async def test_proxy_validation_rejects_authentication_failure():
    response = AsyncMock()
    response.__aenter__.return_value = SimpleNamespace(status=407)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.return_value = response
    detector = StreamingDetector(session, parse_streaming_proxy("proxy.local:7890"))

    with pytest.raises(StreamingProxyAuthError):
        await detector.async_validate_proxy()


async def test_runtime_proxy_failure_returns_unavailable():
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.side_effect = aiohttp.ClientConnectionError()
    detector = StreamingDetector(session, parse_streaming_proxy("proxy.local:7890"))

    result = await detector.async_get_url_status("https://streaming.example/title")

    assert result["status_code"] == 0
    assert result["latency"] >= 0

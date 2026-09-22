"""Streaming detector contracts."""

import asyncio
import logging
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
    StreamingResponse,
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
    response.__aenter__.return_value = SimpleNamespace(
        status=status,
        url="https://streaming.example/title",
        text=AsyncMock(return_value="response body"),
        headers={"Content-Type": "text/html"},
        history=(SimpleNamespace(headers={"Set-Cookie": "countryCode=FR"}),),
    )
    session = MagicMock(spec=aiohttp.ClientSession)
    session.request.return_value = response
    proxy = parse_streaming_proxy("user:password@proxy.local:7890")

    result = await StreamingDetector(session, proxy)._async_request(
        "GET", "https://streaming.example/title"
    )

    assert result.status_code == status
    assert "countryCode=FR" in result.response_headers
    assert "Content-Type: text/html" in result.response_headers
    assert result.latency >= 0
    assert result.error == ("proxy_authentication" if status == 407 else None)
    assert session.request.call_args.kwargs["proxy"] == proxy.url
    assert session.request.call_args.kwargs["proxy_headers"] == proxy.headers


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


async def test_runtime_proxy_failure_returns_unknown():
    session = MagicMock(spec=aiohttp.ClientSession)
    session.request.side_effect = aiohttp.ClientConnectionError()
    detector = StreamingDetector(session, parse_streaming_proxy("proxy.local:7890"))

    result = await detector._async_request(
        "GET", "https://streaming.example/title"
    )

    assert result.status_code == 0
    assert result.latency >= 0
    assert result.error == "connection_error"


@pytest.mark.parametrize(
    ("checker", "response", "state", "attributes"),
    [
        (
            "_async_check_netflix",
            StreamingResponse(404, 0.1, "https://www.netflix.com/title/81280792"),
            "limited",
            {"access_level": "originals_only"},
        ),
        (
            "_async_check_youtube_premium",
            StreamingResponse(
                200,
                0.1,
                "https://www.youtube.com/premium",
                '"INNERTUBE_CONTEXT_GL":"JP" ad-free',
            ),
            "available",
            {"region": "JP"},
        ),
        (
            "_async_check_prime_video",
            StreamingResponse(
                200,
                0.1,
                "https://www.primevideo.com/",
                '"isServiceRestricted":true,"currentTerritory":"CN"',
            ),
            "blocked",
            {"region": "CN"},
        ),
        (
            "_async_check_bbc_iplayer",
            StreamingResponse(200, 0.1, "https://open.live.bbc.co.uk", "vs-hls-push-uk"),
            "available",
            {"region": "GB"},
        ),
        (
            "_async_check_paramount_plus",
            StreamingResponse(200, 0.1, "https://www.paramountplus.com/intl/"),
            "blocked",
            {},
        ),
        (
            "_async_check_peacock",
            StreamingResponse(200, 0.1, "https://www.peacocktv.com/"),
            "available",
            {},
        ),
        (
            "_async_check_max",
            StreamingResponse(
                200,
                0.1,
                "https://www.max.com/",
                '"url":"/fr/fr"',
                response_headers="Set-Cookie: countryCode=FR; Path=/",
            ),
            "available",
            {"region": "FR"},
        ),
        (
            "_async_check_dazn",
            StreamingResponse(
                200,
                0.1,
                "https://startup.core.indazn.com/misl/v5/Startup",
                '{"Region":{"isAllowed":true,"GeolocatedCountry":"de"}}',
            ),
            "available",
            {"region": "DE"},
        ),
        (
            "_async_check_dazn",
            StreamingResponse(200, 0.1, "https://startup.core.indazn.com/", "[]"),
            "unknown",
            {},
        ),
    ],
)
async def test_service_checkers_use_normalized_states(
    checker, response, state, attributes
):
    detector = StreamingDetector(
        MagicMock(spec=aiohttp.ClientSession),
        parse_streaming_proxy("proxy.local:7890"),
    )
    detector._async_request = AsyncMock(return_value=response)

    result = await getattr(detector, checker)()

    assert result["state"] == state
    assert set(result) >= {"state", "status_code", "latency", *attributes}
    for key, value in attributes.items():
        assert result[key] == value


async def test_checker_failure_is_isolated_and_cancellation_propagates(caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.clash_controller.streaming")
    detector = StreamingDetector(
        MagicMock(spec=aiohttp.ClientSession),
        parse_streaming_proxy("proxy.local:7890"),
    )
    netflix = {"state": "available", "status_code": 200, "latency": 0.1}
    detector._async_check_netflix = AsyncMock(return_value=netflix)
    detector._async_check_dazn = AsyncMock(side_effect=ValueError("unexpected payload"))

    result = await detector.async_fetch_data({"netflix", "dazn"})

    assert result == {
        "netflix": netflix,
        "dazn": {"state": "unknown", "reason": "checker_error"},
    }
    assert "Unexpected error checking streaming service dazn" in caplog.text
    await detector.async_fetch_data({"dazn"})
    assert "Streaming checker dazn still failing: ValueError" in caplog.text
    assert len([record for record in caplog.records if record.exc_info]) == 1
    detector._async_check_dazn.side_effect = TypeError("different failure")
    await detector.async_fetch_data({"dazn"})
    assert len([record for record in caplog.records if record.exc_info]) == 2
    detector._async_check_dazn.side_effect = None
    detector._async_check_dazn.return_value = {"state": "unknown"}
    await detector.async_fetch_data({"dazn"})
    await detector.async_fetch_data({"dazn"})
    assert sum(record.message == "Streaming checker dazn recovered" for record in caplog.records) == 1
    detector._async_check_dazn.side_effect = ValueError("new outage")
    await detector.async_fetch_data({"dazn"})
    assert len([record for record in caplog.records if record.exc_info]) == 3
    detector._async_check_dazn.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await detector.async_fetch_data({"dazn"})
    assert len([record for record in caplog.records if record.exc_info]) == 3

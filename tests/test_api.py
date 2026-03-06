"""Unit tests for API helpers."""

from __future__ import annotations

import pytest

from custom_components.clash_controller.api import ClashAPI


def test_infer_core_model_prefers_reported_name() -> None:
    """Reported core name should be normalized first."""
    assert ClashAPI._infer_core_model({"name": "mihomo"}) == "Mihomo"
    assert ClashAPI._infer_core_model({"name": "clash.meta alpha"}) == "Clash Meta"
    assert ClashAPI._infer_core_model({"name": "Clash"}) == "Clash"


def test_infer_core_model_fallbacks_from_meta_version() -> None:
    """Meta cores should split by legacy Clash.Meta and newer mihomo era."""
    assert ClashAPI._infer_core_model({"meta": True, "version": "v1.16.5"}) == "Clash Meta"
    assert ClashAPI._infer_core_model({"meta": True, "version": "v1.17.0"}) == "Mihomo"
    assert ClashAPI._infer_core_model({"meta": False, "version": "v1.0.0"}) == "Clash Compatible Core"


@pytest.mark.asyncio
async def test_detect_capabilities_probes_when_cached_capabilities_empty(monkeypatch) -> None:
    """Empty dict cache must not short-circuit capability probing."""
    api = ClashAPI("http://127.0.0.1:9090/", "token", capabilities={})

    http_calls = 0
    ws_calls = 0

    async def fake_probe_http(method, endpoint, **kwargs):  # noqa: ANN001
        nonlocal http_calls
        http_calls += 1
        return endpoint in {"proxies", "connections"}

    async def fake_probe_ws(endpoint, timeout=1.5):  # noqa: ANN001
        nonlocal ws_calls
        ws_calls += 1
        return False

    monkeypatch.setattr(api, "_probe_http_endpoint", fake_probe_http)
    monkeypatch.setattr(api, "_probe_ws_endpoint", fake_probe_ws)

    capabilities = await api.async_detect_capabilities()

    assert http_calls > 0
    assert ws_calls > 0
    assert capabilities["proxies"] is True
    assert capabilities["connections"] is True
    assert capabilities["traffic"] is False

    calls_after_first_detect = http_calls
    await api.async_detect_capabilities()
    assert http_calls == calls_after_first_detect


@pytest.mark.asyncio
async def test_detect_capabilities_accepts_ws_only_stream_endpoints(monkeypatch) -> None:
    """Websocket-only reverse proxies should still expose streaming capabilities."""
    api = ClashAPI("https://example.invalid/", "token")

    async def fake_probe_http(method, endpoint, **kwargs):  # noqa: ANN001
        return endpoint in {"proxies", "configs"}

    async def fake_probe_ws(endpoint, timeout=1.5):  # noqa: ANN001
        return endpoint in {"traffic", "memory", "connections?interval=1"}

    monkeypatch.setattr(api, "_probe_http_endpoint", fake_probe_http)
    monkeypatch.setattr(api, "_probe_ws_endpoint", fake_probe_ws)

    capabilities = await api.async_detect_capabilities(force=True)

    assert capabilities["traffic"] is True
    assert capabilities["memory"] is True
    assert capabilities["connections"] is True
    assert capabilities["ws_traffic"] is True
    assert capabilities["ws_memory"] is True
    assert capabilities["ws_connections"] is True
    assert api.available_endpoints == [("proxies", {})]

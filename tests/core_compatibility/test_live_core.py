"""One protocol contract executed for every pinned core."""

from urllib.parse import quote

import aiohttp
import pytest

from custom_components.clash_controller.clash_api import (
    APIAuthError,
    APIClientError,
    ClashAPI,
)

from .core import SECRET, RunningCore

pytestmark = [pytest.mark.system, pytest.mark.enable_socket]


async def test_core_contract(running_core: RunningCore):
    """Verify auth, declared capabilities, payloads and a real write/read cycle."""
    async with aiohttp.ClientSession() as session:
        api = ClashAPI(running_core.url, SECRET, session=session)
        bad_api = ClashAPI(running_core.url, "wrong-secret", session=session)
        with pytest.raises(APIAuthError):
            await bad_api.connected()
        assert await api.connected()
        assert (await api.get_version())["version"] != "unknown"
        capabilities = await api.async_detect_capabilities(force=True)
        for name, expected in running_core.expected_capabilities.items():
            assert capabilities[name] is expected, (
                running_core.name,
                name,
                capabilities,
            )
        result = await api.fetch_data()
        assert not result.errors, result.errors
        assert {"up", "down"} <= result["traffic"].keys()
        assert {"uploadTotal", "downloadTotal", "connections"} <= result[
            "connections"
        ].keys()
        assert isinstance(result["proxies"]["proxies"], dict)
        assert isinstance(result["configs"], dict)
        rules = (await api.async_request("GET", "rules"))["rules"]
        # sing-box serializes an empty rule set as null; the service normalizes it.
        assert isinstance(rules, list) or (
            running_core.name == "sing_box" and rules is None
        )
        for key in ("providers_proxies", "providers_rules"):
            if running_core.expected_capabilities[key]:
                providers = result[key]["providers"]
                assert isinstance(providers, dict) or (
                    running_core.name == "sing_box" and providers == []
                )
        if running_core.expected_capabilities["memory"]:
            assert "inuse" in result["memory"]

        # Force both transports separately: fallback must not hide a broken one.
        for endpoint, required_keys in (
            ("traffic", {"up", "down"}),
            ("memory", {"inuse"}),
            ("connections", {"connections"}),
        ):
            if running_core.expected_capabilities.get("ws_" + endpoint):
                payload = await api.async_ws_request(endpoint)
                assert required_keys <= payload.keys()
            if running_core.expected_capabilities.get("http_" + endpoint):
                read_line = (
                    dict(api.available_endpoints).get(endpoint, {}).get("read_line", 0)
                )
                payload = await api.async_request("GET", endpoint, read_line=read_line)
                assert required_keys <= payload.keys()

        endpoint = "proxies/" + quote("HA Compatibility Test", safe="")
        original = (await api.async_request("GET", endpoint))["now"]
        target = "SECOND" if running_core.name == "sing_box" else "REJECT"
        try:
            await api.async_request("PUT", endpoint, json_data={"name": target})
            assert (await api.async_request("GET", endpoint))["now"] == target
        finally:
            await api.async_request("PUT", endpoint, json_data={"name": original})

        original_mode = (await api.async_request("GET", "configs"))["mode"]

        async def set_mode(mode):
            try:
                await api.async_request("PATCH", "configs", json_data={"mode": mode})
            except APIClientError:
                await api.async_request("PUT", "configs", json_data={"mode": mode})

        try:
            await set_mode("global")
            assert (await api.async_request("GET", "configs"))["mode"] == "global"
        finally:
            await set_mode(original_mode)

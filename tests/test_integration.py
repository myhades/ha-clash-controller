"""HA lifecycle and user-facing behavior, independent of the core implementation."""

import asyncio
import json
import logging
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from clash_controller_api import (
    APIAuthError,
    APIClientError,
    APIConnectionError,
    APITimeoutError,
    CapabilityReport,
    FetchResult,
    VersionInfo,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.clash_controller.const import DOMAIN
from custom_components.clash_controller.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.clash_controller.streaming import (
    StreamingProxyAuthError,
    StreamingProxyConnectionError,
    StreamingProxyTimeoutError,
)

HOST = "http://controller.local:9090/"
INPUT = {
    "api_url": HOST,
    "bearer_token": "secret-token",
    "allow_unsafe": False,
    "use_ssl": False,
}
PAYLOAD = {
    "traffic": {"up": 1048576, "down": 0},
    "connections": {"uploadTotal": 1073741824, "downloadTotal": 0, "connections": []},
    "memory": {"inuse": 1048576},
    "configs": {"mode": "rule"},
    "proxies": {
        "proxies": {
            "A/B 中文": {
                "name": "A/B 中文",
                "type": "Selector",
                "now": "DIRECT",
                "all": ["DIRECT", "REJECT"],
            }
        }
    },
}


@pytest.fixture
def backend(monkeypatch):
    """Mock only the API boundary; HA setup, registries, entities and services are real."""
    instances = {}

    def factory(host, token, *args, **kwargs):
        if host not in instances:
            api = SimpleNamespace(
                capabilities={
                    **dict.fromkeys(PAYLOAD, True),
                    "cache_fakeip_flush": True,
                    "restart": True,
                    "group_delay": True,
                    "proxy_delay": True,
                },
                available_endpoints=[],
                payload=deepcopy(PAYLOAD),
                async_validate_connection=AsyncMock(return_value=None),
                async_get_version=AsyncMock(
                    return_value=VersionInfo(
                        model="Mihomo", version="test", meta="Meta Core"
                    )
                ),
                async_close=AsyncMock(),
                async_request=AsyncMock(return_value={}),
            )

            async def fetch():
                return FetchResult(deepcopy(api.payload), {})

            api.async_fetch_data = AsyncMock(side_effect=fetch)
            api.async_detect_capabilities = AsyncMock(
                return_value=CapabilityReport(dict(api.capabilities), {})
            )
            instances[host] = api
        return instances[host]

    monkeypatch.setattr(
        "custom_components.clash_controller.coordinator.ClashAPI", factory
    )
    monkeypatch.setattr(
        "custom_components.clash_controller.config_flow.ClashAPI", factory
    )
    return factory, instances


async def load_entry(hass, backend, host=HOST):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=host,
        data={**INPUT, "api_url": host},
        unique_id=host,
        options={"scan_interval": 10, "streaming_detection": False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    return entry


def entity_id(hass, entry, suffix):
    return next(
        item.entity_id
        for item in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if item.unique_id.endswith(suffix)
    )


async def poll(hass, seconds=11):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (APIAuthError("bad password"), "invalid_token"),
        (APIConnectionError("offline"), "cannot_connect"),
        (APITimeoutError("timeout"), "timed_out"),
        (APIClientError("malformed"), "cannot_connect"),
        (RuntimeError("unexpected failure"), "unknown"),
    ],
)
async def test_config_flow_errors(hass, backend, error, key, caplog):
    api = backend[0](HOST, "")
    api.async_validate_connection.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=dict(INPUT)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}
    assert not hass.config_entries.async_entries(DOMAIN)
    api.async_detect_capabilities.assert_not_awaited()
    unexpected = [
        record for record in caplog.records
        if record.message == "Unexpected error validating controller connection"
    ]
    assert len(unexpected) == (1 if key == "unknown" else 0)
    if unexpected:
        assert unexpected[0].exc_info is not None


async def test_flow_identity_reload_and_cleanup(hass, backend):
    with patch(
        "custom_components.clash_controller.streaming_coordinator.StreamingDetector"
    ) as streaming:
        streaming.return_value.async_fetch_data = AsyncMock(return_value={})
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=dict(INPUT)
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        entry = result["result"]
        assert "capabilities" not in entry.data
        assert "available_endpoints" not in entry.data
        api = backend[1][HOST]
        registry = er.async_get(hass)
        before = {
            item.unique_id: item.entity_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        assert (
            "http___controller_local_9090__device_traffic_sensor_upload_speed" in before
        )
        device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[
            0
        ]
        assert device.identifiers == {(DOMAIN, "http___controller_local_9090__device")}
        assert device.configuration_url == HOST
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=dict(INPUT)
        )
        assert duplicate["type"] is FlowResultType.ABORT
        assert duplicate["reason"] == "already_configured"
        streaming.return_value.async_fetch_data.assert_not_awaited()
        services = dict(hass.services.async_services_for_domain(DOMAIN))
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert all(
            hass.services.async_services_for_domain(DOMAIN)[key] is value
            for key, value in services.items()
        )
        assert {
            item.unique_id: item.entity_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        } == before
        api.async_detect_capabilities.assert_awaited_with(force=True)
        api.async_fetch_data.reset_mock()
        api.async_validate_connection.reset_mock()
        api.async_get_version.reset_mock()
        api.async_detect_capabilities.reset_mock()
        await poll(hass, 61)
        api.async_fetch_data.assert_awaited_once()
        api.async_validate_connection.assert_not_awaited()
        api.async_get_version.assert_not_awaited()
        api.async_detect_capabilities.assert_not_awaited()
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        api.async_fetch_data.reset_mock()
        await poll(hass, 180)
        api.async_fetch_data.assert_not_awaited()
        assert hass.services.async_services_for_domain(DOMAIN)


async def test_entry_migration_removes_runtime_probe_data(hass, backend):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="controller",
        data={
            **INPUT,
            "capabilities": {"traffic": True},
            "available_endpoints": [["traffic", {"read_line": 1}]],
        },
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.minor_version == 2
    assert "capabilities" not in entry.data
    assert "available_endpoints" not in entry.data
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("scope", ["partial", "providers", "all"])
async def test_polling_outage_and_recovery(hass, backend, scope, caplog):
    caplog.set_level(logging.INFO, logger="custom_components.clash_controller.coordinator")
    api = backend[0](HOST, "")
    api.capabilities.update(providers_proxies=True, providers_rules=True)
    api.payload.update(
        providers_proxies={"providers": {"proxy": {}}},
        providers_rules={"providers": {"rule": {}}},
    )
    entry = await load_entry(hass, backend)
    upload = entity_id(hass, entry, "_upload_speed")
    group = entity_id(hass, entry, "_a/b_中文")
    proxy_count = entity_id(hass, entry, "_proxy_provider_count")
    rule_count = entity_id(hass, entry, "_rule_provider_count")
    original = deepcopy(api.payload)

    async def fetch():
        return FetchResult(
            deepcopy(api.payload),
            {key: APIConnectionError("offline") for key in original if key not in api.payload},
        )

    api.async_fetch_data.side_effect = fetch
    missing_endpoint = "providers_proxies" if scope == "providers" else "proxies"
    api.payload = (
        {}
        if scope == "all"
        else {key: value for key, value in original.items() if key != missing_endpoint}
    )
    await poll(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert (hass.states.get(group).state == STATE_UNAVAILABLE) is (scope != "providers")
    assert (hass.states.get(upload).state == STATE_UNAVAILABLE) is (scope == "all")
    assert hass.states.get(proxy_count).state == (
        STATE_UNAVAILABLE if scope in {"providers", "all"} else "1"
    )
    assert hass.states.get(rule_count).state == (STATE_UNAVAILABLE if scope == "all" else "1")
    await poll(hass, 22)
    endpoint_logs = [record.message for record in caplog.records if record.message.startswith("Endpoint ")]
    assert len(endpoint_logs) == (0 if scope == "all" else 1)
    if endpoint_logs:
        assert f"Endpoint {missing_endpoint} unavailable" in endpoint_logs[0]
        assert "APIConnectionError" in endpoint_logs[0]
    api.payload = original
    await poll(hass, 33)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(group).state != STATE_UNAVAILABLE
    assert hass.states.get(upload).state != STATE_UNAVAILABLE
    assert hass.states.get(proxy_count).state == "1"
    assert hass.states.get(rule_count).state == "1"
    endpoint_logs = [record.message for record in caplog.records if record.message.startswith("Endpoint ")]
    assert len(endpoint_logs) == (0 if scope == "all" else 2)
    if endpoint_logs:
        assert f"Endpoint {missing_endpoint} recovered" in endpoint_logs[-1]


async def test_offline_start_retries_without_probing(hass, backend):
    api = backend[0](HOST, "")
    api.async_validate_connection.side_effect = APIConnectionError("offline")
    entry = MockConfigEntry(domain=DOMAIN, title="controller", data=dict(INPUT))
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    api.async_detect_capabilities.assert_not_awaited()
    api.async_fetch_data.assert_not_awaited()
    api.async_validate_connection.side_effect = None
    await poll(hass, 120)
    assert entry.state is ConfigEntryState.LOADED


async def test_entities_added_after_first_refresh(hass, backend):
    api = backend[0](HOST, "")
    api.capabilities.update(providers_proxies=True, provider_healthcheck=True)
    api.payload.pop("memory")
    api.payload.pop("proxies")
    api.payload["providers_proxies"] = {"providers": {}}
    entry = await load_entry(hass, backend)
    registry = er.async_get(hass)

    def registered():
        return {
            item.unique_id: item.entity_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        }

    before = registered()
    restored = deepcopy(PAYLOAD)
    restored["proxies"]["proxies"]["Auto"] = {
        "name": "Auto", "type": "URLTest", "now": "DIRECT", "all": ["DIRECT"]
    }
    restored["providers_proxies"] = {"providers": {"New provider": {}}}
    api.payload = restored
    await poll(hass)
    after = registered()
    assert before.items() <= after.items()
    assert len(after) == len(before) + 4
    memory = entity_id(hass, entry, "_memory_used")
    group = entity_id(hass, entry, "_a/b_中文")
    automatic = entity_id(hass, entry, "_auto")
    button = entity_id(hass, entry, "_provider_healthcheck_new_provider")
    assert hass.states.get(memory).state != STATE_UNAVAILABLE
    assert hass.states.get(group).state == "DIRECT"
    assert hass.states.get(automatic).state == "DIRECT"
    assert registry.async_get(button).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    api.payload = {"traffic": PAYLOAD["traffic"]}
    await poll(hass, 22)
    assert hass.states.get(memory).state == STATE_UNAVAILABLE
    assert hass.states.get(group).state == STATE_UNAVAILABLE
    api.payload = restored
    await poll(hass, 33)
    assert registered() == after
    assert hass.states.get(memory).state != STATE_UNAVAILABLE
    assert hass.states.get(group).state == "DIRECT"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    api.async_fetch_data.reset_mock()
    await poll(hass, 120)
    api.async_fetch_data.assert_not_awaited()


async def test_stored_auth_failure_starts_reauthentication(hass, backend):
    api = backend[0](HOST, "")
    api.async_validate_connection.side_effect = APIAuthError("invalid")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="controller",
        data=dict(INPUT),
        unique_id=HOST,
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"

    api.async_validate_connection.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"bearer_token": "replacement-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["bearer_token"] == "replacement-token"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_polling_auth_failure_starts_reauthentication(hass, backend):
    entry = await load_entry(hass, backend)
    api = backend[1][HOST]
    api.async_fetch_data.side_effect = None
    api.async_fetch_data.return_value = FetchResult(
        {}, {"traffic": APIAuthError("invalid")}
    )

    await poll(hass)

    assert entry.state is ConfigEntryState.LOADED
    upload = hass.states.get(entity_id(hass, entry, "_upload_speed"))
    assert upload.state == STATE_UNAVAILABLE
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_numeric_entities_and_missing_values(hass, backend):
    entry = await load_entry(hass, backend)
    api = backend[1][HOST]
    for suffix, value, unit, state_class in [
        ("_upload_speed", "1.048576", "MB/s", "measurement"),
        ("_download_speed", "0", "MB/s", "measurement"),
        ("_upload_traffic", "1.073741824", "GB", "total_increasing"),
        ("_memory_used", "1.048576", "MB", "measurement"),
    ]:
        state = hass.states.get(entity_id(hass, entry, suffix))
        assert float(state.state) == float(value)
        assert state.attributes["unit_of_measurement"] == unit
        assert state.attributes["state_class"] == state_class
    upload = entity_id(hass, entry, "_upload_speed")
    for offset, value in enumerate([None, True, "invalid", 0], 1):
        api.payload["traffic"]["up"] = value
        await poll(hass, 11 * offset)
        assert (hass.states.get(upload).state == STATE_UNAVAILABLE) is (value != 0)


@pytest.mark.parametrize("finish_check", [True, False])
async def test_streaming_first_refresh_does_not_block_setup(hass, backend, finish_check):
    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = asyncio.Event()

    async def fetch(services):
        assert services == {"netflix"}
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {"netflix": {"state": "available"}}

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=dict(INPUT),
        options={"streaming_detection": True, "streaming_proxy": "proxy.local:7890"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.clash_controller.streaming_coordinator."
        "StreamingDetector.async_fetch_data",
        side_effect=fetch,
    ):
        assert await asyncio.wait_for(hass.config_entries.async_setup(entry.entry_id), 2)
        await asyncio.wait_for(hass.async_block_till_done(), 2)
        await asyncio.wait_for(started.wait(), 1)
        assert entry.state is ConfigEntryState.LOADED
        netflix = entity_id(hass, entry, "_streaming_detection_netflix")
        assert hass.states.get(netflix).state == "unknown"
        assert (
            hass.states.get(entity_id(hass, entry, "_upload_speed")).state
            != STATE_UNAVAILABLE
        )
        if finish_check:
            release.set()
            await hass.async_block_till_done(wait_background_tasks=True)
            assert hass.states.get(netflix).state == "available"
            assert not cancelled.is_set()
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert cancelled.is_set() is (not finish_check)


async def test_options_and_streaming_isolation(hass, backend):
    entry = await load_entry(hass, backend)
    options = {
        "scan_interval": 20,
        "concurrent_connections": 3,
        "streaming_detection": True,
        "streaming_proxy": "http://user%40name:p%3A%40ss@proxy.local:7890",
    }
    with (
        patch(
            "custom_components.clash_controller.config_flow."
            "StreamingDetector.async_validate_proxy",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.clash_controller.streaming_coordinator.StreamingDetector"
        ) as detector,
    ):
        detector.return_value.async_fetch_data = AsyncMock(
            return_value={
                "netflix": {
                    "state": "available",
                    "status_code": 200,
                    "latency": 0.1,
                }
            }
        )
        result = await hass.config_entries.options.async_init(
            entry.entry_id, data=options
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert entry.data["bearer_token"] == INPUT["bearer_token"]
        assert entry.runtime_data.coordinator.update_interval == timedelta(seconds=20)
        assert entry.runtime_data.coordinator.concurrent_connections == 3
        streaming_coordinator = entry.runtime_data.streaming_coordinator
        assert streaming_coordinator is not None
        assert streaming_coordinator.update_interval == timedelta(seconds=20)
        proxy = detector.call_args.args[1]
        assert str(proxy.url) == "http://proxy.local:7890"
        assert proxy.headers == {
            "Proxy-Authorization": aiohttp.encode_basic_auth("user@name", "p:@ss")
        }
        detector.return_value.async_fetch_data.assert_awaited_with({"netflix"})
        registry = er.async_get(hass)
        streaming_entries = [
            item
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
            if "_streaming_detection_" in item.unique_id
        ]
        assert len(streaming_entries) == 8
        assert (
            next(
                item
                for item in streaming_entries
                if item.unique_id.endswith("_netflix")
            ).disabled_by
            is None
        )
        assert all(
            item.disabled_by is not None
            for item in streaming_entries
            if not item.unique_id.endswith("_netflix")
        )

        devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        clash_device = next(
            item
            for item in devices
            if (DOMAIN, "http___controller_local_9090__device") in item.identifiers
        )
        streaming_device = next(
            item
            for item in devices
            if (DOMAIN, "http___controller_local_9090__device_streaming")
            in item.identifiers
        )
        assert streaming_device.via_device_id == clash_device.id
        assert all(item.device_id == streaming_device.id for item in streaming_entries)
        netflix_entity_id = entity_id(hass, entry, "_streaming_detection_netflix")
        assert hass.states.get(netflix_entity_id).state == "available"

        prime_video = next(
            item
            for item in streaming_entries
            if item.unique_id.endswith("_prime_video")
        )
        registry.async_update_entity(prime_video.entity_id, disabled_by=None)
        detector.return_value.async_fetch_data.reset_mock()
        api = backend[1][HOST]
        api.async_fetch_data.reset_mock()
        await streaming_coordinator.async_refresh()
        detector.return_value.async_fetch_data.assert_awaited_with(
            {"netflix", "prime_video"}
        )
        api.async_fetch_data.assert_not_awaited()

        detector.return_value.async_fetch_data.reset_mock()
        await entry.runtime_data.coordinator.async_refresh()
        api.async_fetch_data.assert_awaited_once()
        detector.return_value.async_fetch_data.assert_not_awaited()
        assert (
            hass.states.get(entity_id(hass, entry, "_upload_speed")).state
            != STATE_UNAVAILABLE
        )


@pytest.mark.parametrize(
    ("proxy_address", "side_effect", "error_key"),
    [
        ("", None, "invalid_proxy"),
        ("proxy.local", None, "invalid_proxy"),
        (
            "proxy.local:7890",
            StreamingProxyConnectionError(),
            "cannot_connect_proxy",
        ),
        (
            "proxy.local:7890",
            StreamingProxyAuthError(),
            "invalid_proxy_auth",
        ),
        (
            "proxy.local:7890",
            StreamingProxyTimeoutError(),
            "proxy_timed_out",
        ),
    ],
)
async def test_streaming_proxy_options_errors(
    hass, backend, proxy_address, side_effect, error_key
):
    entry = await load_entry(hass, backend)
    options = {
        "scan_interval": 20,
        "concurrent_connections": 3,
        "streaming_detection": True,
        "streaming_proxy": proxy_address,
    }

    with patch(
        "custom_components.clash_controller.config_flow."
        "StreamingDetector.async_validate_proxy",
        new=AsyncMock(side_effect=side_effect),
    ):
        result = await hass.config_entries.options.async_init(
            entry.entry_id, data=options
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error_key}
    assert entry.options["streaming_detection"] is False


async def test_disabled_streaming_does_not_validate_proxy(hass, backend):
    entry = await load_entry(hass, backend)
    options = {
        "scan_interval": 20,
        "concurrent_connections": 3,
        "streaming_detection": False,
        "streaming_proxy": "not-a-proxy",
    }

    with patch(
        "custom_components.clash_controller.config_flow."
        "StreamingDetector.async_validate_proxy",
        new=AsyncMock(),
    ) as validate:
        result = await hass.config_entries.options.async_init(
            entry.entry_id, data=options
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    validate.assert_not_awaited()


async def test_diagnostics_redaction(hass, backend):
    entry = await load_entry(hass, backend)
    proxy_address = "proxy-user:proxy-secret@proxy.local:7890"
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, "streaming_proxy": proxy_address},
    )
    output = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
    for secret in [
        INPUT["bearer_token"],
        HOST,
        "controller.local",
        "A/B 中文",
        proxy_address,
        "proxy-secret",
    ]:
        assert secret not in output


@pytest.mark.parametrize(
    ("service", "data", "method", "endpoint", "reply", "expected", "error_key"),
    [
        ("reboot_core_service", {}, "POST", "restart", {}, None, "reboot_failed"),
        (
            "dns_query_service",
            {"domain_name": "example.com"},
            "GET",
            "dns/query",
            {"Answer": []},
            {"Answer": []},
            "dns_query_failed",
        ),
        (
            "get_rule_service",
            {"rule_payload": "example"},
            "GET",
            "rules",
            {"rules": [{"payload": "example.com"}, {"payload": "other"}]},
            {"rules": [{"payload": "example.com"}]},
            "rules_failed",
        ),
        (
            "get_latency_service",
            {"node": "A/B 中文"},
            "GET",
            "proxies/A%2FB%20%E4%B8%AD%E6%96%87/delay",
            {"delay": 3},
            {"latency": {"A/B 中文": 3}},
            "latency_failed",
        ),
        (
            "get_latency_service",
            {"group": "A/B 中文"},
            "GET",
            "group/A%2FB%20%E4%B8%AD%E6%96%87/delay",
            {"b": 5, "a": 2},
            {"fastest_node": "a", "latency": [("a", 2), ("b", 5)]},
            "latency_failed",
        ),
        (
            "api_call_service",
            {
                "api_endpoint": "configs",
                "api_method": "PATCH",
                "api_data": '{"mode":"global"}',
            },
            "PATCH",
            "configs",
            {"ok": True},
            {"response": {"ok": True}},
            "api_call_failed",
        ),
    ],
)
async def test_service_contracts(
    hass, backend, service, data, method, endpoint, reply, expected, error_key
):
    entry = await load_entry(hass, backend)
    api = backend[1][HOST]
    device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]
    api.async_request.return_value = reply

    async def invoke():
        return await hass.services.async_call(
            DOMAIN,
            service,
            {"device_id": device.id, **data},
            blocking=True,
            return_response=service != "reboot_core_service",
        )

    assert await invoke() == expected
    call = api.async_request.await_args
    assert (call.args[0] if call.args else call.kwargs["method"]) == method
    assert (call.args[1] if call.args else call.kwargs["endpoint"]) == endpoint
    if service == "get_latency_service":
        assert call.kwargs["params"] == {
            "url": "https://www.gstatic.com/generate_204",
            "timeout": 5000,
        }
    if service == "dns_query_service":
        assert call.kwargs["params"] == {"name": "example.com", "type": "A"}
    if service == "api_call_service":
        assert call.kwargs["json_data"] == {"mode": "global"}
    api.async_request.side_effect = APIConnectionError("offline")
    with pytest.raises(HomeAssistantError) as error:
        await invoke()
    assert error.value.translation_key == error_key
    assert entry.state is ConfigEntryState.LOADED


async def test_connections_and_multiple_entry_routing(hass, backend):
    first = await load_entry(hass, backend)
    second = await load_entry(hass, backend, "http://second.local/")
    api = backend[1]["http://second.local/"]
    device = dr.async_entries_for_config_entry(dr.async_get(hass), second.entry_id)[0]
    records = [
        {"id": "1", "metadata": {"host": "Example.COM"}},
        {"id": "2", "metadata": {"host": "other.com"}},
    ]
    api.async_request.return_value = {"connections": records}
    result = await hass.services.async_call(
        DOMAIN,
        "filter_connection_service",
        {"device_id": device.id, "host": "example", "close_connection": True},
        blocking=True,
        return_response=True,
    )
    assert result == {
        "connection_number": 1,
        "connection_closed": True,
        "connections": records[:1],
    }
    api.async_request.assert_any_await("DELETE", "connections/1")
    backend[1][HOST].async_request.assert_not_awaited()
    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()
    assert second.state is ConfigEntryState.LOADED
    await hass.services.async_call(
        DOMAIN,
        "filter_connection_service",
        {"device_id": device.id, "close_connection": True},
        blocking=True,
        return_response=True,
    )
    api.async_request.assert_any_await("DELETE", "connections")


@pytest.mark.parametrize(
    ("service", "data", "key"),
    [
        ("get_latency_service", {}, "invalid_latency_target"),
        ("get_latency_service", {"node": "a", "group": "b"}, "invalid_latency_target"),
        (
            "api_call_service",
            {"api_method": "GET", "api_endpoint": "configs", "api_data": "[]"},
            "invalid_json",
        ),
        ("reboot_core_service", {}, "unsupported_action"),
        ("get_rule_service", {"device_id": "missing"}, "invalid_device"),
        ("get_rule_service", {"device_id": "foreign"}, "invalid_device"),
        ("get_rule_service", {"device_id": "unloaded"}, "invalid_device"),
    ],
)
async def test_service_validation(hass, backend, service, data, key):
    entry = await load_entry(hass, backend)
    api = backend[1][HOST]
    api.capabilities["restart"] = False
    device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]
    data = dict(data)
    if data.get("device_id") == "foreign":
        foreign_entry = MockConfigEntry(domain="other", state=ConfigEntryState.LOADED)
        foreign_entry.add_to_hass(hass)
        foreign_entry.runtime_data = entry.runtime_data
        foreign_device = dr.async_get(hass).async_get_or_create(
            config_entry_id=foreign_entry.entry_id,
            identifiers={("other", "device")},
        )
        data["device_id"] = foreign_device.id
    elif data.get("device_id") == "unloaded":
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        data["device_id"] = device.id
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            service,
            {"device_id": device.id, **data},
            blocking=True,
            return_response=service != "reboot_core_service",
        )
    assert error.value.translation_key == key
    api.async_request.assert_not_awaited()


async def test_select_and_button_writes(hass, backend):
    entry = await load_entry(hass, backend)
    api = backend[1][HOST]
    selector = entity_id(hass, entry, "_a/b_中文")
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": selector, "option": "REJECT"},
        blocking=True,
    )
    api.async_request.assert_awaited_once_with(
        "PUT", "proxies/A%2FB%20%E4%B8%AD%E6%96%87", json_data={"name": "REJECT"}
    )
    assert hass.states.get(selector).state == "REJECT"
    api.async_request.reset_mock()
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id(hass, entry, "_core_mode"), "option": "global"},
        blocking=True,
    )
    api.async_request.assert_awaited_once_with(
        "PATCH", "configs", json_data={"mode": "global"}
    )
    assert hass.states.get(entity_id(hass, entry, "_core_mode")).state == "global"
    api.async_request.reset_mock()
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(hass, entry, "_flush_fakeip_cache")},
        blocking=True,
    )
    api.async_request.assert_awaited_once_with("POST", "cache/fakeip/flush")


@pytest.mark.parametrize(
    "api_error",
    [APIConnectionError, APIAuthError, APITimeoutError, APIClientError],
)
async def test_entity_action_errors_are_translated(hass, backend, api_error):
    entry = await load_entry(hass, backend)
    api = backend[1][HOST]
    api.async_request.side_effect = api_error("request failed")

    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id(hass, entry, "_a/b_中文"), "option": "REJECT"},
            blocking=True,
        )
    assert error.value.translation_key == "proxy_group_selection_failed"

    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id(hass, entry, "_flush_fakeip_cache")},
            blocking=True,
        )
    assert error.value.translation_key == "button_action_failed"

    api.async_request.reset_mock()
    mode = entity_id(hass, entry, "_core_mode")
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": mode, "option": "global"},
            blocking=True,
        )
    assert error.value.translation_key == "mode_selection_failed"
    api.async_request.assert_awaited_once_with(
        "PATCH", "configs", json_data={"mode": "global"}
    )
    assert hass.states.get(mode).state == "rule"

"""System tests loading the integration in a real Home Assistant instance."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket

from homeassistant import config_entries
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN, SERVICE_SELECT_OPTION
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.clash_controller.const import (
    API_CALL_SERVICE_NAME,
    CONF_ALLOW_UNSAFE,
    CONF_API_URL,
    CONF_BEAR_TOKEN,
    CONF_CONCURRENT_CONNECTIONS,
    CONF_STREAMING_DETECTION,
    CONF_USE_SSL,
    DOMAIN,
    DNS_QUERY_SERVICE_NAME,
    FILTER_CONNECTION_SERVICE_NAME,
    GET_LATENCY_SERVICE_NAME,
    GET_RULE_SERVICE_NAME,
    REBOOT_CORE_SERVICE_NAME,
)

from .fault_proxy import ControllerFaultProxy
from .test_live_core import ClashAPI, RunningCore, SECRET, create_running_core

pytestmark = [pytest.mark.system, pytest.mark.enable_socket]


def _require_reference_core() -> None:
    """Run core-independent fault scenarios only once in a matrix."""
    if os.environ.get("CLASH_CORE_NAME") != "mihomo":
        pytest.skip("fault scenario runs once with the reference core")


def _flow_input(
    core: RunningCore, token: str = SECRET, api_url: str | None = None
) -> dict[str, object]:
    """Build user input for the integration config flow."""
    return {
        CONF_API_URL: api_url or core.url,
        CONF_BEAR_TOKEN: token,
        CONF_USE_SSL: False,
        CONF_ALLOW_UNSAFE: False,
    }


async def _create_loaded_entry(
    hass: HomeAssistant, core: RunningCore, api_url: str | None = None
) -> config_entries.ConfigEntry:
    """Create the entry through its config flow and wait for setup."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=_flow_input(core, api_url=api_url),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _unload_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Unload an entry and drain cleanup callbacks before the test ends."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_config_flow_rejects_invalid_token(
    hass: HomeAssistant, running_core: RunningCore
) -> None:
    """A real core 401 must be surfaced as invalid credentials by the flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=_flow_input(running_core, "wrong-secret"),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_token"}
    assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.asyncio
async def test_config_flow_reports_connection_refused(hass: HomeAssistant) -> None:
    """A closed local controller port must be reported as cannot-connect."""
    _require_reference_core()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={
            CONF_API_URL: f"http://127.0.0.1:{port}/",
            CONF_BEAR_TOKEN: SECRET,
            CONF_USE_SSL: False,
            CONF_ALLOW_UNSAFE: False,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
@pytest.mark.release
async def test_config_flow_reports_timeout(
    hass: HomeAssistant, hanging_api_url: str
) -> None:
    """A controller which accepts but never responds must report a timeout."""
    _require_reference_core()
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={
            CONF_API_URL: hanging_api_url,
            CONF_BEAR_TOKEN: SECRET,
            CONF_USE_SSL: False,
            CONF_ALLOW_UNSAFE: False,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "timed_out"}


@pytest.mark.asyncio
@pytest.mark.release
async def test_config_flow_rejects_malformed_version_response(
    hass: HomeAssistant,
    running_core: RunningCore,
    fault_proxy: ControllerFaultProxy,
) -> None:
    """A non-JSON version response must not create a config entry."""
    _require_reference_core()
    fault_proxy.set_malformed("version")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=_flow_input(running_core, api_url=fault_proxy.url),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_config_flow_setup_entities_and_services(
    hass: HomeAssistant, running_core: RunningCore
) -> None:
    """Exercise config flow, setup, entities and read services end to end."""
    entry = await _create_loaded_entry(hass, running_core)
    try:
        device_registry = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        assert len(devices) == 1
        device_id = next(iter(devices)).id

        entity_registry = er.async_get(hass)
        integration_entities = er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        )
        assert integration_entities
        assert all(
            item.disabled_by is not None or hass.states.get(item.entity_id)
            for item in integration_entities
        )
        disabled_entities = [
            item for item in integration_entities if item.disabled_by is not None
        ]
        assert disabled_entities
        assert all(
            hass.states.get(item.entity_id) is None for item in disabled_entities
        )

        rules = await hass.services.async_call(
            DOMAIN,
            GET_RULE_SERVICE_NAME,
            {"device_id": device_id},
            blocking=True,
            return_response=True,
        )
        assert rules and rules["rules"]

        response = await hass.services.async_call(
            DOMAIN,
            API_CALL_SERVICE_NAME,
            {
                "device_id": device_id,
                "api_endpoint": "configs",
                "api_method": "GET",
            },
            blocking=True,
            return_response=True,
        )
        assert response and isinstance(response["response"], dict)
    finally:
        await _unload_entry(hass, entry)


@pytest.mark.asyncio
async def test_duplicate_flow_aborts_without_second_entry(
    hass: HomeAssistant, running_core: RunningCore
) -> None:
    """The same controller URL must not create duplicate config entries."""
    entry = await _create_loaded_entry(hass, running_core)
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=_flow_input(running_core),
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    finally:
        await _unload_entry(hass, entry)


@pytest.mark.asyncio
@pytest.mark.release
async def test_reload_keeps_entity_ids_and_does_not_duplicate_services(
    hass: HomeAssistant, running_core: RunningCore
) -> None:
    """Reload must preserve registry identity and single service registration."""
    entry = await _create_loaded_entry(hass, running_core)
    entity_registry = er.async_get(hass)
    before = {
        item.entity_id
        for item in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }
    services_before = set(hass.services.async_services_for_domain(DOMAIN))
    try:
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        after = {
            item.entity_id
            for item in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        }
        assert after == before
        assert set(hass.services.async_services_for_domain(DOMAIN)) == services_before
    finally:
        await _unload_entry(hass, entry)
    assert not hass.services.async_services_for_domain(DOMAIN)


@pytest.mark.asyncio
async def test_selector_write_round_trip_through_home_assistant(
    hass: HomeAssistant, running_core: RunningCore
) -> None:
    """A HA select service call must mutate and read back the real core."""
    entry = await _create_loaded_entry(hass, running_core)
    try:
        selector = next(
            state
            for state in hass.states.async_all(SELECT_DOMAIN)
            if state.entity_id.endswith("_ha_compatibility_test")
        )
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: selector.entity_id, "option": "REJECT"},
            blocking=True,
        )
        assert hass.states.get(selector.entity_id).state == "REJECT"

        api = ClashAPI(running_core.url, SECRET)
        try:
            group = await api.async_request(
                "GET", "proxies/HA%20Compatibility%20Test", suppress_errors=False
            )
            assert group["now"] == "REJECT"
        finally:
            await api.async_request(
                "PUT",
                "proxies/HA%20Compatibility%20Test",
                json_data={"name": "DIRECT"},
                suppress_errors=True,
            )
            await api.close_session()
    finally:
        await _unload_entry(hass, entry)


@pytest.mark.asyncio
async def test_services_route_errors_and_live_responses(
    hass: HomeAssistant, running_core: RunningCore, aiohttp_server
) -> None:
    """Exercise service routing, validation and real latency/filter responses."""
    from aiohttp import web

    async def _generate_204(_request: web.Request) -> web.Response:
        return web.Response(status=204)

    app = web.Application()
    app.router.add_get("/generate_204", _generate_204)
    server = await aiohttp_server(app)
    entry = await _create_loaded_entry(hass, running_core)
    try:
        device = next(
            iter(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id))
        )

        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                DOMAIN,
                GET_RULE_SERVICE_NAME,
                {"device_id": "not-a-device"},
                blocking=True,
                return_response=True,
            )

        connections = await hass.services.async_call(
            DOMAIN,
            FILTER_CONNECTION_SERVICE_NAME,
            {"device_id": device.id},
            blocking=True,
            return_response=True,
        )
        assert connections == {
            "connection_number": 0,
            "connection_closed": False,
            "connections": [],
        }

        latency = await hass.services.async_call(
            DOMAIN,
            GET_LATENCY_SERVICE_NAME,
            {
                "device_id": device.id,
                "node": "DIRECT",
                "url": str(server.make_url("/generate_204")),
                "timeout": 3000,
            },
            blocking=True,
            return_response=True,
        )
        assert isinstance(latency["latency"]["DIRECT"], int)
        assert latency["latency"]["DIRECT"] >= 0

        coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
        if coordinator.api.capabilities.get("dns_query"):
            dns = await hass.services.async_call(
                DOMAIN,
                DNS_QUERY_SERVICE_NAME,
                {"device_id": device.id, "domain_name": "example.com", "record_type": "A"},
                blocking=True,
                return_response=True,
            )
            assert isinstance(dns, dict)
        else:
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    DOMAIN,
                    DNS_QUERY_SERVICE_NAME,
                    {
                        "device_id": device.id,
                        "domain_name": "example.com",
                        "record_type": "A",
                    },
                    blocking=True,
                    return_response=True,
                )

        for button in hass.states.async_all(BUTTON_DOMAIN):
            if button.entity_id.endswith(("_flush_fakeip_cache", "_flush_dns_cache")):
                try:
                    await hass.services.async_call(
                        BUTTON_DOMAIN,
                        SERVICE_PRESS,
                        {ATTR_ENTITY_ID: button.entity_id},
                        blocking=True,
                    )
                except HomeAssistantError:
                    # Some cores expose a cache route but reject it unless the
                    # corresponding DNS mode is active. The entity must surface
                    # that as a service error without destabilising the entry.
                    assert entry.state is ConfigEntryState.LOADED

        if coordinator.api.capabilities.get("restart"):
            await hass.services.async_call(
                DOMAIN,
                REBOOT_CORE_SERVICE_NAME,
                {"device_id": device.id},
                blocking=True,
            )
        else:
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    DOMAIN,
                    REBOOT_CORE_SERVICE_NAME,
                    {"device_id": device.id},
                    blocking=True,
                )
        assert running_core.process.poll() is None
    finally:
        await _unload_entry(hass, entry)


@pytest.mark.asyncio
@pytest.mark.release
async def test_endpoint_failure_only_marks_dependent_entities_unavailable(
    hass: HomeAssistant,
    running_core: RunningCore,
    fault_proxy: ControllerFaultProxy,
) -> None:
    """One broken endpoint must not fail the entry or unrelated entities."""
    entry = await _create_loaded_entry(hass, running_core, fault_proxy.url)
    coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    group_entity_id = next(
        item.entity_id
        for item in entities
        if item.entity_id.endswith("_ha_compatibility_test")
    )
    traffic_entity_id = next(
        item.entity_id for item in entities if item.entity_id.endswith("_upload_speed")
    )
    try:
        fault_proxy.set_status("proxies")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert hass.states.get(group_entity_id).state == STATE_UNAVAILABLE
        assert hass.states.get(traffic_entity_id).state != STATE_UNAVAILABLE

        fault_proxy.clear("proxies")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(group_entity_id).state != STATE_UNAVAILABLE
        assert hass.states.get(traffic_entity_id).state != STATE_UNAVAILABLE
    finally:
        await _unload_entry(hass, entry)


@pytest.mark.asyncio
@pytest.mark.release
async def test_services_route_to_the_targeted_config_entry(
    hass: HomeAssistant, running_core: RunningCore, tmp_path: Path
) -> None:
    """Device-targeted services must select the correct loaded coordinator."""
    _require_reference_core()
    second_core = create_running_core(
        running_core.binary, running_core.name, tmp_path / "second-core"
    )
    first_entry: config_entries.ConfigEntry | None = None
    second_entry: config_entries.ConfigEntry | None = None
    second_api = ClashAPI(second_core.url, SECRET)
    endpoint = "proxies/HA%20Compatibility%20Test"
    try:
        first_entry = await _create_loaded_entry(hass, running_core)
        second_entry = await _create_loaded_entry(hass, second_core)
        await second_api.async_request(
            "PUT",
            endpoint,
            json_data={"name": "REJECT"},
            suppress_errors=False,
        )

        device_registry = dr.async_get(hass)
        first_device = next(
            iter(
                dr.async_entries_for_config_entry(
                    device_registry, first_entry.entry_id
                )
            )
        )
        second_device = next(
            iter(
                dr.async_entries_for_config_entry(
                    device_registry, second_entry.entry_id
                )
            )
        )

        async def _selected_node(device_id: str) -> str:
            response = await hass.services.async_call(
                DOMAIN,
                API_CALL_SERVICE_NAME,
                {
                    "device_id": device_id,
                    "api_endpoint": endpoint,
                    "api_method": "GET",
                },
                blocking=True,
                return_response=True,
            )
            return response["response"]["now"]

        assert await _selected_node(first_device.id) == "DIRECT"
        assert await _selected_node(second_device.id) == "REJECT"
    finally:
        await second_api.async_request(
            "PUT",
            endpoint,
            json_data={"name": "DIRECT"},
            suppress_errors=True,
        )
        await second_api.close_session()
        for entry in (second_entry, first_entry):
            if entry is not None and entry.state is ConfigEntryState.LOADED:
                await _unload_entry(hass, entry)
        second_core.stop()


@pytest.mark.asyncio
@pytest.mark.release
async def test_loaded_entry_survives_outage_and_recovers_entities(
    hass: HomeAssistant, running_core: RunningCore
) -> None:
    """A transient outage must not fail the entry and entities must recover."""
    entry = await _create_loaded_entry(hass, running_core)
    coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    entity_registry = er.async_get(hass)
    entity_ids = [
        item.entity_id
        for item in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if item.disabled_by is None
    ]
    assert entity_ids

    try:
        running_core.stop()
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert all(
            hass.states.get(entity_id).state == STATE_UNAVAILABLE
            for entity_id in entity_ids
        )

        running_core.start()
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert all(
            hass.states.get(entity_id).state != STATE_UNAVAILABLE
            for entity_id in entity_ids
        )
    finally:
        if running_core.process.poll() is not None:
            running_core.start()
        await _unload_entry(hass, entry)


@pytest.mark.asyncio
@pytest.mark.release
async def test_offline_first_setup_retries_then_loads(
    hass: HomeAssistant, running_core: RunningCore
) -> None:
    """An unavailable core at startup must retry instead of permanently failing."""
    running_core.stop()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=running_core.url,
        data={
            **_flow_input(running_core),
            "available_endpoints": [],
            "capabilities": {},
        },
        options={
            CONF_CONCURRENT_CONNECTIONS: 5,
            CONF_STREAMING_DETECTION: False,
        },
        unique_id=running_core.url.replace("://", "___").replace("/", "_"),
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY

    try:
        running_core.start()
        deadline = asyncio.get_running_loop().time() + 20
        while (
            entry.state is not ConfigEntryState.LOADED
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(0.1)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
    finally:
        if entry.state is ConfigEntryState.LOADED:
            await _unload_entry(hass, entry)

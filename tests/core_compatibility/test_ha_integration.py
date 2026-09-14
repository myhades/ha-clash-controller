"""Small real-core HA smoke; generic HA behavior lives in test_integration.py."""

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.clash_controller.const import DOMAIN

from .core import SECRET

pytestmark = [pytest.mark.system, pytest.mark.enable_socket]


async def test_core_loads_in_home_assistant(hass, running_core):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={
            "api_url": running_core.url,
            "bearer_token": SECRET,
            "use_ssl": False,
            "allow_unsafe": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    try:
        assert entry.state is ConfigEntryState.LOADED
        entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        enabled = [item for item in entities if item.disabled_by is None]
        assert enabled
        assert all(
            hass.states.get(item.entity_id).state != STATE_UNAVAILABLE
            for item in enabled
        )
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.release
async def test_real_process_outage_recovers_on_poll(hass, running_core):
    """One real process restart; no manual coordinator refresh."""
    if running_core.name != "mihomo":
        pytest.skip("process recovery is core independent")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={
            "api_url": running_core.url,
            "bearer_token": SECRET,
            "use_ssl": False,
            "allow_unsafe": False,
        },
    )
    await hass.async_block_till_done()
    entry = result["result"]
    coordinator = entry.runtime_data.coordinator
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ids = [item.entity_id for item in entities if item.disabled_by is None]
    now = dt_util.utcnow()
    try:
        running_core.stop()
        async_fire_time_changed(
            hass, now + coordinator.update_interval + timedelta(seconds=1)
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.state is ConfigEntryState.LOADED
        assert all(
            hass.states.get(entity_id).state == STATE_UNAVAILABLE for entity_id in ids
        )
        running_core.start()
        async_fire_time_changed(
            hass, now + 2 * coordinator.update_interval + timedelta(seconds=2)
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.state is ConfigEntryState.LOADED
        assert all(
            hass.states.get(entity_id).state != STATE_UNAVAILABLE for entity_id in ids
        )
    finally:
        if running_core.process.poll() is not None:
            running_core.start()
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

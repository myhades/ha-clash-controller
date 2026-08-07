"""Initializations for Clash Controller."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS, CONF_API_URL, CONF_BEAR_TOKEN, CONF_ALLOW_UNSAFE
from .api import ClashAPI
from .coordinator import ClashControllerCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

@dataclass
class ClashRuntimeData:
    """Class to hold integration data."""
    coordinator: ClashControllerCoordinator
    api: ClashAPI

type ClashConfigEntry = ConfigEntry[ClashRuntimeData]

async def async_setup_entry(hass: HomeAssistant, entry: ClashConfigEntry) -> bool:
    """Set up Clash Controller from a config entry."""

    api = ClashAPI(
        hass,
        host=entry.data[CONF_API_URL],
        token=entry.data[CONF_BEAR_TOKEN],
        entry_id=entry.entry_id,
        allow_unsafe=entry.data.get(CONF_ALLOW_UNSAFE, False),
        available_endpoints=entry.data.get("available_endpoints"),
        capabilities=entry.data.get("capabilities"),
    )

    coordinator = ClashControllerCoordinator(hass, entry)
    coordinator.api = api
    await _async_migrate_unique_ids(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        if entry.data.get("available_endpoints"):
            _LOGGER.warning("Clash 暂时无法连接，使用缓存模式启动: %s", err)
        else:
            raise err

    if coordinator.last_update_success:
        capabilities = coordinator.api.capabilities or {}
        available_endpoints = [list(item) for item in (coordinator.api.available_endpoints or [])]
        if (
            entry.data.get("capabilities") != capabilities
            or entry.data.get("available_endpoints") != available_endpoints
        ):
            hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    "available_endpoints": available_endpoints,
                    "capabilities": capabilities,
                },
            )

    entry.runtime_data = ClashRuntimeData(coordinator=coordinator, api=api)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)
    return True

async def _async_migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """将旧实体的 Unique ID 从基于 IP 的格式迁移到基于 Entry ID 的格式。"""
    ent_reg = er.async_get(hass)
    existing_entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    for entity_entry in existing_entries:
        old_uid = entity_entry.unique_id
        if not old_uid.startswith(entry.entry_id):
            parts = old_uid.split("_")
            new_uid = f"{entry.entry_id}_{'_'.join(parts[-2:])}"
            _LOGGER.debug("Migrating unique_id from [%s] to [%s]", old_uid, new_uid)
            try:
                ent_reg.async_update_entity(entity_entry.entity_id, new_unique_id=new_uid)
            except ValueError:
                _LOGGER.warning("Could not migrate unique_id for %s, new ID already exists", entity_entry.entity_id)

async def _async_update_listener(hass: HomeAssistant, entry: ClashConfigEntry):
    """处理选项流更新。"""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ClashConfigEntry) -> bool:
    """卸载配置条目。"""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:

        if not hass.config_entries.async_entries(DOMAIN):
            for service in list(hass.services.async_services_for_domain(DOMAIN)):
                hass.services.async_remove(DOMAIN, service)
                
    return unload_ok
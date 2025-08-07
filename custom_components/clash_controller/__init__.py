"""Initializations for Clash Controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .coordinator import ClashControllerCoordinator
from .services import ClashServicesSetup

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]

@dataclass
class RuntimeData:
    """Class to hold integration data."""

    coordinator: DataUpdateCoordinator
    cancel_update_listener: Callable
    setup_done: bool = False


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Clash Controller from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    runtime_data: RuntimeData | None = hass.data[DOMAIN].get(config_entry.entry_id)
    setup_done = runtime_data.setup_done if runtime_data else False
    coordinator = ClashControllerCoordinator(hass, config_entry)

    if not config_entry.data.get("available_endpoints"):
        try:
            available_endpoints = await coordinator.api.async_detect_available_endpoints()
            hass.config_entries.async_update_entry(
                config_entry,
                data={**config_entry.data, "available_endpoints": available_endpoints},
            )
        except Exception as err:
            _LOGGER.debug(f"Failed to detect available endpoints: {err}")


    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        if not setup_done:
            raise err
        _LOGGER.warning(err)
        coordinator.data = coordinator.data or []

    cancel_update_listener = config_entry.add_update_listener(_async_update_listener)
    hass.data[DOMAIN][config_entry.entry_id] = RuntimeData(
        coordinator, cancel_update_listener, True
    )
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    ClashServicesSetup(hass, config_entry)
    return True


async def _async_update_listener(hass: HomeAssistant, config_entry):
    """Handle config options update."""

    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry) -> bool:
    """Handle entry removal."""

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    for service in hass.services.async_services_for_domain(DOMAIN):
        hass.services.async_remove(DOMAIN, service)
    hass.data[DOMAIN][config_entry.entry_id].cancel_update_listener()
    coordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator
    if coordinator:
        await coordinator.api.close_session()
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)
    return unload_ok
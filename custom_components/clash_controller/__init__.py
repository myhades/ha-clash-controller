"""Initializations for Clash Controller."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry

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

    coordinator: ClashControllerCoordinator
    setup_done: bool = False


type ClashControllerConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ClashControllerConfigEntry
) -> bool:
    """Set up Clash Controller from a config entry."""

    runtime_data: RuntimeData | None = getattr(config_entry, "runtime_data", None)
    setup_done = runtime_data.setup_done if runtime_data else False
    coordinator = ClashControllerCoordinator(hass, config_entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        if not setup_done:
            await coordinator.api.close_session()
            raise err
        _LOGGER.warning(err)
        coordinator.data = coordinator.data or []

    if coordinator.last_update_success:
        capabilities = coordinator.api.capabilities or {}
        available_endpoints = coordinator.api.available_endpoints or []
        normalized_endpoints = [list(item) for item in available_endpoints]
        if (
            config_entry.data.get("capabilities") != capabilities
            or config_entry.data.get("available_endpoints") != normalized_endpoints
        ):
            hass.config_entries.async_update_entry(
                config_entry,
                data={
                    **config_entry.data,
                    "available_endpoints": normalized_endpoints,
                    "capabilities": capabilities,
                },
            )

    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_update_listener)
    )
    config_entry.runtime_data = RuntimeData(coordinator, True)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    ClashServicesSetup(hass)
    return True


async def _async_update_listener(
    hass: HomeAssistant, config_entry: ClashControllerConfigEntry
) -> None:
    """Handle config options update."""

    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ClashControllerConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Handle entry removal."""

    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: ClashControllerConfigEntry
) -> bool:
    """Unload a config entry."""

    runtime_data: RuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator
    if coordinator:
        await coordinator.api.close_session()
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    if unload_ok:
        other_loaded_entries = [
            entry
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            if entry.entry_id != config_entry.entry_id
        ]
        if not other_loaded_entries:
            for service in list(hass.services.async_services_for_domain(DOMAIN)):
                hass.services.async_remove(DOMAIN, service)
    return unload_ok

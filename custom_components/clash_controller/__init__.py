"""Initializations for Clash Controller."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

from .coordinator import ClashControllerCoordinator
from .services import ClashServicesSetup

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]


@dataclass
class RuntimeData:
    """Class to hold integration data."""

    coordinator: ClashControllerCoordinator


type ClashControllerConfigEntry = ConfigEntry[RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-wide service actions."""
    ClashServicesSetup(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ClashControllerConfigEntry
) -> bool:
    """Set up Clash Controller from a config entry."""

    coordinator = ClashControllerCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()

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

    config_entry.runtime_data = RuntimeData(coordinator)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True

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

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    return unload_ok

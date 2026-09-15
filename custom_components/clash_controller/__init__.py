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

    config_entry.runtime_data = RuntimeData(coordinator)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ClashControllerConfigEntry
) -> bool:
    """Remove obsolete runtime state from persisted entry data."""
    if config_entry.version == 1 and config_entry.minor_version < 2:
        data = dict(config_entry.data)
        data.pop("available_endpoints", None)
        data.pop("capabilities", None)
        hass.config_entries.async_update_entry(
            config_entry,
            data=data,
            minor_version=2,
        )
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

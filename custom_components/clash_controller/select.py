"""Select platform for Clash Controller."""

import logging
from urllib.parse import quote

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import BaseEntity
from .const import DOMAIN
from .coordinator import ClashControllerCoordinator, ClashEntityData

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):

    coordinator: ClashControllerCoordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator

    select_types = {
        "proxy_group_selector": GroupSelect,
        "core_mode_selector": CoreModeSelect,
    }

    selects = [
        select_types[entity_type](coordinator, entity_data)
        for entity_data in coordinator.data
        if (entity_type := entity_data.entity_type) in select_types
    ]

    async_add_entities(selects)

class SelectEntityBase(BaseEntity, SelectEntity):
    """Base select entity class."""

    def __init__(
        self, coordinator: ClashControllerCoordinator, entity_data: ClashEntityData
    ) -> None:
        super().__init__(coordinator, entity_data)
    
    @property
    def current_option(self) -> str | None:
        return self.entity_data.state

    @property
    def options(self) -> list[str] | None:
        return self.entity_data.options

class GroupSelect(SelectEntityBase):
    """Implementation of a group select."""

    def __init__(
        self, coordinator: ClashControllerCoordinator, entity_data: ClashEntityData
    ) -> None:
        super().__init__(coordinator, entity_data)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        group = self._attr_name.strip()
        node = option.strip()
        try:
            await self.coordinator.api.async_request(
                "PUT",
                f"proxies/{quote(group, safe='')}",
                json_data={"name": node},
                suppress_errors=False,
            )
        except Exception as err:
            raise HomeAssistantError(f"Failed to set proxy group {group} to {node}.") from err
        self.entity_data.state = option
        self.async_write_ha_state()

class CoreModeSelect(SelectEntityBase):
    """Implementation of core mode select."""

    def __init__(
        self, coordinator: ClashControllerCoordinator, entity_data: ClashEntityData
    ) -> None:
        super().__init__(coordinator, entity_data)

    async def async_select_option(self, option: str) -> None:
        """Change Clash running mode."""
        mode = option.strip()
        if not mode:
            raise HomeAssistantError("Mode cannot be empty.")
        try:
            await self.coordinator.api.async_request(
                "PATCH",
                "configs",
                json_data={"mode": mode},
                suppress_errors=False,
            )
        except Exception:
            try:
                await self.coordinator.api.async_request(
                    "PUT",
                    "configs",
                    json_data={"mode": mode},
                    suppress_errors=False,
                )
            except Exception as err:
                raise HomeAssistantError(f"Failed to set mode to {mode}.") from err
        self.entity_data.state = mode
        self.async_write_ha_state()

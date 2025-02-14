"""Select platform for Clash Controller."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import BaseEntity
from .const import DOMAIN
from .coordinator import ClashControllerCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):

    coordinator: ClashControllerCoordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator

    select_types = {
        "proxy_group_selector": GroupSelect,
    }

    selects = [
        select_types[entity_type](coordinator, entity_data)
        for entity_data in coordinator.data
        if (entity_type := entity_data.get("entity_type")) in select_types
    ]

    async_add_entities(selects)

class SelectEntityBase(BaseEntity, SelectEntity):
    """Base select entity class."""

    def __init__(self, coordinator: ClashControllerCoordinator, entity_data: dict) -> None:
        super().__init__(coordinator, entity_data)
    
    @property
    def current_option(self) -> str | None:
        return self.entity_data.get("state")

    @property
    def options(self) -> dict | None:
        return self.entity_data.get("options")

class GroupSelect(SelectEntityBase):
    """Implementation of a group select."""

    def __init__(self, coordinator: ClashControllerCoordinator, entity_data: dict) -> None:
        super().__init__(coordinator, entity_data)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        group = self._attr_name.strip()
        node = option.strip()
        try:
            await self.coordinator.api.async_request("PUT", f"proxies/{group}", json_data={"name": node})
        except Exception as err:
            raise HomeAssistantError(f"Failed to set proxy group {group} to {node}.") from err
        self._attr_current_option = option
        self.async_write_ha_state()
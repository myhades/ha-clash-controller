"""Select platform for Clash Controller."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
        select_types[entity_type](coordinator, entityData)
        for entityData in coordinator.data
        if (entity_type := entityData.get("entity_type")) in select_types
    ]

    async_add_entities(selects)

class SelectEntityBase(BaseEntity, SelectEntity):
    """Base select entity class."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)
        self._attr_current_option = self.entityData.get("state")
        self._attr_options = self.entityData.get("options")

class GroupSelect(SelectEntityBase):
    """Implementation of a group select."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.coordinator.api.set_proxy_group(self._attr_name, option)
        self._attr_current_option = option
        self.async_write_ha_state()
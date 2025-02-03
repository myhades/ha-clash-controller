"""Button platform for Clash Controller."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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

    button_types = {
        "fakeip_flush_button": ButtonEntityBase,
    }

    buttons = [
        button_types[entity_type](coordinator, entityData)
        for entityData in coordinator.data
        if (entity_type := entityData.get("entity_type")) in button_types
    ]

    async_add_entities(buttons)

class ButtonEntityBase(BaseEntity, ButtonEntity):
    """Base button entity class."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)

    async def async_press(self) -> None:
        """Press action."""
        method = self.entityData.get("action").get("method")
        args = self.entityData.get("action").get("args", [])
        await method(*args)
        self.async_write_ha_state()
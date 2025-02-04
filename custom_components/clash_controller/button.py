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
        button_types[entity_type](coordinator, entity_data)
        for entity_data in coordinator.data
        if (entity_type := entity_data.get("entity_type")) in button_types
    ]

    async_add_entities(buttons)

class ButtonEntityBase(BaseEntity, ButtonEntity):
    """Base button entity class."""

    def __init__(self, coordinator: ClashControllerCoordinator, entity_data: dict) -> None:
        super().__init__(coordinator, entity_data)

    async def async_press(self) -> None:
        """Press action."""
        method = self.entity_data.get("action").get("method")
        args = self.entity_data.get("action").get("args", [])
        await method(*args)
        self.async_write_ha_state()
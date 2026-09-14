"""Button platform for Clash Controller."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ClashControllerConfigEntry
from .base import BaseEntity
from .coordinator import ClashControllerCoordinator, ClashEntityData

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ClashControllerConfigEntry,
    async_add_entities: AddEntitiesCallback,
):

    coordinator: ClashControllerCoordinator = config_entry.runtime_data.coordinator

    button_types = {
        "fakeip_flush_button": ButtonEntityBase,
        "dns_flush_button": ButtonEntityBase,
        "provider_healthcheck_button": ButtonEntityBase,
    }

    buttons = [
        button_types[entity_type](coordinator, entity_data)
        for entity_data in coordinator.data
        if (entity_type := entity_data.entity_type) in button_types
    ]

    async_add_entities(buttons)

class ButtonEntityBase(BaseEntity, ButtonEntity):
    """Base button entity class."""

    def __init__(
        self, coordinator: ClashControllerCoordinator, entity_data: ClashEntityData
    ) -> None:
        super().__init__(coordinator, entity_data)

    async def async_press(self) -> None:
        """Press action."""
        action = self.entity_data.action or {}
        method = action.get("method")
        args = action.get("args", [])
        kwargs = action.get("kwargs", {})
        if method is None:
            raise HomeAssistantError("No action defined for this button.")
        try:
            await method(*args, **kwargs)
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to execute {self.entity_data.unique_key}."
            ) from err
        self.async_write_ha_state()

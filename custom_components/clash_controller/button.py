"""Button platform for Clash Controller."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ClashControllerConfigEntry
from .base import BaseEntity
from .const import DOMAIN
from .coordinator import ClashControllerCoordinator, ClashEntityData

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ClashControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up button entities for a config entry."""

    coordinator: ClashControllerCoordinator = config_entry.runtime_data.coordinator

    button_types = {
        "fakeip_flush_button": ButtonEntityBase,
        "dns_flush_button": ButtonEntityBase,
        "provider_healthcheck_button": ButtonEntityBase,
    }

    known_ids: set[str] = set()

    @callback
    def async_add_new_buttons() -> None:
        buttons = []
        for entity_data in coordinator.data:
            if entity_data.unique_id in known_ids:
                continue
            if entity_type := button_types.get(entity_data.entity_type):
                buttons.append(entity_type(coordinator, entity_data))
                known_ids.add(entity_data.unique_id)
        if buttons:
            async_add_entities(buttons)

    async_add_new_buttons()
    config_entry.async_on_unload(coordinator.async_add_listener(async_add_new_buttons))

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
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="button_action_missing",
            )
        try:
            await method(*args, **kwargs)
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="button_action_failed",
                translation_placeholders={
                    "action": self.entity_data.unique_key or "unknown",
                    "error": str(err),
                },
            ) from err
        self.async_write_ha_state()

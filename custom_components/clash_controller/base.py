"""Base entity for Clash Controller."""

import logging

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ClashControllerCoordinator

_LOGGER = logging.getLogger(__name__)


class BaseEntity(CoordinatorEntity):
    """Base entity class."""

    coordinator: ClashControllerCoordinator
    _attr_has_entity_name = True

    def __init__(self, coordinator: ClashControllerCoordinator, entity_data: dict) -> None:
        super().__init__(coordinator)
        self.entity_data = entity_data
        self._attr_device_info = self.coordinator.device
        
        self._entity_name = self.entity_data.get("name")
        self._entity_unique_id = self.entity_data.get("unique_id")
        
        self._attr_name = self._entity_name
        self._attr_unique_id = self._entity_unique_id
        self._attr_icon = self.entity_data.get("icon")
        self._attr_available = True

        _LOGGER.debug(f"Entity {self._attr_name} ({self._attr_unique_id}) initialized.")

    @callback
    def _handle_coordinator_update(self) -> None:
        self.entity_data = self.coordinator.get_data_by_name(self.entity_data.get("name")) or {}
        self.async_write_ha_state()
    
    @property
    def extra_state_attributes(self):
        """Default extra state attributes for base sensor."""
        return self.entity_data.get("attributes", None)

    @property
    def translation_key(self):
        """Default translation_key for base sensor."""
        return self.entity_data.get("translation_key", None)


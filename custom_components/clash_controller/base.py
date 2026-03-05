"""Base entity for Clash Controller."""

import logging

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ClashControllerCoordinator, ClashEntityData

_LOGGER = logging.getLogger(__name__)


class BaseEntity(CoordinatorEntity):
    """Base entity class."""

    coordinator: ClashControllerCoordinator
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ClashControllerCoordinator, entity_data: ClashEntityData
    ) -> None:
        super().__init__(coordinator)
        self.entity_data = entity_data
        self._attr_device_info = self.coordinator.device

        self._entity_name = self.entity_data.name
        self._entity_unique_id = self.entity_data.unique_id

        if self._entity_name is not None:
            self._attr_name = self._entity_name
        self._attr_unique_id = self._entity_unique_id
        self._attr_icon = self.entity_data.icon
        self._attr_translation_key = self.entity_data.translation_key
        self._attr_available = True

        entity_label = (
            self._entity_name
            or self.entity_data.translation_key
            or self.entity_data.entity_type
        )
        _LOGGER.debug("Entity %s (%s) initialized.", entity_label, self._attr_unique_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        new_data = self.coordinator.get_data_by_unique_id(self._entity_unique_id)
        if (new_data is None) and self._entity_name:
            new_data = self.coordinator.get_data_by_name(self._entity_name)
        if new_data:
            self.entity_data = new_data
            self._attr_available = True
        else:
            self._attr_available = False
        self.async_write_ha_state()
    
    @property
    def extra_state_attributes(self):
        """Default extra state attributes for base sensor."""
        return self.entity_data.attributes

    @property
    def translation_key(self):
        """Return translation key with backward-compatible behavior."""
        return self.entity_data.translation_key


"""Base entity for Clash Controller."""

import logging
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ClashControllerCoordinator

_LOGGER = logging.getLogger(__name__)


class BaseEntity(CoordinatorEntity):
    """Base entity class."""

    coordinator: ClashControllerCoordinator
    _attr_has_entity_name = True

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator)
        self.entityData = entityData

        self._attr_device_info = self.coordinator.device
        self._attr_name = self.entityData.get("name")
        self._attr_unique_id = self.entityData.get("unique_id")
        self._attr_icon = self.entityData.get("icon")

        _LOGGER.debug(f"Entity {self._attr_name} ({self._attr_unique_id}) initialized.")

    @callback
    def _handle_coordinator_update(self) -> None:
        self.entityData = self.coordinator.get_data_by_name(self.entityData.get("name"))
        self.async_write_ha_state()
    
    @property
    def extra_state_attributes(self):
        """Default extra state attributes for base sensor."""
        return self.entityData.get("attributes", None)


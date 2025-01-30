"""Sensor platform for Clash Controller."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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

    sensor_types = {
        "traffic_sensor": TrafficSensor,
        "memory_sensor": MemorySensor,
        "total_traffic_sensor": TotalTrafficSensor,
        "connection_sensor": ConnectionSensor,
        "proxy_group_sensor": GroupSensor,
    }

    sensors = [
        sensor_types[entity_type](coordinator, entityData)
        for entityData in coordinator.data
        if (entity_type := entityData.get("entity_type")) in sensor_types
    ]

    async_add_entities(sensors)

class SensorEntityBase(BaseEntity, SensorEntity):
    """Base sensor entity class."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)

    @property
    def native_value(self) -> int | None:
        """Default state of the base sensor."""
        value = self.entityData.get("state", None)
        return int(value) if value is not None else None

class TrafficSensor(SensorEntityBase):
    """Implementation of a traffic sensor."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)
        self._attr_device_class = SensorDeviceClass.DATA_RATE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "bit/s"
        self._attr_suggested_unit_of_measurement = "kB/s"
        self._attr_suggested_display_precision = 0

class TotalTrafficSensor(SensorEntityBase):
    """Implementation of a traffic sensor."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "B"
        self._attr_suggested_unit_of_measurement = "GB"
        self._attr_suggested_display_precision = 2

class ConnectionSensor(SensorEntityBase):
    """Implementation of a traffic sensor."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)
        self._attr_state_class = SensorStateClass.MEASUREMENT

class MemorySensor(SensorEntityBase):
    """Implementation of a memory sensor."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)
        self._attr_device_class = SensorDeviceClass.DATA_SIZE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "B"
        self._attr_suggested_unit_of_measurement = "MB"
        self._attr_suggested_display_precision = 0

class GroupSensor(SensorEntityBase):
    """Implementation of a memory sensor."""

    def __init__(self, coordinator: ClashControllerCoordinator, entityData: dict) -> None:
        super().__init__(coordinator, entityData)
    
    @property
    def native_value(self) -> int | None:
        """Default state of the base sensor."""
        return self.entityData.get("state", None)
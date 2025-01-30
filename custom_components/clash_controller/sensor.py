"""Sensor platform for Clash Controller."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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

    sensors = [
        TrafficSensor(coordinator, entityData)
        for entityData in coordinator.data
        if entityData.get("entity_type") == "traffic_sensor"
    ]+[
        MemorySensor(coordinator, entityData)
        for entityData in coordinator.data
        if entityData.get("entity_type") == "memory_sensor"
    ]+[
        TotalTrafficSensor(coordinator, entityData)
        for entityData in coordinator.data
        if entityData.get("entity_type") == "total_traffic_sensor"
    ]+[
        ConnectionSensor(coordinator, entityData)
        for entityData in coordinator.data
        if entityData.get("entity_type") == "connection_sensor"
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

    @property
    def extra_state_attributes(self):
        """Default extra state attributes for base sensor."""
        return self.entityData.get("attributes", None)

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
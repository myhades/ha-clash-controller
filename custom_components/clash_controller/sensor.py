"""Sensor platform for Clash Controller."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfDataRate, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ClashControllerConfigEntry
from .base import BaseEntity
from .coordinator import ClashControllerCoordinator, ClashEntityData

PARALLEL_UPDATES = 0

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    "upload_speed": SensorEntityDescription(
        key="upload_speed",
        translation_key="up_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
    ),
    "download_speed": SensorEntityDescription(
        key="download_speed",
        translation_key="down_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
    ),
    "upload_traffic": SensorEntityDescription(
        key="upload_traffic",
        translation_key="up_traffic",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
    ),
    "download_traffic": SensorEntityDescription(
        key="download_traffic",
        translation_key="down_traffic",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
    ),
    "connection_number": SensorEntityDescription(
        key="connection_number",
        translation_key="connection_number",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "proxy_provider_count": SensorEntityDescription(
        key="proxy_provider_count",
        translation_key="proxy_provider_count",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "rule_provider_count": SensorEntityDescription(
        key="rule_provider_count",
        translation_key="rule_provider_count",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "memory_used": SensorEntityDescription(
        key="memory_used",
        translation_key="memory_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ClashControllerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for a config entry."""
    coordinator: ClashControllerCoordinator = config_entry.runtime_data.coordinator

    sensors: list[SensorEntity] = []
    for entity_data in coordinator.data:
        if description := SENSOR_DESCRIPTIONS.get(entity_data.unique_key or ""):
            sensors.append(ClashNumericSensor(coordinator, entity_data, description))
        elif entity_data.entity_type == "proxy_group_sensor":
            sensors.append(GroupSensor(coordinator, entity_data))
        elif entity_data.entity_type == "streaming_detection":
            sensors.append(StreamingSensor(coordinator, entity_data))

    async_add_entities(sensors)


class SensorEntityBase(BaseEntity, SensorEntity):
    """Base sensor entity class."""


class ClashNumericSensor(SensorEntityBase):
    """Numeric sensor described by a static Home Assistant definition."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: ClashControllerCoordinator,
        entity_data: ClashEntityData,
        description: SensorEntityDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, entity_data)

    @property
    def native_value(self) -> int | float | None:
        """Return the latest numeric value."""
        value = self.entity_data.state
        return value if self._is_numeric(value) else None

    @property
    def available(self) -> bool:
        """Return whether this sensor has a valid numeric reading."""
        return super().available and self._is_numeric(self.entity_data.state)

    @staticmethod
    def _is_numeric(value: object) -> bool:
        """Return whether a value is a supported sensor number."""
        return isinstance(value, (int, float)) and not isinstance(value, bool)


class GroupSensor(SensorEntityBase):
    """Proxy group state sensor."""

    @property
    def native_value(self) -> str | None:
        """Return the selected proxy."""
        return self.entity_data.state


class StreamingSensor(SensorEntityBase):
    """Streaming service detection sensor."""

    _attr_device_class = SensorDeviceClass.ENUM

    @property
    def options(self) -> list[str] | None:
        """Return the possible service states."""
        return self.entity_data.options

    @property
    def native_value(self) -> str | None:
        """Return the detected service state."""
        return self.entity_data.state

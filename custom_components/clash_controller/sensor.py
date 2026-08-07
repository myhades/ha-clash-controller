"""Sensor platform for Clash Controller."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from dataclasses import replace

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfDataRate, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import BaseEntity

if TYPE_CHECKING:
    from . import ClashConfigEntry
    from .coordinator import ClashControllerCoordinator, ClashEntityData

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    "up_speed": SensorEntityDescription(
        key="up_speed",
        translation_key="up_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "down_speed": SensorEntityDescription(
        key="down_speed",
        translation_key="down_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "up_traffic": SensorEntityDescription(
        key="up_traffic",
        translation_key="up_traffic",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "down_traffic": SensorEntityDescription(
        key="down_traffic",
        translation_key="down_traffic",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "memory_used": SensorEntityDescription(
        key="memory_used",
        translation_key="memory_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "connection_number": SensorEntityDescription(
        key="connection_number",
        translation_key="connection_number",
        icon="mdi:transit-connection",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "proxy_provider_count": SensorEntityDescription(
        key="proxy_provider_count",
        translation_key="proxy_provider_count",
        icon="mdi:server-outline",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "rule_provider_count": SensorEntityDescription(
        key="rule_provider_count",
        translation_key="rule_provider_count",
        icon="mdi:file-document-outline",
        state_class=SensorStateClass.MEASUREMENT,
    ),
}

async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ClashConfigEntry, 
    async_add_entities: AddEntitiesCallback
):
    """传感器平台。"""
    coordinator = entry.runtime_data.coordinator
    entities = []

    for entity_data in coordinator.data:

        if entity_data.entity_type.endswith("_sensor") or entity_data.entity_type == "streaming_detection":
            
            description = SENSOR_DESCRIPTIONS.get(entity_data.unique_key)
            if not description:

                description = SensorEntityDescription(
                    key=entity_data.unique_key,
                    translation_key=entity_data.translation_key,
                    icon=entity_data.icon,
                )
                if entity_data.entity_type == "streaming_detection":
                    description = replace(
                        description,
                        device_class=SensorDeviceClass.ENUM,
                        options=entity_data.options
                    )

            entities.append(ClashSensorEntity(coordinator, entity_data, description))

    async_add_entities(entities)


class ClashSensorEntity(BaseEntity, SensorEntity):
    """通用传感器实现。"""

    entity_description: SensorEntityDescription

    def __init__(
        self, 
        coordinator: ClashControllerCoordinator, 
        entity_data: ClashEntityData,
        description: SensorEntityDescription
    ) -> None:
        """初始化传感器。"""

        self.entity_description = description
        self._attr_device_class = description.device_class
        super().__init__(coordinator, entity_data)

        if entity_data.name is not None:
            self._attr_name = entity_data.name
        else:
            if hasattr(self, "_attr_name"):
                delattr(self, "_attr_name")

    @property
    def native_value(self) -> float | int | str | None:
        """数值处理逻辑。"""
        value = self.entity_data.state
        if value is None:
            return None

        if self.entity_data.entity_type in ["proxy_group_sensor", "streaming_detection"]:
            return value

        try:

            if self.entity_description.suggested_display_precision and self.entity_description.suggested_display_precision > 0:
                return float(value)

            return int(float(value))
            
        except (ValueError, TypeError):

            if self.entity_description.state_class or self.entity_description.device_class:
                _LOGGER.debug(
                    " entity %s 的 API 值 '%s' 无法解析为数字，已安全置为 None", 
                    self.entity_id, value
                )
                return None
                
            return value
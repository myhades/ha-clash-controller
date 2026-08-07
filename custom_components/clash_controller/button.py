"""Button platform for Clash Controller."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import BaseEntity

if TYPE_CHECKING:
    from . import ClashConfigEntry
    from .coordinator import ClashControllerCoordinator, ClashEntityData

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True, kw_only=True)
class ClashButtonEntityDescription(ButtonEntityDescription):
    """描述 Clash 按钮的自定义类。"""

# 静态描述符配置
BUTTON_DESCRIPTIONS: Final[dict[str, ClashButtonEntityDescription]] = {
    "fakeip_flush_button": ClashButtonEntityDescription(
        key="fakeip_flush_button",
        translation_key="flush_cache",
        icon="mdi:cached",
    ),
    "dns_flush_button": ClashButtonEntityDescription(
        key="dns_flush_button",
        translation_key="flush_dns_cache",
        icon="mdi:cached",
    ),
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClashConfigEntry, 
    async_add_entities: AddEntitiesCallback,
) -> None:
    """基于 Config Entry 设置按钮平台。"""
    
    coordinator = entry.runtime_data.coordinator

    entities: list[ClashButtonEntity] = []

    for entity_data in coordinator.data:
        if entity_data.entity_type in [
            "fakeip_flush_button", 
            "dns_flush_button", 
            "provider_healthcheck_button"
        ]:
            # 获取或动态创建描述符
            description = BUTTON_DESCRIPTIONS.get(entity_data.entity_type)
            if not description:
                description = ClashButtonEntityDescription(
                    key=entity_data.unique_key or entity_data.entity_type,
                    translation_key=entity_data.translation_key,
                    icon=entity_data.icon,
                )

            entities.append(ClashButtonEntity(coordinator, entity_data, description))

    async_add_entities(entities)

class ClashButtonEntity(BaseEntity, ButtonEntity):
    """按钮实体类"""

    entity_description: ClashButtonEntityDescription

    def __init__(
        self, 
        coordinator: ClashControllerCoordinator, 
        entity_data: ClashEntityData,
        description: ClashButtonEntityDescription
    ) -> None:
        """初始化按钮。"""

        self.entity_description = description
        super().__init__(coordinator, entity_data)

    async def async_press(self) -> None:
        action = self.entity_data.action or {}
        method = action.get("method")
        args = action.get("args", [])
        kwargs = action.get("kwargs", {})
        
        if method is None:
            raise HomeAssistantError("No action defined for this button.")
            
        try:
            await method(*args, **kwargs)
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error executing button action: %s", err)
            raise HomeAssistantError(f"Action failed: {err}") from err
"""Select platform for Clash Controller."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import BaseEntity

if TYPE_CHECKING:
    from . import ClashConfigEntry
    from .coordinator import ClashControllerCoordinator, ClashEntityData

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True, kw_only=True)
class ClashSelectDescription(SelectEntityDescription):
    """描述 Clash 选择器的自定义类。"""

# 定义核心模式的静态描述符
SELECT_DESCRIPTIONS: Final[dict[str, ClashSelectDescription]] = {
    "core_mode_selector": ClashSelectDescription(
        key="core_mode",
        translation_key="core_mode",
        icon="mdi:tune",
    ),
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClashConfigEntry, 
    async_add_entities: AddEntitiesCallback,
) -> None:
    """基于描述符设置选择器平台。"""
    coordinator = entry.runtime_data.coordinator
    entities: list[SelectEntity] = []

    for entity_data in coordinator.data:
        if entity_data.entity_type in ["proxy_group_selector", "core_mode_selector"]:

            description = SELECT_DESCRIPTIONS.get(entity_data.entity_type)
            
            if not description:
                description = ClashSelectDescription(
                    key=entity_data.unique_key,
                    translation_key="proxy_group",
                    icon="mdi:network-outline",
                )

            if entity_data.entity_type == "core_mode_selector":
                entities.append(ClashCoreModeSelect(coordinator, entity_data, description))
            else:
                entities.append(ClashGroupSelect(coordinator, entity_data, description))

    async_add_entities(entities)

class ClashSelectBase(BaseEntity, SelectEntity):
    """Select 平台抽象基类。"""
    
    entity_description: ClashSelectDescription

    def __init__(
        self, 
        coordinator: ClashControllerCoordinator, 
        entity_data: ClashEntityData,
        description: ClashSelectDescription
    ) -> None:
        super().__init__(coordinator, entity_data)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        """从 entity_data 映射状态。"""
        return self.entity_data.state

    @property
    def options(self) -> list[str]:
        """从 entity_data 映射可选列表。"""
        return self.entity_data.options or []


class ClashGroupSelect(ClashSelectBase):
    """代理组选择器实现。"""

    def __init__(self, coordinator, entity_data, description) -> None:
        super().__init__(coordinator, entity_data, description)

        self._attr_name = entity_data.name

    async def async_select_option(self, option: str) -> None:
        """执行代理组切换。"""
        group = self._attr_name.strip()
        try:
            await self.coordinator.api.async_request(
                "PUT",
                f"proxies/{quote(group, safe='')}",
                json_data={"name": option.strip()},
                suppress_errors=False,
            )
            self.entity_data.state = option
            self.async_write_ha_state()
        except Exception as err:
            raise HomeAssistantError(f"设置代理组 {group} 失败: {err}") from err

class ClashCoreModeSelect(ClashSelectBase):
    """核心运行模式选择器实现。"""

    def __init__(self, coordinator, entity_data, description) -> None:
        super().__init__(coordinator, entity_data, description)

        self._attr_name = None

    async def async_select_option(self, option: str) -> None:
        """执行核心模式切换（PATCH -> PUT 回退逻辑）。"""
        mode = option.strip()
        try:
            try:
                # 尝试现代 PATCH 接口
                await self.coordinator.api.async_request(
                    "PATCH", "configs", json_data={"mode": mode}, suppress_errors=False
                )
            except Exception:
                # 回退到旧版 PUT 接口
                await self.coordinator.api.async_request(
                    "PUT", "configs", json_data={"mode": mode}, suppress_errors=False
                )
            
            self.entity_data.state = mode
            self.async_write_ha_state()
        except Exception as err:
            raise HomeAssistantError(f"切换核心模式至 {mode} 失败: {err}") from err
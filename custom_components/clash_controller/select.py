"""Select platform for Clash Controller."""

import logging
from urllib.parse import quote

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
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
    """Set up select entities for a config entry."""

    coordinator: ClashControllerCoordinator = config_entry.runtime_data.coordinator

    select_types = {
        "proxy_group_selector": GroupSelect,
        "core_mode_selector": CoreModeSelect,
    }

    known_ids: set[str] = set()

    @callback
    def async_add_new_selects() -> None:
        selects = []
        for entity_data in coordinator.data:
            if entity_data.unique_id in known_ids:
                continue
            if entity_type := select_types.get(entity_data.entity_type):
                selects.append(entity_type(coordinator, entity_data))
                known_ids.add(entity_data.unique_id)
        if selects:
            async_add_entities(selects)

    async_add_new_selects()
    config_entry.async_on_unload(coordinator.async_add_listener(async_add_new_selects))

class SelectEntityBase(BaseEntity, SelectEntity):
    """Base select entity class."""

    def __init__(
        self, coordinator: ClashControllerCoordinator, entity_data: ClashEntityData
    ) -> None:
        super().__init__(coordinator, entity_data)
    
    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self.entity_data.state

    @property
    def options(self) -> list[str] | None:
        """Return available select options."""
        return self.entity_data.options

class GroupSelect(SelectEntityBase):
    """Implementation of a group select."""

    def __init__(
        self, coordinator: ClashControllerCoordinator, entity_data: ClashEntityData
    ) -> None:
        super().__init__(coordinator, entity_data)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        group = self._attr_name.strip()
        node = option.strip()
        try:
            await self.coordinator.api.async_request(
                "PUT",
                f"proxies/{quote(group, safe='')}",
                json_data={"name": node},
            )
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="proxy_group_selection_failed",
                translation_placeholders={
                    "error": str(err),
                    "group": group,
                    "node": node,
                },
            ) from err
        self.entity_data.state = option
        self.async_write_ha_state()

class CoreModeSelect(SelectEntityBase):
    """Implementation of core mode select."""

    def __init__(
        self, coordinator: ClashControllerCoordinator, entity_data: ClashEntityData
    ) -> None:
        super().__init__(coordinator, entity_data)

    async def async_select_option(self, option: str) -> None:
        """Change Clash running mode."""
        mode = option.strip()
        if not mode:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="empty_mode",
            )
        try:
            await self.coordinator.api.async_request(
                "PATCH",
                "configs",
                json_data={"mode": mode},
            )
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="mode_selection_failed",
                translation_placeholders={"error": str(err), "mode": mode},
            ) from err
        self.entity_data.state = mode
        self.async_write_ha_state()

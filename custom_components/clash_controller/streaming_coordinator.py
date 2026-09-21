"""Coordinator for streaming availability checks."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_STREAMING_PROXY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ClashEntityData
from .streaming import (
    SERVICE_TABLE,
    STREAMING_STATES,
    InvalidStreamingProxyError,
    StreamingDetector,
    parse_streaming_proxy,
)

_LOGGER = logging.getLogger(__name__)


class StreamingCoordinator(DataUpdateCoordinator[list[ClashEntityData]]):
    """Fetch streaming availability independently of the Clash API."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        device_id: str,
        parent_device_id: str,
    ) -> None:
        self.device_id = device_id
        self.device = DeviceInfo(
            identifiers={(DOMAIN, f"{device_id}_streaming")},
            translation_key="streaming_detection",
            via_device_id=parent_device_id,
        )
        self._data_by_unique_id: dict[str, ClashEntityData] = {}

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} streaming ({config_entry.data['api_url']})",
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                )
            ),
        )

        self.detector: StreamingDetector | None = None
        try:
            proxy = parse_streaming_proxy(
                config_entry.options.get(CONF_STREAMING_PROXY, "")
            )
        except InvalidStreamingProxyError:
            _LOGGER.warning(
                "Streaming detection is enabled without a valid proxy address"
            )
        else:
            self.detector = StreamingDetector(async_get_clientsession(hass), proxy)

    def _entity_unique_id(self, service: str) -> str:
        """Return the stable entity unique ID for a streaming service."""
        return f"{self.device_id}_streaming_detection_{service}"

    def _enabled_services(self) -> set[str]:
        """Return services whose entity-registry entries are enabled."""
        registry = er.async_get(self.hass)
        enabled: set[str] = set()
        for service, service_info in SERVICE_TABLE.items():
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, self._entity_unique_id(service)
            )
            if entity_id is None:
                if service_info.enabled_default:
                    enabled.add(service)
                continue
            entry = registry.async_get(entity_id)
            if entry is not None and entry.disabled_by is None:
                enabled.add(service)
        return enabled

    async def _async_update_data(self) -> list[ClashEntityData]:
        """Check enabled services and update all streaming entities."""
        streaming = (
            await self.detector.async_fetch_data(self._enabled_services())
            if self.detector is not None
            else {}
        )
        entities = self._build_entities(streaming)
        self._data_by_unique_id = {item.unique_id: item for item in entities}
        return entities

    def _build_entities(self, streaming: dict[str, Any]) -> list[ClashEntityData]:
        """Create streaming sensor data from normalized checker results."""
        entities: list[ClashEntityData] = []
        for service, service_info in SERVICE_TABLE.items():
            details = streaming.get(service, {})
            entities.append(
                ClashEntityData(
                    name=None,
                    state=details.get("state", "unknown"),
                    icon=service_info.icon,
                    attributes={
                        key: value for key, value in details.items() if key != "state"
                    },
                    options=STREAMING_STATES,
                    entity_type="streaming_detection",
                    translation_key="streaming_service",
                    translation_placeholders={"service": service_info.name},
                    enabled_default=service_info.enabled_default,
                    unique_key=service,
                    unique_id=self._entity_unique_id(service),
                    device_info=self.device,
                )
            )
        return entities

    def get_data_by_unique_id(self, unique_id: str) -> ClashEntityData | None:
        """Retrieve streaming data by entity unique ID."""
        return self._data_by_unique_id.get(unique_id)

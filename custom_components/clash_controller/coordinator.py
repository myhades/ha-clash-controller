"""Data coordinator for Clash Controller."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ClashAPI, SERVICE_TABLE
from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_CONCURRENT_CONNECTIONS,
    DEFAULT_STREAMING_DETECTION,
    CONF_CONCURRENT_CONNECTIONS,
    CONF_STREAMING_DETECTION,
)

_LOGGER = logging.getLogger(__name__)


EntityData = dict[str, Any]


class ClashControllerCoordinator(DataUpdateCoordinator[list[EntityData]]):
    """A coordinator to fetch data from the Clash API."""

    device: DeviceInfo | None = None

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """
        Initialize the Clash Controller coordinator.
        """
        self.host = config_entry.data["api_url"]
        self.token = config_entry.data["bearer_token"]
        self.allow_unsafe = config_entry.data["allow_unsafe"]

        self.poll_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        self.concurrent_connections = config_entry.options.get(
            CONF_CONCURRENT_CONNECTIONS, DEFAULT_CONCURRENT_CONNECTIONS
        )
        self.streaming_detection = config_entry.options.get(
            CONF_STREAMING_DETECTION, DEFAULT_STREAMING_DETECTION
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({self.host})",
            update_method=self._async_update_data,
            update_interval=timedelta(seconds=self.poll_interval),
        )

        self.api = ClashAPI(host=self.host, token=self.token, allow_unsafe=self.allow_unsafe)
        _LOGGER.debug(f"Clash API initialized for coordinator {self.name}")

    async def _get_device(self) -> DeviceInfo:
        """
        Generate a device object.
        """
        version_info = await self.api.get_version()
        return DeviceInfo(
            name = "Clash Instance",
            manufacturer = "Clash",
            model = version_info.get("meta"),
            sw_version = version_info.get("version"),
            identifiers = {(DOMAIN, self.api.device_id)},
        )

    async def _async_update_data(self):
        """
        Fetch data from API endpoint.
        """
        response: dict[str, Any] = {}
        _LOGGER.debug("Start fetching data from Clash.")

        try:
            if await self.api.connected(suppress_errors=False):
                response = await self.api.fetch_data(
                    streaming_detection=self.streaming_detection,
                    suppress_errors=True,
                )
                if not self.device:
                    self.device = await self._get_device()
        except Exception as err:
            raise UpdateFailed(err) from err
        
        data = self._build_entity_data(response)
        real_entities = [
            item for item in data 
            if item.get("entity_type") != "fakeip_flush_button"
        ]
        if not real_entities:
            raise UpdateFailed("Empty response")

        return data

    def _build_entity_data(self, response: dict[str, Any]) -> list[EntityData]:
        """Construct entity descriptions from API response."""

        entity_data: list[EntityData] = []
        entity_data.extend(self._build_traffic_entities(response.get("traffic", {})))
        entity_data.extend(self._build_connection_entities(response.get("connections", {})))
        entity_data.extend(self._build_memory_entities(response.get("memory", {})))
        entity_data.extend(self._build_proxy_entities(response.get("proxies", {})))
        entity_data.extend(self._build_streaming_entities(response.get("streaming", {})))
        entity_data.append(self._build_fakeip_button())

        for item in entity_data:
            item["unique_id"] = (
                f"{self.api.device_id}"
                f"_{item['entity_type']}"
                f"_{item['name'].lower().replace(' ', '_')}"
            )

        return entity_data

    @staticmethod
    def _build_traffic_entities(traffic: dict[str, Any]) -> list[EntityData]:
        """Create traffic related entities."""

        if not traffic:
            return []

        return [
            {
                "name": "Upload Speed",
                "state": traffic.get("up"),
                "entity_type": "traffic_sensor",
                "icon": "mdi:arrow-up",
                "translation_key": "up_speed",
            },
            {
                "name": "Download Speed",
                "state": traffic.get("down"),
                "entity_type": "traffic_sensor",
                "icon": "mdi:arrow-down",
                "translation_key": "down_speed",
            },
        ]

    @staticmethod
    def _build_connection_entities(connections: dict[str, Any]) -> list[EntityData]:
        """Create connection related entities."""

        if not connections:
            return []

        return [
            {
                "name": "Upload Traffic",
                "state": connections.get("uploadTotal"),
                "entity_type": "total_traffic_sensor",
                "icon": "mdi:tray-arrow-up",
                "translation_key": "up_traffic",
            },
            {
                "name": "Download Traffic",
                "state": connections.get("downloadTotal"),
                "entity_type": "total_traffic_sensor",
                "icon": "mdi:tray-arrow-down",
                "translation_key": "down_traffic",
            },
            {
                "name": "Connection Number",
                "state": len(connections.get("connections", []) or []),
                "entity_type": "connection_sensor",
                "icon": "mdi:transit-connection",
                "translation_key": "connection_number",
            },
        ]

    @staticmethod
    def _build_memory_entities(memory: dict[str, Any]) -> list[EntityData]:
        """Create memory related entities."""

        if not memory:
            return []

        return [
            {
                "name": "Memory Used",
                "state": memory.get("inuse"),
                "entity_type": "memory_sensor",
                "icon": "mdi:memory",
                "translation_key": "memory_used",
            }
        ]

    def _build_fakeip_button(self) -> EntityData:
        """Create FakeIP cache flush button entity."""

        return {
            "name": "Flush FakeIP Cache",
            "entity_type": "fakeip_flush_button",
            "icon": "mdi:broom",
            "translation_key": "flush_cache",
            "action": {
                "method": self.api.async_request,
                "args": ("POST", "cache/fakeip/flush"),
            },
        }

    @staticmethod
    def _build_proxy_entities(proxies: dict[str, Any]) -> list[EntityData]:
        """Create entities for proxy groups."""

        entity_data: list[EntityData] = []
        group_selector_items = ["tfo", "type", "udp", "xudp", "alive", "history"]
        group_sensor_items = group_selector_items + ["all"]

        for item in proxies.get("proxies", {}).values():
            if item.get("type") in ["Selector", "Fallback"]:
                entity_data.append(
                    {
                        "name": item.get("name"),
                        "state": item.get("now"),
                        "entity_type": "proxy_group_selector",
                        "icon": "mdi:network-outline",
                        "options": item.get("all"),
                        "attributes": {
                            k: item[k] for k in group_selector_items if k in item
                        },
                    }
                )
            elif item.get("type") == "URLTest":
                entity_data.append(
                    {
                        "name": item.get("name"),
                        "state": item.get("now"),
                        "entity_type": "proxy_group_sensor",
                        "icon": "mdi:network-outline",
                        "attributes": {
                            k: item[k] for k in group_sensor_items if k in item
                        },
                    }
                )

        return entity_data

    def _build_streaming_entities(self, streaming: dict[str, Any]) -> list[EntityData]:
        """Create streaming detection entities."""

        if not self.streaming_detection or not streaming:
            return []

        entity_data: list[EntityData] = []

        for service, details in streaming.items():
            service_info = SERVICE_TABLE.get(service)
            code_table = service_info.get("code_table", {})
            code = details.get("status_code", 0)
            entity_data.append(
                {
                    "name": service_info.get("name", "Unknown Service"),
                    "state": code_table.get(code, "unknown"),
                    "icon": service_info.get("icon", "mdi:play"),
                    "attributes": details,
                    "options": list(code_table.values()) + ["unknown"],
                    "entity_type": "streaming_detection",
                    "translation_key": service + "_service",
                }
            )

        return entity_data

    def get_data_by_name(self, name: str) -> dict | None:
        """
        Retrieve data by name.
        """
        return next((item for item in self.data if item["name"] == name), None)

    def get_data_by_unique_id(self, unique_id: str) -> dict | None:
        """
        Retrieve data by unique ID.
        """
        return next((item for item in self.data if item["unique_id"] == unique_id), None)
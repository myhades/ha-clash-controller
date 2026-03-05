"""Data coordinator for Clash Controller."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(slots=True)
class ClashEntityData:
    """Structured data model used by entities."""

    name: str | None
    entity_type: str
    state: Any = None
    icon: str | None = None
    translation_key: str | None = None
    attributes: dict[str, Any] | None = None
    options: list[str] | None = None
    action: dict[str, Any] | None = None
    unique_key: str | None = None
    unique_id: str = ""


class ClashControllerCoordinator(DataUpdateCoordinator[list[ClashEntityData]]):
    """A coordinator to fetch data from the Clash API."""

    device: DeviceInfo | None = None

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """
        Initialize the Clash Controller coordinator.
        """
        self.host = config_entry.data["api_url"]
        self.token = config_entry.data["bearer_token"]
        self.allow_unsafe = config_entry.data["allow_unsafe"]
        self.config_entry = config_entry

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

        stored_endpoints = self.config_entry.data.get("available_endpoints")
        available_endpoints = (
            [tuple(item) for item in stored_endpoints] if stored_endpoints else None
        )
        self.api = ClashAPI(
            host=self.host,
            token=self.token,
            allow_unsafe=self.allow_unsafe,
            available_endpoints=available_endpoints,
        )
        self._data_by_name: dict[str, ClashEntityData] = {}
        self._data_by_unique_id: dict[str, ClashEntityData] = {}
        _LOGGER.debug(f"Clash API initialized for coordinator {self.name}")

    async def _get_device(self) -> DeviceInfo:
        """
        Generate a device object.
        """
        version_info = await self.api.get_version()
        device_kwargs = {
            "manufacturer": "Clash",
            "model": version_info.get("meta"),
            "sw_version": version_info.get("version"),
            "identifiers": {(DOMAIN, self.api.device_id)},
        }
        try:
            return DeviceInfo(
                translation_key="clash_instance",
                **device_kwargs,
            )
        except TypeError:
            return DeviceInfo(
                name="Clash Instance",
                **device_kwargs,
            )

    async def _async_update_data(self):
        """
        Fetch data from API endpoint.
        """
        response: dict[str, Any] = {}
        _LOGGER.debug("Start fetching data from Clash.")

        try:
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
            if item.entity_type != "fakeip_flush_button"
        ]
        if not real_entities:
            raise UpdateFailed("Empty response")

        return data

    def _build_entity_data(self, response: dict[str, Any]) -> list[ClashEntityData]:
        """Construct entity descriptions from API response."""

        entity_data: list[ClashEntityData] = []
        entity_data.extend(self._build_traffic_entities(response.get("traffic", {})))
        entity_data.extend(self._build_connection_entities(response.get("connections", {})))
        entity_data.extend(self._build_memory_entities(response.get("memory", {})))
        entity_data.extend(self._build_proxy_entities(response.get("proxies", {})))
        entity_data.extend(self._build_streaming_entities(response.get("streaming", {})))
        entity_data.append(self._build_fakeip_button())

        for item in entity_data:
            id_source = (
                item.unique_key
                or item.name
                or item.translation_key
                or item.entity_type
            )
            item.unique_id = (
                f"{self.api.device_id}"
                f"_{item.entity_type}"
                f"_{id_source.lower().replace(' ', '_')}"
            )

        self._data_by_name = {}
        for item in entity_data:
            if item.name and item.name not in self._data_by_name:
                self._data_by_name[item.name] = item
        self._data_by_unique_id = {item.unique_id: item for item in entity_data}
        return entity_data

    @staticmethod
    def _build_traffic_entities(traffic: dict[str, Any]) -> list[ClashEntityData]:
        """Create traffic related entities."""

        if not traffic:
            return []

        return [
            ClashEntityData(
                name=None,
                state=traffic.get("up"),
                entity_type="traffic_sensor",
                icon="mdi:arrow-up",
                translation_key="up_speed",
                unique_key="upload_speed",
            ),
            ClashEntityData(
                name=None,
                state=traffic.get("down"),
                entity_type="traffic_sensor",
                icon="mdi:arrow-down",
                translation_key="down_speed",
                unique_key="download_speed",
            ),
        ]

    @staticmethod
    def _build_connection_entities(connections: dict[str, Any]) -> list[ClashEntityData]:
        """Create connection related entities."""

        if not connections:
            return []

        return [
            ClashEntityData(
                name=None,
                state=connections.get("uploadTotal"),
                entity_type="total_traffic_sensor",
                icon="mdi:tray-arrow-up",
                translation_key="up_traffic",
                unique_key="upload_traffic",
            ),
            ClashEntityData(
                name=None,
                state=connections.get("downloadTotal"),
                entity_type="total_traffic_sensor",
                icon="mdi:tray-arrow-down",
                translation_key="down_traffic",
                unique_key="download_traffic",
            ),
            ClashEntityData(
                name=None,
                state=len(connections.get("connections", []) or []),
                entity_type="connection_sensor",
                icon="mdi:transit-connection",
                translation_key="connection_number",
                unique_key="connection_number",
            ),
        ]

    @staticmethod
    def _build_memory_entities(memory: dict[str, Any]) -> list[ClashEntityData]:
        """Create memory related entities."""

        if not memory:
            return []

        return [
            ClashEntityData(
                name=None,
                state=memory.get("inuse"),
                entity_type="memory_sensor",
                icon="mdi:memory",
                translation_key="memory_used",
                unique_key="memory_used",
            )
        ]

    def _build_fakeip_button(self) -> ClashEntityData:
        """Create FakeIP cache flush button entity."""

        return ClashEntityData(
            name=None,
            entity_type="fakeip_flush_button",
            icon="mdi:broom",
            translation_key="flush_cache",
            action={
                "method": self.api.async_request,
                "args": ("POST", "cache/fakeip/flush"),
                "kwargs": {"suppress_errors": False},
            },
            unique_key="flush_fakeip_cache",
        )

    @staticmethod
    def _build_proxy_entities(proxies: dict[str, Any]) -> list[ClashEntityData]:
        """Create entities for proxy groups."""

        entity_data: list[ClashEntityData] = []
        group_selector_items = ["tfo", "type", "udp", "xudp", "alive", "history"]
        group_sensor_items = group_selector_items + ["all"]

        for item in proxies.get("proxies", {}).values():
            if item.get("type") in ["Selector", "Fallback"]:
                entity_data.append(
                    ClashEntityData(
                        name=item.get("name", ""),
                        state=item.get("now"),
                        entity_type="proxy_group_selector",
                        icon="mdi:network-outline",
                        options=item.get("all"),
                        attributes={
                            k: item[k] for k in group_selector_items if k in item
                        },
                    )
                )
            elif item.get("type") == "URLTest":
                entity_data.append(
                    ClashEntityData(
                        name=item.get("name", ""),
                        state=item.get("now"),
                        entity_type="proxy_group_sensor",
                        icon="mdi:network-outline",
                        attributes={
                            k: item[k] for k in group_sensor_items if k in item
                        },
                    )
                )

        return entity_data

    def _build_streaming_entities(self, streaming: dict[str, Any]) -> list[ClashEntityData]:
        """Create streaming detection entities."""

        if not self.streaming_detection or not streaming:
            return []

        entity_data: list[ClashEntityData] = []

        for service, details in streaming.items():
            service_info = SERVICE_TABLE.get(service)
            code_table = service_info.get("code_table", {})
            code = details.get("status_code", 0)
            entity_data.append(
                ClashEntityData(
                    name=None,
                    state=code_table.get(code, "unknown"),
                    icon=service_info.get("icon", "mdi:play"),
                    attributes=details,
                    options=list(code_table.values()) + ["unknown"],
                    entity_type="streaming_detection",
                    translation_key=service + "_service",
                    unique_key=(service_info.get("name", service)).lower().replace(" ", "_"),
                )
            )

        return entity_data

    def get_data_by_name(self, name: str) -> ClashEntityData | None:
        """
        Retrieve data by name.
        """
        return self._data_by_name.get(name)

    def get_data_by_unique_id(self, unique_id: str) -> ClashEntityData | None:
        """
        Retrieve data by unique ID.
        """
        return self._data_by_unique_id.get(unique_id)

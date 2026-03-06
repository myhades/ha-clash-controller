"""Data coordinator for Clash Controller."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
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
DEFAULT_HEALTHCHECK_TIMEOUT_MS = 5000
CORE_DATA_KEYS = frozenset(
    {
        "traffic",
        "memory",
        "connections",
        "proxies",
        "configs",
        "providers_proxies",
        "providers_rules",
    }
)


@dataclass(slots=True)
class ClashEntityData:
    """Structured data model used by entities."""

    name: str | None
    entity_type: str
    state: Any = None
    icon: str | None = None
    translation_key: str | None = None
    translation_placeholders: dict[str, str] | None = None
    entity_category: EntityCategory | None = None
    enabled_default: bool | None = None
    attributes: dict[str, Any] | None = None
    options: list[str] | None = None
    action: dict[str, Any] | None = None
    unique_key: str | None = None
    unique_id: str = ""


class ClashControllerCoordinator(DataUpdateCoordinator[list[ClashEntityData]]):
    """A coordinator to fetch data from the Clash API."""

    device: DeviceInfo | None = None

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the Clash Controller coordinator."""
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
        stored_capabilities = self.config_entry.data.get("capabilities")
        capabilities = (
            dict(stored_capabilities) if isinstance(stored_capabilities, dict) else None
        )
        self.api = ClashAPI(
            host=self.host,
            token=self.token,
            allow_unsafe=self.allow_unsafe,
            available_endpoints=available_endpoints,
            capabilities=capabilities,
        )
        self._data_by_name: dict[str, ClashEntityData] = {}
        self._data_by_unique_id: dict[str, ClashEntityData] = {}
        _LOGGER.debug(f"Clash API initialized for coordinator {self.name}")

    async def _get_device(self) -> DeviceInfo:
        """Generate a device object."""
        version_info = await self.api.get_version()
        model = version_info.get("model", version_info.get("meta", "Unknown Core"))
        lowered_model = model.lower()
        manufacturer = (
            "MetaCubeX"
            if ("mihomo" in lowered_model or "meta" in lowered_model)
            else "Clash"
        )
        device_kwargs = {
            "manufacturer": manufacturer,
            "model": model,
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
        """Fetch data from API endpoint."""
        response: dict[str, Any] = {}
        _LOGGER.debug("Start fetching data from Clash.")

        try:
            response = await self.api.fetch_data(
                streaming_detection=self.streaming_detection,
                suppress_errors=True,
            )
            if not CORE_DATA_KEYS.intersection(response):
                raise UpdateFailed("No data returned from Clash core.")
            if not self.device:
                self.device = await self._get_device()
        except Exception as err:
            raise UpdateFailed(err) from err

        data = self._build_entity_data(response)
        real_entities = [
            item for item in data if item.entity_type not in {"fakeip_flush_button", "dns_flush_button"}
        ]
        if not real_entities:
            raise UpdateFailed("Empty response")

        return data

    @staticmethod
    def _slugify(value: str) -> str:
        return re.sub(r"[^a-z0-9_]+", "_", value.lower().replace(" ", "_")).strip("_")

    def _build_entity_data(self, response: dict[str, Any]) -> list[ClashEntityData]:
        """Construct entity descriptions from API response."""
        capabilities = self.api.capabilities or {}
        entity_data: list[ClashEntityData] = []

        if capabilities.get("traffic"):
            entity_data.extend(self._build_traffic_entities(response.get("traffic", {})))
        if capabilities.get("connections"):
            entity_data.extend(
                self._build_connection_entities(response.get("connections", {}))
            )
        if capabilities.get("memory"):
            entity_data.extend(self._build_memory_entities(response.get("memory", {})))
        if capabilities.get("proxies"):
            entity_data.extend(self._build_proxy_entities(response.get("proxies", {})))
        if capabilities.get("configs"):
            entity_data.extend(self._build_config_entities(response.get("configs", {})))
        if capabilities.get("providers_proxies") or capabilities.get("providers_rules"):
            entity_data.extend(
                self._build_provider_entities(
                    response.get("providers_proxies", {}),
                    response.get("providers_rules", {}),
                    provider_healthcheck_enabled=capabilities.get(
                        "provider_healthcheck", False
                    ),
                )
            )
        entity_data.extend(self._build_streaming_entities(response.get("streaming", {})))

        if capabilities.get("cache_fakeip_flush"):
            entity_data.append(self._build_fakeip_button())
        if capabilities.get("cache_dns_flush"):
            entity_data.append(self._build_dns_flush_button())

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
    def _build_connection_entities(
        connections: dict[str, Any],
    ) -> list[ClashEntityData]:
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
            icon="mdi:cached",
            translation_key="flush_cache",
            entity_category=EntityCategory.DIAGNOSTIC,
            action={
                "method": self.api.async_request,
                "args": ("POST", "cache/fakeip/flush"),
                "kwargs": {"suppress_errors": False},
            },
            unique_key="flush_fakeip_cache",
        )

    def _build_dns_flush_button(self) -> ClashEntityData:
        """Create DNS cache flush button entity."""
        return ClashEntityData(
            name=None,
            entity_type="dns_flush_button",
            icon="mdi:cached",
            translation_key="flush_dns_cache",
            entity_category=EntityCategory.DIAGNOSTIC,
            action={
                "method": self.api.async_request,
                "args": ("POST", "cache/dns/flush"),
                "kwargs": {"suppress_errors": False},
            },
            unique_key="flush_dns_cache",
        )

    @staticmethod
    def _build_proxy_entities(proxies: dict[str, Any]) -> list[ClashEntityData]:
        """Create entities for proxy groups."""
        entity_data: list[ClashEntityData] = []
        group_selector_items = ["tfo", "type", "udp", "xudp", "alive", "history"]
        group_sensor_items = group_selector_items + ["all"]
        urltest_items = group_sensor_items + ["expectedStatus", "testUrl", "lastTestTime"]

        for item in proxies.get("proxies", {}).values():
            if item.get("type") in ["Selector", "Fallback"]:
                entity_data.append(
                    ClashEntityData(
                        name=item.get("name", ""),
                        state=item.get("now"),
                        entity_type="proxy_group_selector",
                        icon="mdi:network-outline",
                        options=item.get("all"),
                        attributes={k: item[k] for k in group_selector_items if k in item},
                    )
                )
            elif item.get("type") == "URLTest":
                fixed_value = item.get("fixed")
                supports_fixed = "fixed" in item
                attributes = {k: item[k] for k in urltest_items if k in item}
                if supports_fixed:
                    attributes["fixed"] = bool(fixed_value)
                entity_data.append(
                    ClashEntityData(
                        name=item.get("name", ""),
                        state=item.get("now"),
                        entity_type=(
                            "proxy_group_selector" if supports_fixed else "proxy_group_sensor"
                        ),
                        icon="mdi:network-outline",
                        options=item.get("all") if supports_fixed else None,
                        attributes=attributes,
                    )
                )

        return entity_data

    def _build_config_entities(self, configs: dict[str, Any]) -> list[ClashEntityData]:
        """Create entities for mutable config values."""
        if not configs:
            return []

        mode = configs.get("mode")
        if not mode:
            return []

        mode_options = configs.get("mode-list")
        if not isinstance(mode_options, list) or not mode_options:
            mode_options = ["rule", "global", "direct"]
        if mode not in mode_options:
            mode_options = [*mode_options, mode]

        return [
            ClashEntityData(
                name=None,
                state=mode,
                options=mode_options,
                entity_type="core_mode_selector",
                icon="mdi:tune",
                translation_key="core_mode",
                unique_key="core_mode",
            )
        ]

    def _build_provider_entities(
        self,
        providers_proxies: dict[str, Any],
        providers_rules: dict[str, Any],
        provider_healthcheck_enabled: bool,
    ) -> list[ClashEntityData]:
        """Create entities for provider metrics and actions."""
        def _safe_timeout(value: Any) -> int:
            try:
                timeout = int(value)
            except (TypeError, ValueError):
                return DEFAULT_HEALTHCHECK_TIMEOUT_MS
            return timeout if timeout > 0 else DEFAULT_HEALTHCHECK_TIMEOUT_MS

        proxy_provider_map = (
            providers_proxies.get("providers", {})
            if isinstance(providers_proxies, dict)
            else {}
        )
        rule_provider_map = (
            providers_rules.get("providers", {})
            if isinstance(providers_rules, dict)
            else {}
        )

        if not isinstance(proxy_provider_map, dict):
            proxy_provider_map = {}
        if not isinstance(rule_provider_map, dict):
            rule_provider_map = {}

        entity_data: list[ClashEntityData] = [
            ClashEntityData(
                name=None,
                state=len(proxy_provider_map),
                entity_type="provider_count_sensor",
                icon="mdi:server-outline",
                translation_key="proxy_provider_count",
                entity_category=EntityCategory.DIAGNOSTIC,
                unique_key="proxy_provider_count",
            ),
            ClashEntityData(
                name=None,
                state=len(rule_provider_map),
                entity_type="provider_count_sensor",
                icon="mdi:file-document-outline",
                translation_key="rule_provider_count",
                entity_category=EntityCategory.DIAGNOSTIC,
                unique_key="rule_provider_count",
            ),
        ]

        if provider_healthcheck_enabled:
            for provider_name, provider_detail in proxy_provider_map.items():
                encoded = quote(provider_name, safe="")
                slug = self._slugify(provider_name) or encoded.lower().replace("%", "_")
                translation_key = (
                    "default_proxy_group_healthcheck"
                    if provider_name.strip().lower() == "default"
                    else "provider_healthcheck"
                )
                placeholders = (
                    None
                    if translation_key == "default_proxy_group_healthcheck"
                    else {"provider_name": provider_name}
                )
                if not isinstance(provider_detail, dict):
                    provider_detail = {}
                health_check_config = provider_detail.get("healthCheck")
                if not isinstance(health_check_config, dict):
                    health_check_config = {}

                test_url = provider_detail.get("testUrl")
                if not isinstance(test_url, str) or not test_url.strip():
                    test_url = health_check_config.get("url")
                if not isinstance(test_url, str) or not test_url.strip():
                    test_url = "http://www.gstatic.com/generate_204"

                timeout_value = health_check_config.get("timeout")
                if timeout_value is None:
                    timeout_value = provider_detail.get("timeout")
                timeout = _safe_timeout(timeout_value)
                common_params = {"url": test_url, "timeout": timeout}
                action = {
                    "method": self.api.async_request,
                    "args": ("GET", f"providers/proxies/{encoded}/healthcheck"),
                    "kwargs": {"params": common_params, "suppress_errors": False},
                }
                entity_data.append(
                    ClashEntityData(
                        name=None,
                        entity_type="provider_healthcheck_button",
                        icon="mdi:stethoscope",
                        translation_key=translation_key,
                        translation_placeholders=placeholders,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        enabled_default=False,
                        action=action,
                        unique_key=f"provider_healthcheck_{slug}",
                    )
                )

        return entity_data

    def _build_streaming_entities(
        self,
        streaming: dict[str, Any],
    ) -> list[ClashEntityData]:
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
                    unique_key=(service_info.get("name", service))
                    .lower()
                    .replace(" ", "_"),
                )
            )

        return entity_data

    def get_data_by_name(self, name: str) -> ClashEntityData | None:
        """Retrieve data by name."""
        return self._data_by_name.get(name)

    def get_data_by_unique_id(self, unique_id: str) -> ClashEntityData | None:
        """Retrieve data by unique ID."""
        return self._data_by_unique_id.get(unique_id)

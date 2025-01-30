"""Data coordinator for Clash Controller."""

from datetime import timedelta
from typing import List, Dict, Optional
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ClashAPI
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class ClashControllerCoordinator(DataUpdateCoordinator):
    """A coordinator to fetch data from the Clash API."""

    device: Optional[DeviceInfo] = None

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

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
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
        isConnected = False
        _LOGGER.debug(f"Start fetching data from Clash.")

        try:
            isConnected = await self.api.connected(suppress_errors=False)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        
        if isConnected:
            response = await self.api.fetch_data()
            if not self.device:
                self.device = await self._get_device()

        entity_data = [
            {
                "name": "Upload Speed",
                "state": response.get("traffic").get("up"),
                "entity_type": "traffic_sensor",
                "icon": "mdi:arrow-up"
            },
            {
                "name": "Download Speed",
                "state": response.get("traffic").get("down"),
                "entity_type": "traffic_sensor",
                "icon": "mdi:arrow-down",
            },
            {
                "name": "Upload Traffic",
                "state": response.get("connections").get("uploadTotal"),
                "entity_type": "total_traffic_sensor",
                "icon": "mdi:tray-arrow-up"
            },
            {
                "name": "Download Traffic",
                "state": response.get("connections").get("downloadTotal"),
                "entity_type": "total_traffic_sensor",
                "icon": "mdi:tray-arrow-down",
            },
            {
                "name": "Memory Used",
                "state": response.get("memory").get("inuse"),
                "entity_type": "memory_sensor",
                "icon": "mdi:memory",
            },
            {
                "name": "Connection Number",
                "state": len(response.get("connections").get("connections")),
                "entity_type": "connection_sensor",
                "icon": "mdi:transit-connection",
            },
        ]
        for item in entity_data:
            item["unique_id"] = f"{self.api.device_id}_{item['name'].lower().replace(' ', '_')}"

        return entity_data
    
    def get_data_by_name(self, name: str) -> dict | None:
        """
        Retrieve data by name.
        """
        return next((item for item in self.data if item["name"] == name), None)
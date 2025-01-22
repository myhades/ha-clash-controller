"""Data coordinator for Clash Controller."""

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ClashAPI, Device
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class ClashAPIData:
    """Class to hold api data."""

    devices: list[Device]

class ClashControllerCoordinator(DataUpdateCoordinator):
    """A coordinator to fetch data from the Clash API."""

    data: ClashAPIData

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

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            update_method=self.async_update_data,
            update_interval=timedelta(seconds=self.poll_interval),
        )

        # Initialise API
        self.api = ClashAPI(host=self.host, token=self.token, allow_unsafe=self.allow_unsafe)
        _LOGGER.debug(f"Clash API initialized for coordinator {self.name}")

    async def async_update_data(self):
        """
        Fetch data from API endpoint.
        """
        
        _LOGGER.debug(f"Start fetching data from Clash.")
        devices: dict[str, Device] = {}

        try:
            if await self.api.connected(suppress_errors=False):
                await self.api.fetch_data()
                # devices = await self.hass.async_add_executor_job(self.api.get_devices)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        return ClashAPIData(devices)
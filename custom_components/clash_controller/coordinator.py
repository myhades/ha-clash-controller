"""Data coordinator for Clash Controller."""

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    # api_url,
    # bearer_token,
    # use_ssl,
    # allow_unsafe,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ClashAPI, Device
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class ClashAPIData:
    """Class to hold api data."""

    controller_name: str
    devices: list[Device]

class ClashControllerCoordinator(DataUpdateCoordinator):
    """A coordinator to fetch data from the Clash API."""

    data: ClashAPIData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """
        Initialize the Clash Controller coordinator.
        """
        self.host = config_entry.data[api_url]
        self.token = config_entry.data[bearer_token]
        self.use_ssl = config_entry.data[use_ssl]
        self.allow_unsafe = config_entry.data[allow_unsafe]

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
        self.api = ClashAPI(
            host=self.host, token=self.token, use_ssl=self.use_ssl, allow_unsafe=self.allow_unsafe
        )

    async def async_update_data(self):
        """
        Fetch data from API endpoint.
        """
        try:
            if not self.api.connected:
                await self.hass.async_add_executor_job(self.api.connect)
            devices = await self.hass.async_add_executor_job(self.api.get_devices)
        # TODO: Implement error detections
        # except APIAuthError as err:
        #     _LOGGER.error(err)
        #     raise UpdateFailed(err) from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        # What is returned here is stored in self.data by the DataUpdateCoordinator
        return ClashAPIData(self.api.controller_name, devices)

    def get_device_by_id(self, device_id: int) -> Device | None:
        """Return device by device id."""
        try:
            return [
                device
                for device in self.data.devices
                if device.device_id == device_id
            ][0]
        except IndexError:
            return None
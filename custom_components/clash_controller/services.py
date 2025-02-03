"""Services for the Clash Controller."""

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    REBOOT_CORE_SERVICE_NAME,
    GET_CONNECTION_SERVICE_NAME,
    GET_GROUP_LATENCY_SERVICE_NAME,
    GET_NODE_LATENCY_SERVICE_NAME,
    GET_RULE_SERVICE_NAME,
    DELETE_CONNECTION_SERVICE_NAME,
)
from .coordinator import ClashControllerCoordinator

HOST_KEYWORD = "host"
SRC_HOSTNAME_KEYWORD = "src_hostname"
DES_HOSTNAME_KEYWORD = "des_hostname"

REBOOT_CORE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
    }
)

GET_CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(HOST_KEYWORD): cv.string,
        vol.Optional(SRC_HOSTNAME_KEYWORD): cv.string,
        vol.Optional(DES_HOSTNAME_KEYWORD): cv.string,
    }
)

class ClashServicesSetup:
    """Class to handle Integration Services."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.coordinator: ClashControllerCoordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator
        self.setup_services()

    def setup_services(self):
        """Initialise the services."""
        self.hass.services.async_register(
            DOMAIN,
            REBOOT_CORE_SERVICE_NAME,
            self.async_reboot_core_service,
            schema=REBOOT_CORE_SERVICE_SCHEMA
        )
        self.hass.services.async_register(
            DOMAIN,
            GET_CONNECTION_SERVICE_NAME,
            self.async_get_connection_service,
            schema=GET_CONNECTION_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    def _get_coordinator(self, device_id: str) -> None:
        """Get the corresponding coordinator with given device_id."""
        
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get(device_id)

        if not device:
            raise HomeAssistantError(f"Device with ID {device_id} not found")
        config_entry_id = next(iter(device.config_entries), None)

        if not config_entry_id:
            raise HomeAssistantError(f"Device {device_id} is not linked to any config entry")

        coordinator: ClashControllerCoordinator = self.hass.data[DOMAIN][config_entry_id].coordinator

        return coordinator

    async def async_reboot_core_service(self, service_call: ServiceCall) -> None:
        """Execute service call for core reboot."""

        coordinator = self._get_coordinator(service_call.data[CONF_DEVICE_ID])
        
        try:
            await coordinator.api.async_request("POST", "core/restart")
        except Exception as err:
            raise HomeAssistantError(f"Error rebooting core: {err}") from err

    async def async_get_connection_service(self, service_call: ServiceCall) -> None:
        """Execute service call for core reboot."""

        coordinator = self._get_coordinator(service_call.data[CONF_DEVICE_ID])

        def parse_filter(key):
            value_str = service_call.data.get(key)
            return {item.strip() for item in value_str.split(",") if item.strip()} if value_str else None

        def filter_connection(conn):
            meta = conn.get("metadata", {})
            host = meta.get("host", "").lower()
            src_ip = meta.get("sourceIP", "").lower()
            des_ip = meta.get("destinationIP", "").lower()
            if hosts and not any(h in host for h in hosts):
                return False
            if src_hosts and not any(h in src_ip for h in src_hosts):
                return False
            if des_hosts and not any(h in des_ip for h in des_hosts):
                return False
            return True

        try:
            response = await coordinator.api.async_request("GET", "connections")
            if response is None:
                raise HomeAssistantError("Empty response from API.")
        except Exception as err:
            raise HomeAssistantError(f"Error getting connections: {err}") from err

        hosts = parse_filter(HOST_KEYWORD)
        src_hosts = parse_filter(SRC_HOSTNAME_KEYWORD)
        des_hosts = parse_filter(DES_HOSTNAME_KEYWORD)

        connections = response.get("connections", [])
        filtered_connections = [conn for conn in connections if filter_connection(conn)]

        return {
            "connection_number": len(filtered_connections),
            "connections": filtered_connections,
        }


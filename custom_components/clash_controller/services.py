"""Services for the Clash Controller."""

import asyncio
import json
from urllib.parse import quote
import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    REBOOT_CORE_SERVICE_NAME,
    FILTER_CONNECTION_SERVICE_NAME,
    GET_LATENCY_SERVICE_NAME,
    DNS_QUERY_SERVICE_NAME,
    GET_RULE_SERVICE_NAME,
    API_CALL_SERVICE_NAME,
)
from .coordinator import ClashControllerCoordinator

HOST_KEYWORD = "host"
SRC_HOSTNAME_KEYWORD = "src_hostname"
DES_HOSTNAME_KEYWORD = "des_hostname"
CLOSE_CONNECTION = "close_connection"

GROUP_NAME = "group"
NODE_NAME = "node"
TEST_URL = "url"
TEST_TIMEOUT = "timeout"

DOMAIN_NAME = "domain_name"
RECORD_TYPE = "record_type"

RULE_TYPE = "rule_type"
RULE_PAYLOAD = "rule_payload"
RULE_PROXY = "rule_proxy"

API_ENDPOINT = "api_endpoint"
API_METHOD = "api_method"
API_PARAMS = "api_params"
API_DATA = "api_data"
API_READ_LINE = "read_line"

REBOOT_CORE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
    }
)

FILTER_CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(CLOSE_CONNECTION): cv.boolean,
        vol.Optional(HOST_KEYWORD): cv.string,
        vol.Optional(SRC_HOSTNAME_KEYWORD): cv.string,
        vol.Optional(DES_HOSTNAME_KEYWORD): cv.string,
    }
)

GET_LATENCY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(GROUP_NAME): cv.string,
        vol.Optional(NODE_NAME): cv.string,
        vol.Optional(TEST_URL): cv.string,
        vol.Optional(TEST_TIMEOUT): cv.positive_int,
    }
)

DNS_QUERY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(DOMAIN_NAME): cv.string,
        vol.Optional(RECORD_TYPE): cv.string,
    }
)

GET_RULE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(RULE_TYPE): cv.string,
        vol.Optional(RULE_PAYLOAD): cv.string,
        vol.Optional(RULE_PROXY): cv.string,
    }
)

API_CALL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(API_ENDPOINT): cv.string,
        vol.Required(API_METHOD): cv.string,
        vol.Optional(API_PARAMS): cv.string,
        vol.Optional(API_DATA): cv.string,
        vol.Optional(API_READ_LINE): cv.positive_int,
    }
)

class ClashServicesSetup:
    """Class to handle Integration Services."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.setup_services()

    def setup_services(self):
        """Initialise the services."""

        def _register(
            service_name: str,
            handler,
            schema: vol.Schema,
            supports_response: SupportsResponse | None = None,
        ) -> None:
            if self.hass.services.has_service(DOMAIN, service_name):
                return
            kwargs = {"schema": schema}
            if supports_response is not None:
                kwargs["supports_response"] = supports_response
            self.hass.services.async_register(
                DOMAIN,
                service_name,
                handler,
                **kwargs,
            )

        _register(
            REBOOT_CORE_SERVICE_NAME,
            self.async_reboot_core_service,
            REBOOT_CORE_SERVICE_SCHEMA,
        )
        _register(
            FILTER_CONNECTION_SERVICE_NAME,
            self.async_filter_connection_service,
            FILTER_CONNECTION_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        _register(
            GET_LATENCY_SERVICE_NAME,
            self.async_get_latency_service,
            GET_LATENCY_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        _register(
            DNS_QUERY_SERVICE_NAME,
            self.async_dns_query_service,
            DNS_QUERY_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        _register(
            GET_RULE_SERVICE_NAME,
            self.async_get_rule_service,
            GET_RULE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        _register(
            API_CALL_SERVICE_NAME,
            self.async_api_call_service,
            API_CALL_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    def _get_coordinator(self, device_id: str) -> ClashControllerCoordinator:
        """Get the corresponding coordinator with given device_id."""

        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get(device_id)
        if not device:
            raise HomeAssistantError("Invalid device id.")
        config_entry_id = next(iter(device.config_entries), None)
        if not config_entry_id:
            raise HomeAssistantError("Invalid device id.")
        runtime_data = self.hass.data.get(DOMAIN, {}).get(config_entry_id)
        if not runtime_data:
            raise HomeAssistantError("Invalid device id.")
        return runtime_data.coordinator

    async def async_reboot_core_service(self, service_call: ServiceCall) -> None:
        """Execute service call for rebooting core."""

        coordinator = self._get_coordinator(service_call.data[CONF_DEVICE_ID])
        
        try:
            await coordinator.api.async_request("POST", "restart", suppress_errors=False)
        except Exception as err:
            raise HomeAssistantError(f"Error rebooting core: {err}") from err

    async def async_filter_connection_service(self, service_call: ServiceCall) -> dict:
        """Execute service call for filtering connection."""

        coordinator = self._get_coordinator(service_call.data[CONF_DEVICE_ID])

        def parse_filter(key):
            value_str = service_call.data.get(key)
            return (
                {item.strip().lower() for item in value_str.split(",") if item.strip()}
                if value_str
                else None
            )

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

        async def delete_connection(conn_id):
            async with semaphore:
                await coordinator.api.async_request(
                    "DELETE",
                    f"connections/{conn_id}",
                    suppress_errors=False,
                )

        hosts = parse_filter(HOST_KEYWORD)
        src_hosts = parse_filter(SRC_HOSTNAME_KEYWORD)
        des_hosts = parse_filter(DES_HOSTNAME_KEYWORD)
        close_connection = service_call.data.get(CLOSE_CONNECTION, False)

        try:
            response = await coordinator.api.async_request("GET", "connections", suppress_errors=False)
        except Exception as err:
            raise HomeAssistantError(f"Error getting connections: {err}") from err

        connections = response.get("connections", []) or []
        filtered_connections = [conn for conn in connections if filter_connection(conn)]

        service_response = {
            "connection_number": len(filtered_connections),
            "connection_closed": close_connection,
            "connections": filtered_connections,
        }

        if not close_connection:
            return service_response

        try:
            if hosts or src_hosts or des_hosts:
                semaphore = asyncio.Semaphore(coordinator.concurrent_connections)
                await asyncio.gather(*[
                    delete_connection(conn["id"]) for conn in filtered_connections
                ])
            else:
                await coordinator.api.async_request(
                    "DELETE",
                    "connections",
                    suppress_errors=False,
                )
        except Exception as err:
            raise HomeAssistantError(f"Error closing connection: {err}") from err

        return service_response

    async def async_get_latency_service(self, service_call: ServiceCall) -> dict:
        """Execute service call for getting latency."""

        coordinator = self._get_coordinator(service_call.data[CONF_DEVICE_ID])

        def sort_group(data: dict) -> dict:
            if not data:
                return {"fastest_node": None,"latency": []}
            sorted_items = sorted(data.items(), key=lambda x: x[1])
            return {
                "fastest_node": sorted_items[0][0],
                "latency": sorted_items
            }
        
        group = service_call.data.get(GROUP_NAME, "").strip()
        node = service_call.data.get(NODE_NAME, "").strip()
        url = service_call.data.get(TEST_URL, "http://www.gstatic.com/generate_204")
        timeout = service_call.data.get(TEST_TIMEOUT, 5000)
        
        if bool(group) ^ bool(node) is False:
            raise HomeAssistantError("Exactly one of the group or node should be provided.")

        try:
            response = await coordinator.api.async_request(
                method="GET",
                endpoint=(
                    f"group/{quote(group, safe='')}/delay"
                    if group
                    else f"proxies/{quote(node, safe='')}/delay"
                ),
                params={"url": url,"timeout": timeout},
                suppress_errors=False
            )
        except Exception as err:
            raise HomeAssistantError(f"Error getting latency: {err}") from err
        
        if group:
            return sort_group(response)
        else:
            return {"latency": {node: response.get("delay", [])}}

    async def async_dns_query_service(self, service_call: ServiceCall) -> dict:
        """Execute service call for performing a DNS query."""

        coordinator = self._get_coordinator(service_call.data[CONF_DEVICE_ID])

        domain_name = service_call.data.get(DOMAIN_NAME, "")
        record_type = service_call.data.get(RECORD_TYPE, "A")

        try:
            return await coordinator.api.async_request(
                method="GET",
                endpoint="dns/query",
                params={"name": domain_name,"type": record_type},
                suppress_errors=False
            )
        except Exception as err:
            raise HomeAssistantError(f"Error performing DNS query: {err}") from err

    async def async_get_rule_service(self, service_call: ServiceCall) -> dict:
        """Execute service call for performing a DNS query."""

        coordinator = self._get_coordinator(service_call.data[CONF_DEVICE_ID])

        def parse_filter(key):
            value_str = service_call.data.get(key)
            return (
                {item.strip().lower() for item in value_str.split(",") if item.strip()}
                if value_str
                else None
            )

        def filter_rule(rule):
            rule_type = rule.get("type", "").lower()
            rule_payload = rule.get("payload", "").lower()
            rule_proxy = rule.get("proxy", "").lower()
            if rule_types and not any(h in rule_type for h in rule_types):
                return False
            if rule_payloads and not any(h in rule_payload for h in rule_payloads):
                return False
            if rule_proxys and not any(h in rule_proxy for h in rule_proxys):
                return False
            return True

        rule_types = parse_filter(RULE_TYPE)
        rule_payloads = parse_filter(RULE_PAYLOAD)
        rule_proxys = parse_filter(RULE_PROXY)

        try:
            response = await coordinator.api.async_request(method="GET",endpoint="rules",suppress_errors=False)
        except Exception as err:
            raise HomeAssistantError(f"Error getting rules: {err}") from err

        rules = response.get("rules", [])
        filtered_rules = [rule for rule in rules if filter_rule(rule)]
        service_response = {"rules": filtered_rules}

        return service_response

    async def async_api_call_service(self, service_call: ServiceCall) -> None:
        """Execute service call for calling API."""

        coordinator = self._get_coordinator(service_call.data[CONF_DEVICE_ID])

        def to_dict(input_str: str):
            try:
                data = json.loads(input_str)
                if isinstance(data, dict):
                    return data
                else:
                    return {}
            except json.JSONDecodeError:
                return {}

        method = service_call.data.get(API_METHOD, "GET")
        endpoint = service_call.data.get(API_ENDPOINT, "")
        read_line = service_call.data.get(API_READ_LINE, 0)
        params = to_dict(service_call.data.get(API_PARAMS, "") or "")
        data = to_dict(service_call.data.get(API_DATA, "") or "")
        
        try:
            response = await coordinator.api.async_request(
                method=method,
                endpoint=endpoint,
                params=params,
                json_data=data,
                read_line=read_line,
                suppress_errors=False
            )
        except Exception as err:
            raise HomeAssistantError(f"Error performing API call: {err}") from err
        
        return {"response": response}



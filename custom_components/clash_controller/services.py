"""Services for the Clash Controller integration."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Final
from urllib.parse import quote

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import (
    DOMAIN,
    REBOOT_CORE_SERVICE_NAME,
    FILTER_CONNECTION_SERVICE_NAME,
    GET_LATENCY_SERVICE_NAME,
    DNS_QUERY_SERVICE_NAME,
    GET_RULE_SERVICE_NAME,
    API_CALL_SERVICE_NAME,
)

# --- 参数常量定义  ---
ATTR_HOST: Final = "host"
ATTR_SRC_HOSTNAME: Final = "src_hostname"
ATTR_DES_HOSTNAME: Final = "des_hostname"
ATTR_CLOSE_CONNECTION: Final = "close_connection"
ATTR_GROUP: Final = "group"
ATTR_NODE: Final = "node"
ATTR_URL: Final = "url"
ATTR_TIMEOUT: Final = "timeout"
ATTR_DOMAIN_NAME: Final = "domain_name"
ATTR_RECORD_TYPE: Final = "record_type"
ATTR_RULE_TYPE: Final = "rule_type"
ATTR_RULE_PAYLOAD: Final = "rule_payload"
ATTR_RULE_PROXY: Final = "rule_proxy"
ATTR_API_ENDPOINT: Final = "api_endpoint"
ATTR_API_METHOD: Final = "api_method"
ATTR_API_PARAMS: Final = "api_params"
ATTR_API_DATA: Final = "api_data"
ATTR_READ_LINE: Final = "read_line"

# --- 校验架构 (Schemas) ---
REBOOT_CORE_SERVICE_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID): cv.string,
})

FILTER_CONNECTION_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Optional(ATTR_CLOSE_CONNECTION, default=False): cv.boolean,
    vol.Optional(ATTR_HOST): cv.string,
    vol.Optional(ATTR_SRC_HOSTNAME): cv.string,
    vol.Optional(ATTR_DES_HOSTNAME): cv.string,
})

GET_LATENCY_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Optional(ATTR_GROUP): cv.string,
    vol.Optional(ATTR_NODE): cv.string,
    vol.Optional(ATTR_URL, default="http://www.gstatic.com/generate_204"): cv.string,
    vol.Optional(ATTR_TIMEOUT, default=5000): cv.positive_int,
})

DNS_QUERY_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Required(ATTR_DOMAIN_NAME): cv.string,
    vol.Optional(ATTR_RECORD_TYPE, default="A"): cv.string,
})

GET_RULE_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Optional(ATTR_RULE_TYPE): cv.string,
    vol.Optional(ATTR_RULE_PAYLOAD): cv.string,
    vol.Optional(ATTR_RULE_PROXY): cv.string,
})

API_CALL_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Required(ATTR_API_ENDPOINT): cv.string,
    vol.Required(ATTR_API_METHOD): cv.string,
    vol.Optional(ATTR_API_PARAMS): cv.string,
    vol.Optional(ATTR_API_DATA): cv.string,
    vol.Optional(ATTR_READ_LINE): cv.positive_int,
})

async def async_setup_services(hass: HomeAssistant) -> None:
    """注册集成服务。此函数在 __init__.py 中被调用。"""

    def _get_coordinator(device_id: str) -> Any:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(device_id)
        if not device:
            raise HomeAssistantError(f"未找到 ID 为 {device_id} 的设备")
        
        entry_id = next(iter(device.config_entries), None)
        if not entry_id:
            raise HomeAssistantError(f"设备 {device_id} 没有关联的配置条目")
            
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry or not hasattr(entry, "runtime_data"):
            raise HomeAssistantError(f"配置条目 {entry_id} 尚未就绪")
            
        return entry.runtime_data.coordinator

    def parse_filter_list(value: str | None) -> set[str] | None:
        if not value:
            return None
        return {item.strip().lower() for item in value.split(",") if item.strip()}

    def to_dict(input_val: Any) -> dict:
        if isinstance(input_val, dict):
            return input_val
        if not input_val or not isinstance(input_val, str):
            return {}
        try:
            data = json.loads(input_val)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    # --- 处理器定义 ---

    async def handle_reboot_core(call: ServiceCall) -> None:
        coordinator = _get_coordinator(call.data[CONF_DEVICE_ID])
        await coordinator.api.async_request("POST", "restart", suppress_errors=False)

    async def handle_filter_connection(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(call.data[CONF_DEVICE_ID])
        hosts = parse_filter_list(call.data.get(ATTR_HOST))
        src_hosts = parse_filter_list(call.data.get(ATTR_SRC_HOSTNAME))
        des_hosts = parse_filter_list(call.data.get(ATTR_DES_HOSTNAME))
        close_connection = call.data[ATTR_CLOSE_CONNECTION]

        response = await coordinator.api.async_request("GET", "connections", suppress_errors=False)
        connections = response.get("connections", []) or []
        
        filtered = [
            c for c in connections if 
            (not hosts or any(h in c.get("metadata", {}).get("host", "").lower() for h in hosts)) and
            (not src_hosts or any(sh in c.get("metadata", {}).get("sourceIP", "").lower() for sh in src_hosts)) and
            (not des_hosts or any(dh in c.get("metadata", {}).get("destinationIP", "").lower() for dh in des_hosts))
        ]

        if close_connection and filtered:
            if hosts or src_hosts or des_hosts:
                semaphore = asyncio.Semaphore(5)
                async def delete_conn(cid):
                    async with semaphore:
                        await coordinator.api.async_request("DELETE", f"connections/{cid}")
                await asyncio.gather(*[delete_conn(c["id"]) for c in filtered], return_exceptions=True)
            else:
                await coordinator.api.async_request("DELETE", "connections", suppress_errors=False)

        return {
            "connection_number": len(filtered),
            "connection_closed": close_connection,
            "connections": filtered[:100],
        }

    async def handle_get_latency(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(call.data[CONF_DEVICE_ID])
        group = call.data.get(ATTR_GROUP, "").strip()
        node = call.data.get(ATTR_NODE, "").strip()
        endpoint = f"group/{quote(group)}/delay" if group else f"proxies/{quote(node)}/delay"
        
        response = await coordinator.api.async_request(
            "GET", endpoint, 
            params={"url": call.data[ATTR_URL], "timeout": call.data[ATTR_TIMEOUT]},
            suppress_errors=False
        )
        if group:
            sorted_items = sorted(response.items(), key=lambda x: x[1])
            return {"fastest_node": sorted_items[0][0] if sorted_items else None, "latency": sorted_items}
        return {"latency": {node: response.get("delay", [])}}

    async def handle_dns_query(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(call.data[CONF_DEVICE_ID])
        return await coordinator.api.async_request(
            "GET", "dns/query", 
            params={"name": call.data[ATTR_DOMAIN_NAME], "type": call.data[ATTR_RECORD_TYPE]},
            suppress_errors=False
        )

    async def handle_get_rule(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(call.data[CONF_DEVICE_ID])
        response = await coordinator.api.async_request("GET", "rules", suppress_errors=False)
        r_type = call.data.get(ATTR_RULE_TYPE, "").lower()
        r_payload = call.data.get(ATTR_RULE_PAYLOAD, "").lower()
        r_proxy = call.data.get(ATTR_RULE_PROXY, "").lower()
        
        filtered = [
            r for r in response.get("rules", [])
            if (not r_type or r_type in r.get("type", "").lower()) and
               (not r_payload or r_payload in r.get("payload", "").lower()) and
               (not r_proxy or r_proxy in r.get("proxy", "").lower())
        ]
        return {"rules": filtered}

    async def handle_api_call(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(call.data[CONF_DEVICE_ID])
        res = await coordinator.api.async_request(
            method=call.data[ATTR_API_METHOD],
            endpoint=call.data[ATTR_API_ENDPOINT],
            params=to_dict(call.data.get(ATTR_API_PARAMS)),
            json_data=to_dict(call.data.get(ATTR_API_DATA)),
            read_line=call.data.get(ATTR_READ_LINE, 0),
            suppress_errors=False
        )
        return {"response": res}

    # --- 注册服务 ---
    
    hass.services.async_register(
        DOMAIN, REBOOT_CORE_SERVICE_NAME, handle_reboot_core, 
        schema=REBOOT_CORE_SERVICE_SCHEMA
    )
    
    hass.services.async_register(
        DOMAIN, FILTER_CONNECTION_SERVICE_NAME, handle_filter_connection, 
        schema=FILTER_CONNECTION_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    
    hass.services.async_register(
        DOMAIN, GET_LATENCY_SERVICE_NAME, handle_get_latency, 
        schema=GET_LATENCY_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    
    hass.services.async_register(
        DOMAIN, DNS_QUERY_SERVICE_NAME, handle_dns_query, 
        schema=DNS_QUERY_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    
    hass.services.async_register(
        DOMAIN, GET_RULE_SERVICE_NAME, handle_get_rule, 
        schema=GET_RULE_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    
    hass.services.async_register(
        DOMAIN, API_CALL_SERVICE_NAME, handle_api_call, 
        schema=API_CALL_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
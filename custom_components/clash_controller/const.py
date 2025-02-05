"""Constants for the Clash Controller."""

DOMAIN = "clash_controller"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 10

CONF_CONCURRENT_CONNECTIONS = "concurrent_connections"
DEFAULT_CONCURRENT_CONNECTIONS = 5
MIN_CONCURRENT_CONNECTIONS = 1
MAX_CONCURRENT_CONNECTIONS = 10

REBOOT_CORE_SERVICE_NAME = "reboot_core_service"
GET_LATENCY_SERVICE_NAME = "get_latency_service"
GET_RULE_SERVICE_NAME = "get_rule_service"
FILTER_CONNECTION_SERVICE_NAME = "filter_connection_service"
DNS_QUERY_SERVICE_NAME = "dns_query_service"
API_CALL_SERVICE_NAME = "api_call_service"
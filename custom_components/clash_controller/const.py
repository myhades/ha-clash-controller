"""Constants for the Clash Controller."""

DOMAIN = "clash_controller"

# Configs

CONF_API_URL = "api_url"
CONF_BEAR_TOKEN = "bearer_token"
CONF_USE_SSL = "use_ssl"
CONF_ALLOW_UNSAFE = "allow_unsafe"

# Options

MIN_SCAN_INTERVAL = 10
DEFAULT_SCAN_INTERVAL = 60

MIN_CONCURRENT_CONNECTIONS = 1
DEFAULT_CONCURRENT_CONNECTIONS = 5
CONF_CONCURRENT_CONNECTIONS = "concurrent_connections"

CONF_STREAMING_DETECTION = "streaming_detection"
DEFAULT_STREAMING_DETECTION = False

# Service names

API_CALL_SERVICE_NAME = "api_call_service"
DNS_QUERY_SERVICE_NAME = "dns_query_service"
FILTER_CONNECTION_SERVICE_NAME = "filter_connection_service"
GET_LATENCY_SERVICE_NAME = "get_latency_service"
GET_RULE_SERVICE_NAME = "get_rule_service"
REBOOT_CORE_SERVICE_NAME = "reboot_core_service"


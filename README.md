# Home Assistant Clash Controller
[![](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![](https://img.shields.io/badge/maintainer-%40myhades-green)](https://github.com/myhades)
[![](https://img.shields.io/github/v/release/myhades/ha-clash-controller)](https://github.com/myhades/ha-clash-controller/releases)

![Repo Logo](https://raw.githubusercontent.com/myhades/ha-clash-controller/refs/heads/main/assets/clash_controller_repo_logo.png)

A Home Assistant integration for controlling an external Clash instance through RESTful API.

This is not an implementation of Clash, but an external controller in the form of a Home Asssistant integration to assist automated network control with ease. 

This integration is my very first Python / Home Assistant project, and I’m still learning. Please expect some instability and rough edges. Feedback and contributions are greatly appreciated!

## Supported Version

This integration is known to work with meta cores, and it should work with most of the Clash cores since they share the same RESTful API. This includes vanilla, premium and etc.
If you experience any issues with your core selection, please let me know. 

> [!IMPORTANT]
> Make sure external controller option is enabled with a token set.

## Installation

Through HACS (not added to default repo, yet)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=myhades&repository=ha-clash-controller&category=integration)

Or manually download the files and add to custom_components folder of your Home Assistant installation.

After either, reboot your instance.

## Configuration

Before proceeding, you'll need to prepare the endpoint location and the bearer token. Having a token set is required to use this integration.

To add the integration, use the My button below or navigate to "Settings" -> "Devices & services" -> "Add integration" -> "Clash Controller". Then, follow the config flow. 

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=clash_controller)

If you can't find it in the list, make sure you've successfully installed the integration and rebooted. If so, try clearing the browser cache.

Note the following:
1. If your endpoint is an IP address, make sure it's static or assign a static DHCP lease for it. Endpoint location changes will require you to re-add the integration.
2. This integration supports both http and https endpoints. If you're using a self-signed certificate, check the "Allow Unsafe SSL Certificates" box.
(Not recommanded, since this option suppresses all warnings and could potentially leak your token, use it only for experimental purposes and/or in a secured network)

## Usage

Note that availability of entities and services vary across cores.

### 1. Entities

- Proxy group sensor (all, current latency attributes)
- Proxy gorup selector (all, current latency attributes)
- Traffic sensor (up/down)
- Total traffic sensor (up/down)
- Connection number sensor
- Memory info sensor
- Flush FakeIP cache button

### 2. Services

| Service Name             | Parameter         | Required | Description |
|--------------------------|------------------|----------|-------------|
| **Reboot Clash Core**    | `device_id`      | Yes   | Select the target instance to reboot the Clash core. |
| **Filter Connection**    | `device_id`      | Yes   | Select the target instance. |
|                          | `close_connection` | No  | If enabled, retrieved connections will also be closed. |
|                          | `host`           | No   | Filter connections by host. |
|                          | `src_hostname`   | No   | Filter connections by source hostname. |
|                          | `des_hostname`   | No   | Filter connections by destination hostname. |
| **Get Latency**          | `device_id`      | Yes   | Select the target instance. |
|                          | `group`          | No   | Proxy group name. Testing a group will also clear its fixed option if set. |
|                          | `node`           | No   | Proxy node name. |
|                          | `url`            | No   | The URL used to test the latency. |
|                          | `timeout`        | No   | Connection timeout in milliseconds. |
| **DNS Query**            | `device_id`      | Yes   | Select the target instance. |
|                          | `domain_name`    | Yes   | The domain name to query. |
|                          | `record_type`    | No   | The record type to query. Leave empty to get IPv4 (A) record. |
| **API Call**             | `device_id`      | Yes   | Select the target instance. |
|                          | `api_endpoint`   | Yes   | The API endpoint to be used. |
|                          | `api_method`     | Yes   | The HTTP method (GET, POST, etc.). |
|                          | `api_params`     | No   | The query parameters for the request (valid JSON string). |
|                          | `api_data`       | No   | The JSON body sent in the request (valid JSON string). |
|                          | `read_line`      | No   | Indicates to read the n-th line for a chunked response. |

Example call: To get all proxies available:
```
action: clash_controller.api_call_service
data:
  api_endpoint: proxies
  api_method: GET
  device_id: [YOUR_DEVICE_ID]
response_variable: proxy_data
```


### 3. Additional Functions
This integration provides basic streaming service availability detection.
For this to work, Home Assistant must connect through the same proxy being tested, and this feature is off by default.
To enable/disable this feature, navigate to "Devices & services" -> "Clash Controller" -> "Options".

Currently supported service(s): Netflix.

## Known Issue
If you're connecting to a Clash behind Nginx or other reverse proxy, some real-time sensors will not work and get "unknown" instead. I'm still working on this.

## Feedback
To report an issue, please include details about your Clash configuration along with debug logs for this integration.
You can enable debug logging in the UI (if possible) or add the following to your Home Assistant configuration:
```
logger:
  default: warning
  logs:
    custom_components.clash_controller: debug
    custom_components.clash_controller.sensor: debug
```

## Disclaimer

This integration is solely for controlling Clash and is not responsible for any actions taken by users while using Clash. The user is fully responsible for ensuring that their use of Clash complies with all applicable laws and regulations. I make no warranties regarding the accuracy, legality, or appropriateness of Clash or its usage.

By using this integration, you acknowledge and agree to this disclaimer.

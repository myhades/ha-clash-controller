# Home Assistant Clash Controller
[![](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![](https://img.shields.io/badge/HACS-Default-yellow.svg)](https://hacs.xyz/)
[![](https://img.shields.io/badge/maintainer-%40myhades-green)](https://github.com/myhades)
[![](https://img.shields.io/github/v/release/myhades/ha-clash-controller)](https://github.com/myhades/ha-clash-controller/releases)

![Repo Logo](https://raw.githubusercontent.com/myhades/ha-clash-controller/refs/heads/main/assets/clash_controller_repo_logo.png)

A Home Assistant integration for controlling an external Clash instance through RESTful API.

This is not an implementation of Clash, but an external controller in the form of a Home Asssistant integration to assist automated network control with ease. 

This integration is my very first Python / Home Assistant project, and I’m still learning. Please expect some instability and rough edges. Feedback and contributions are greatly appreciated. If you find this project useful, consider giving it a ⭐star to show your support!

## Supported Version

This integration should work with most of the Clash clients. 
Known working: OpenClash, ShellClash and MerlinClash.

Core support:

| Core Name       | Supported |
|-----------------|-----------|
| Clash           | Partially |
| Clash Premium   | Partially |
| Clash Meta      | Yes       |

## Installation

Home Assistant Core must be newer than version `2024.4.3`. 

Choose your preferred installation method, and reboot Home Assistant afterward.

### Method 1: Through HACS

Navigate to "HACS" > "Clash Controller" or use the My button below.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=myhades&repository=ha-clash-controller&category=integration)

### Method 2: Manually

Download the repo and copy the folder `/custom_components/clash_controller` into your Home Assistant's `/config/custom_components` directory.

## Configuration

You'll need the API location (most likely with a port number) and the bearer token. Having a token set is required to use this integration.

To add the integration, navigate to "Settings"  > "Devices & services"  > "Add integration"  > "Clash Controller" or use the My button below. Then, follow the config flow. 

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=clash_controller)

Notes:
1. If you can't find it in the integration list, make sure you've successfully installed the integration and rebooted. If so, try clearing the browser cache.
2. If your API location is an IP address, make sure it's static or assign a static DHCP lease for it. Location changes will require you to re-add the integration.
3. This integration supports http and https. If you're using a self-signed certificate, check the "Allow Unsafe SSL Certificates" box and use it only in a secured network.

## Usage

Availability of the following entities and services varies across cores.

### 1. Entities

- Proxy group sensor (all, current latency attributes)
- Proxy gorup selector (all, current latency attributes)
- Traffic sensor (up/down)
- Total traffic sensor (up/down)
- Connection number sensor
- Memory info sensor
- Flush FakeIP cache button

### 2. Services

<table>
  <tr>
    <th>Service Name</th>
    <th>Parameter</th>
    <th>Required</th>
    <th>Description</th>
  </tr>
  
  <tr>
    <td align="center"><b>Reboot Clash Core</b></td>
    <td><code>device_id</code></td>
    <td>✅ Yes</td>
    <td>Select the target instance to reboot the Clash core.</td>
  </tr>
  <tr>
    <td rowspan="5" align="center"><b>Filter Connection</b></td>
    <td><code>device_id</code></td>
    <td>✅ Yes</td>
    <td>Select the target instance.</td>
  </tr>
  <tr>
    <td><code>close_connection</code></td>
    <td>❌ No</td>
    <td>If enabled, retrieved connections will also be closed.</td>
  </tr>
  <tr>
    <td><code>host</code></td>
    <td>❌ No</td>
    <td>Filter connections by host.</td>
  </tr>
  <tr>
    <td><code>src_hostname</code></td>
    <td>❌ No</td>
    <td>Filter connections by source hostname.</td>
  </tr>
  <tr>
    <td><code>des_hostname</code></td>
    <td>❌ No</td>
    <td>Filter connections by destination hostname.</td>
  </tr>

  <tr>
    <td rowspan="5" align="center"><b>Get Latency</b></td>
    <td><code>device_id</code></td>
    <td>✅ Yes</td>
    <td>Select the target instance.</td>
  </tr>
  <tr>
    <td><code>group</code></td>
    <td>❌ No</td>
    <td>Proxy group name. Testing a group will also clear its fixed option if set.</td>
  </tr>
  <tr>
    <td><code>node</code></td>
    <td>❌ No</td>
    <td>Proxy node name.</td>
  </tr>
  <tr>
    <td><code>url</code></td>
    <td>❌ No</td>
    <td>The URL used to test the latency.</td>
  </tr>
  <tr>
    <td><code>timeout</code></td>
    <td>❌ No</td>
    <td>Connection timeout in milliseconds.</td>
  </tr>

  <tr>
    <td rowspan="3" align="center"><b>DNS Query</b></td>
    <td><code>device_id</code></td>
    <td>✅ Yes</td>
    <td>Select the target instance.</td>
  </tr>
  <tr>
    <td><code>domain_name</code></td>
    <td>✅ Yes</td>
    <td>The domain name to query.</td>
  </tr>
  <tr>
    <td><code>record_type</code></td>
    <td>❌ No</td>
    <td>The record type to query. Leave empty to get IPv4 (A) record.</td>
  </tr>

  <tr>
    <td rowspan="4" align="center"><b>Get Rule</b></td>
    <td><code>device_id</code></td>
    <td>✅ Yes</td>
    <td>Select the target instance.</td>
  </tr>
  <tr>
    <td><code>rule_type</code></td>
    <td>❌ No</td>
    <td>The type of the rule.</td>
  </tr>
  <tr>
    <td><code>rule_payload</code></td>
    <td>❌ No</td>
    <td>The payload to match.</td>
  </tr>
  <tr>
    <td><code>rule_proxy</code></td>
    <td>❌ No</td>
    <td>The proxy method used.</td>
  </tr>

  <tr>
    <td rowspan="6" align="center"><b>API Call</b></td>
    <td><code>device_id</code></td>
    <td>✅ Yes</td>
    <td>Select the target instance.</td>
  </tr>
  <tr>
    <td><code>api_endpoint</code></td>
    <td>✅ Yes</td>
    <td>The API endpoint to be used.</td>
  </tr>
  <tr>
    <td><code>api_method</code></td>
    <td>✅ Yes</td>
    <td>The HTTP method (GET, POST, etc.).</td>
  </tr>
  <tr>
    <td><code>api_params</code></td>
    <td>❌ No</td>
    <td>The query parameters for the request. Needs to be a valid JSON string.</td>
  </tr>
  <tr>
    <td><code>api_data</code></td>
    <td>❌ No</td>
    <td>The JSON body sent in the request. Needs to be a valid JSON string.</td>
  </tr>
  <tr>
    <td><code>read_line</code></td>
    <td>❌ No</td>
    <td>Indicates to read the n-th line for a chunked response.</td>
  </tr>
</table>


Example call of getting available proxies:
```
action: clash_controller.api_call_service
data:
  device_id: [YOUR_DEVICE_ID]
  api_endpoint: proxies
  api_method: GET
response_variable: proxy_data
```


### 3. Additional Functions
This integration provides basic streaming service availability detection.
For this to work, Home Assistant must connect through the same proxy being tested, and this feature is off by default.
To enable/disable this feature, navigate to "Settings"  > "Devices & services"  > "Clash Controller"  > "Options".

Currently supported service(s): Netflix.

## Known Issue
If you're connecting to a Clash behind Nginx or other reverse proxy server, some real-time sensors will not work and get "unknown" state instead. I'm still working on this.

## Feedback
To report an issue, please include details about your Clash configuration such as client type, core type and core version, along with debug logs of this integration.
You can enable debug logging in the UI (if possible) or add the following to your Home Assistant configuration:
```
logger:
  default: warning
  logs:
    custom_components.clash_controller: debug
    custom_components.clash_controller.sensor: debug
```

## Disclaimer

This integration is solely for controlling Clash and is not responsible for any actions taken by users while using Clash. The user is fully responsible for ensuring that their use of Clash complies with all applicable laws and regulations.  Neither the owner nor the contributors to this repository make any warranties regarding the accuracy, legality, or appropriateness of Clash or its use.

By using this integration, you acknowledge and agree to this disclaimer.

# Home Assistant Clash Controller
[![](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![](https://img.shields.io/badge/maintainer-%40myhades-green)](https://github.com/myhades)
[![](https://img.shields.io/github/v/release/myhades/ha-clash-controller)](https://github.com/myhades/ha-clash-controller/releases)

![Repo Logo](https://raw.githubusercontent.com/myhades/ha-clash-controller/refs/heads/main/assets/clash_controller_repo_logo.png)

A Home Assistant integration for controlling an external Clash instance through RESTful API.

This is not an implementation of Clash, but an external controller in the form of a Home Asssistant integration to assist automated network control with ease. 

This integration is my very first Python / Home Assistant project, and I’m still learning. Please expect some instability and rough edges. Feedback and contributions are greatly appreciated!

## Supported Version

This integration should work with most of the Clash cores since they share the same RESTful API. This includes vanilla, premium and meta cores, etc.

> [!IMPORTANT]
> Make sure external controller option is enabled.

## Installation

Through HACS (not added to default repo, yet)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=myhades&repository=ha-clash-controller&category=integration)

Or manually download the files and add to custom_components folder of your Home Assistant installation.

After either, reboot your instance.

## Configuration

Add the integration by searching "Clash Controller" and follow the config flow. If you can't find it in the list, make sure you've successfully installed the integration and rebooted. Then, clear the browser cache.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=clash_controller)

You'll need to provide the endpoint location and the bearer token. Having a token set is required to use this integration.

Note the following:
1. If your endpoint is an IP address, make sure it's static or assign a static DHCP lease for it. Endpoint location changes will require you to re-add the integration.
2. This integration supports both http and https endpoints. If you're using a self-signed certificate, check the "Allow Unsafe SSL Certificates" box.
(Not recommanded, since this option suppresses all warnings and could potentially leak your token, use it only for experimental purposes and/or in a secured network)

## Usage

1. Entities
- [x] Proxy group sensor (all, current latency attributes)
- [x] Proxy gorup selector (all, current latency attributes)
- [x] Traffic sensor (up/down)
- [x] Total traffic sensor (up/down)
- [x] Connection number sensor
- [x] Memory info sensor
- [x] Flush FakeIP cache button

2. Services
- [x] Node/Group latency
- [x] Get/Close connection (with filters)
- [x] Get rules (with filters)
- [x] DNS query
- [x] Reboot core

3. Additional Functions
- [ ] Streaming service availability detection
- [ ] Automatic proxy node selection for streaming

## Disclaimer

This integration is solely for controlling Clash and is not responsible for any actions taken by users while using Clash. The user is fully responsible for ensuring that their use of Clash complies with all applicable laws and regulations. I make no warranties regarding the accuracy, legality, or appropriateness of Clash or its usage.

By using this integration, you acknowledge and agree to this disclaimer.

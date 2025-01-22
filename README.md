# Home Assistant Clash Controller
A Home Assistant integration for controlling an external Clash instance through RESTful API.
This is not an implementation of Clash, but merely an external controller in the form of a Home Asssistant integration to assist automated network control. 
(Streaming service availability detection and automatic proxy node change feature planned)

*This integration is currently under development and implemented no functionality.*

### Supported Version

This integration should work with most of the Clash cores since they share the same RESTful API. This includes vanilla, premium and meta cores, etc.
**Make sure external controller option is enabled**.

## Installation

(Recommanded) Through HACS (not added to default repo, yet)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=myhades&repository=ha-clash-controller&category=integration)

Or manually download the files and add to custom_components folder of your Home Assistant installation.

After either, reboot your instance.

## Configuration
Add the integration by searching "Clash Controller" and follow the config flow. If you can't find it in the list, make sure you've rebooted then clear the browser cache.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=clash_controller)

You'll need to provide the endpoint location and the bearer token. Having the token enabled is required to use this integration.

Note the following:
1. If your endpoint is an IP address, make sure it's static or assign a static DHCP lease for it. Endpoint location changes will require you to re-add the integration.
2. This integration supports both http and https endpoints. If you're using a self-signed certificate, check the "Allow Unsafe SSL Certificates" box.
(Not recommanded, since this option suppresses all warnings and could potentially leak your token, use it only for experimental purposes and/or in a secured network)

## Usage
This integration provide one device per entry. It will generate selectors and sensors by enumerate through all proxy groups.
Services are provided to get the latency of a proxy group/node, flush the cache and reboot the core.

1. Entities
- [ ] Proxy group sensor (all, current latency attributes)
- [ ] Proxy gorup selector (all, current latency attributes)
- [ ] Traffic sensor (up/down)
- [ ] Total traffic sensor (up/down)
- [ ] Connection number
- [ ] Memory info
- [ ] Core version sensor (attributes with config info)

2. Services
- [ ] Node/Group latency
- [ ] Flush Cache
- [ ] Reboot core
- [ ] Delete connection (with different filters)

## Disclaimer

This integration is solely for controlling Clash and is not responsible for any actions taken by users while using Clash. The user is fully responsible for ensuring that their use of Clash complies with all applicable laws and regulations. I make no warranties regarding the accuracy, legality, or appropriateness of Clash or its usage.

By using this integration, you acknowledge and agree to this disclaimer.
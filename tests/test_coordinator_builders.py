"""Small capability-dependent entity construction contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.clash_controller.coordinator import ClashControllerCoordinator


@pytest.mark.parametrize("fixed", [True, False])
def test_urltest_entity_type(fixed):
    group = {"name": "Auto", "type": "URLTest", "now": "a", "all": ["a", "b"]}
    if fixed:
        group["fixed"] = "a"
    entities = ClashControllerCoordinator._build_proxy_entities(
        {"proxies": {"auto": group}}
    )
    assert len(entities) == 1
    assert entities[0].entity_type == (
        "proxy_group_selector" if fixed else "proxy_group_sensor"
    )
    assert entities[0].options == (["a", "b"] if fixed else None)


@pytest.mark.parametrize("healthcheck", [True, False])
def test_provider_entities(healthcheck):
    coordinator = object.__new__(ClashControllerCoordinator)
    coordinator.api = SimpleNamespace(async_request=AsyncMock())
    entities = coordinator._build_provider_entities(
        {"providers": {"default": {}, "HK Group": {"timeout": "3000"}}},
        {"providers": {"rules": {}}},
        provider_healthcheck_enabled=healthcheck,
    )
    counts = {
        item.unique_key: item.state
        for item in entities
        if item.entity_type == "provider_count_sensor"
    }
    assert counts == {"proxy_provider_count": 2, "rule_provider_count": 1}
    buttons = [
        item for item in entities if item.entity_type == "provider_healthcheck_button"
    ]
    assert len(buttons) == (2 if healthcheck else 0)
    if healthcheck:
        assert all(item.enabled_default is False for item in buttons)
        assert {
            (item.action["args"][1], item.action["kwargs"]["params"]["timeout"])
            for item in buttons
        } == {
            ("providers/proxies/default/healthcheck", 5000),
            ("providers/proxies/HK%20Group/healthcheck", 3000),
        }

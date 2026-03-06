"""Unit tests for coordinator entity builders."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.helpers.entity import EntityCategory

from custom_components.clash_controller.coordinator import ClashControllerCoordinator


def test_build_proxy_entities_urltest_with_fixed_is_selector() -> None:
    """URLTest groups with fixed support should be exposed as selectors."""
    proxies = {
        "proxies": {
            "auto": {
                "name": "Auto",
                "type": "URLTest",
                "now": "node-a",
                "all": ["node-a", "node-b"],
                "fixed": "node-a",
                "testUrl": "http://example.com",
            }
        }
    }

    entities = ClashControllerCoordinator._build_proxy_entities(proxies)

    assert len(entities) == 1
    entity = entities[0]
    assert entity.entity_type == "proxy_group_selector"
    assert entity.options == ["node-a", "node-b"]
    assert entity.attributes["fixed"] is True


def test_build_proxy_entities_urltest_without_fixed_is_sensor() -> None:
    """Legacy URLTest groups should remain sensors without fixed attribute."""
    proxies = {
        "proxies": {
            "auto": {
                "name": "Auto",
                "type": "URLTest",
                "now": "node-a",
                "all": ["node-a", "node-b"],
            }
        }
    }

    entities = ClashControllerCoordinator._build_proxy_entities(proxies)

    assert len(entities) == 1
    entity = entities[0]
    assert entity.entity_type == "proxy_group_sensor"
    assert entity.options is None
    assert "fixed" not in (entity.attributes or {})


def test_build_provider_entities_with_healthcheck() -> None:
    """Provider entities should include counters and optional healthcheck buttons."""
    coordinator = object.__new__(ClashControllerCoordinator)
    coordinator.api = SimpleNamespace(async_request=AsyncMock())

    providers_proxies = {
        "providers": {
            "default": {"testUrl": "http://a.example"},
            "HK Group": {"testUrl": "http://b.example", "timeout": "3000"},
        }
    }
    providers_rules = {"providers": {"rule-a": {}, "rule-b": {}}}

    entities = ClashControllerCoordinator._build_provider_entities(
        coordinator,
        providers_proxies,
        providers_rules,
        provider_healthcheck_enabled=True,
    )

    count_entities = [e for e in entities if e.entity_type == "provider_count_sensor"]
    assert len(count_entities) == 2

    proxy_count = next(e for e in count_entities if e.translation_key == "proxy_provider_count")
    rule_count = next(e for e in count_entities if e.translation_key == "rule_provider_count")
    assert proxy_count.state == 2
    assert rule_count.state == 2
    assert proxy_count.entity_category == EntityCategory.DIAGNOSTIC
    assert rule_count.entity_category == EntityCategory.DIAGNOSTIC

    buttons = [e for e in entities if e.entity_type == "provider_healthcheck_button"]
    assert len(buttons) == 2

    default_button = next(
        e for e in buttons if e.translation_key == "default_proxy_group_healthcheck"
    )
    custom_button = next(e for e in buttons if e.translation_key == "provider_healthcheck")

    assert default_button.translation_placeholders is None
    assert default_button.enabled_default is False
    assert default_button.action["args"][1] == "providers/proxies/default/healthcheck"
    assert default_button.action["kwargs"]["params"]["timeout"] == 5000

    assert custom_button.translation_placeholders == {"provider_name": "HK Group"}
    assert custom_button.enabled_default is False
    assert custom_button.action["args"][1] == "providers/proxies/HK%20Group/healthcheck"
    assert custom_button.action["kwargs"]["params"]["timeout"] == 3000


def test_build_provider_entities_without_healthcheck() -> None:
    """Provider buttons should not be created when healthcheck is disabled."""
    coordinator = object.__new__(ClashControllerCoordinator)
    coordinator.api = SimpleNamespace(async_request=AsyncMock())

    providers_proxies = {"providers": {"A": {}}}
    providers_rules = {"providers": {}}

    entities = ClashControllerCoordinator._build_provider_entities(
        coordinator,
        providers_proxies,
        providers_rules,
        provider_healthcheck_enabled=False,
    )

    assert [e.entity_type for e in entities] == [
        "provider_count_sensor",
        "provider_count_sensor",
    ]

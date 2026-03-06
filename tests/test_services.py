"""Unit tests for services helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.exceptions import HomeAssistantError

from custom_components.clash_controller.services import (
    GROUP_NAME,
    NODE_NAME,
    TEST_TIMEOUT,
    TEST_URL,
    ClashServicesSetup,
)


@pytest.mark.asyncio
async def test_get_latency_service_quotes_group_name() -> None:
    """Group latency requests should URL-encode group names."""
    coordinator = SimpleNamespace(
        api=SimpleNamespace(async_request=AsyncMock(return_value={"node-a": 80}))
    )
    service = ClashServicesSetup.__new__(ClashServicesSetup)
    service._get_coordinator = lambda _device_id: coordinator

    call = SimpleNamespace(
        data={
            CONF_DEVICE_ID: "dev1",
            GROUP_NAME: "A/B Group",
            TEST_URL: "http://www.gstatic.com/generate_204",
            TEST_TIMEOUT: 5000,
        }
    )

    result = await service.async_get_latency_service(call)

    coordinator.api.async_request.assert_awaited_once_with(
        method="GET",
        endpoint="group/A%2FB%20Group/delay",
        params={"url": "http://www.gstatic.com/generate_204", "timeout": 5000},
        suppress_errors=False,
    )
    assert result["fastest_node"] == "node-a"


@pytest.mark.asyncio
async def test_get_latency_service_quotes_node_name() -> None:
    """Node latency requests should URL-encode node names."""
    coordinator = SimpleNamespace(
        api=SimpleNamespace(async_request=AsyncMock(return_value={"delay": 35}))
    )
    service = ClashServicesSetup.__new__(ClashServicesSetup)
    service._get_coordinator = lambda _device_id: coordinator

    call = SimpleNamespace(
        data={
            CONF_DEVICE_ID: "dev1",
            NODE_NAME: "HK/A",
            TEST_URL: "http://www.gstatic.com/generate_204",
            TEST_TIMEOUT: 5000,
        }
    )

    result = await service.async_get_latency_service(call)

    coordinator.api.async_request.assert_awaited_once_with(
        method="GET",
        endpoint="proxies/HK%2FA/delay",
        params={"url": "http://www.gstatic.com/generate_204", "timeout": 5000},
        suppress_errors=False,
    )
    assert result == {"latency": {"HK/A": 35}}


@pytest.mark.asyncio
async def test_get_latency_service_requires_exactly_one_target() -> None:
    """Service should reject invalid target combinations."""
    coordinator = SimpleNamespace(api=SimpleNamespace(async_request=AsyncMock()))
    service = ClashServicesSetup.__new__(ClashServicesSetup)
    service._get_coordinator = lambda _device_id: coordinator

    with pytest.raises(HomeAssistantError):
        await service.async_get_latency_service(
            SimpleNamespace(
                data={
                    CONF_DEVICE_ID: "dev1",
                    GROUP_NAME: "group-a",
                    NODE_NAME: "node-a",
                }
            )
        )

    with pytest.raises(HomeAssistantError):
        await service.async_get_latency_service(
            SimpleNamespace(data={CONF_DEVICE_ID: "dev1"})
        )

"""Diagnostics support for Clash Controller."""

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ClashControllerConfigEntry
from .const import CONF_API_URL, CONF_BEAR_TOKEN

TO_REDACT = {CONF_API_URL, CONF_BEAR_TOKEN, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ClashControllerConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = config_entry.runtime_data.coordinator
    entity_counts = Counter(
        entity.entity_type for entity in (coordinator.data or [])
    )

    return {
        "config_entry": async_redact_data(config_entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "entity_counts": dict(entity_counts),
        },
        "api": {
            "capabilities": coordinator.api.capabilities or {},
            "available_endpoints": [
                endpoint
                for endpoint, _params in (coordinator.api.available_endpoints or [])
            ],
        },
    }

"""Persistent identities for entities derived from core-provided names."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import ClashEntityData

_LOGGER = logging.getLogger(__name__)


class EntityIdentityStore:
    """Allocate names once and retain ownership when an endpoint disappears."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.store = Store(hass, 1, f"{DOMAIN}.{entry_id}.entity_identities")
        self.identities: dict[str, str] = {}
        self.reserved: set[str] = set()
        self._provider_templates: set[str] = set()
        self._dirty = False

    async def async_load(self) -> None:
        """Load persisted allocations and legacy provider name templates."""
        data = await self.store.async_load()
        if data is not None:
            self.identities = data["identities"]
            self.reserved = set(data["reserved"])
        for language in ("en", "de", "zh-Hans"):
            translations = await async_get_translations(
                self.hass, language, "entity", {DOMAIN}
            )
            template = translations.get(
                f"component.{DOMAIN}.entity.button.provider_healthcheck.name"
            )
            if template:
                self._provider_templates.add(template)

    @staticmethod
    def _key(item: ClashEntityData) -> str:
        return json.dumps([item.entity_type, item.identity_name], ensure_ascii=False)

    def assign(self, entities: list[ClashEntityData]) -> None:
        """Preserve legacy IDs and allocate permanent IDs for colliding names."""
        named = [item for item in entities if item.identity_name is not None]
        if all(self._key(item) in self.identities for item in named):
            for item in named:
                item.unique_id = self.identities[self._key(item)]
            return
        registry = er.async_get(self.hass)
        registered = {
            entry.unique_id: entry
            for entry in er.async_entries_for_config_entry(registry, self.entry_id)
            if entry.platform == DOMAIN
        }
        buckets: dict[str, list[ClashEntityData]] = defaultdict(list)
        for item in entities:
            if item.identity_name is not None:
                buckets[item.unique_id].append(item)
        occupied = self.reserved | set(self.identities.values()) | set(registered)
        # Reserve every legacy ID before generating suffixes, including IDs
        # belonging to another bucket that has not been processed yet.
        occupied.update(item.unique_id for item in entities)
        for legacy_id, items in buckets.items():
            if (
                legacy_id not in self.reserved
                and legacy_id not in self.identities.values()
            ):
                owner = None
                if entry := registered.get(legacy_id):
                    original_name = (
                        entry.original_name_unprefixed or entry.original_name
                    )
                    matches = [
                        item
                        for item in items
                        if original_name == item.identity_name
                        or (
                            item.entity_type == "provider_healthcheck_button"
                            and any(
                                template.replace("{provider_name}", item.identity_name)
                                == original_name
                                for template in self._provider_templates
                            )
                        )
                    ]
                    if len(matches) == 1:
                        owner = matches[0]
                    elif (
                        len(items) == 1
                        and items[0].translation_key
                        == "default_proxy_group_healthcheck"
                    ):
                        owner = items[0]
                    else:
                        self.reserved.add(legacy_id)
                        self._dirty = True
                        _LOGGER.warning(
                            "Legacy entity %s has ambiguous name ownership; preserving its ID without reassignment",
                            entry.entity_id,
                        )
                else:
                    owner = min(items, key=self._key)
                if owner is not None and self._key(owner) not in self.identities:
                    self.identities[self._key(owner)] = legacy_id
                    self._dirty = True

            for item in items:
                key = self._key(item)
                if key not in self.identities:
                    suffix = hashlib.sha256(key.encode()).hexdigest()
                    candidate = f"{legacy_id}_{suffix}"
                    index = 2
                    while candidate in occupied:
                        candidate = f"{legacy_id}_{suffix}_{index}"
                        index += 1
                    self.identities[key] = candidate
                    occupied.add(candidate)
                    self._dirty = True
                item.unique_id = self.identities[key]

    async def async_save(self) -> None:
        """Persist new identities before publishing them to entity platforms."""
        if self._dirty:
            await self.store.async_save(
                {
                    "identities": self.identities,
                    "reserved": sorted(self.reserved),
                }
            )
            self._dirty = False

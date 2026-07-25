"""Persisted alias map (the pantry).

Backed by ``homeassistant.helpers.storage.Store`` at ``.storage/mathem_pantry``
and mutated through services, because managing ~150 rows through an options
dialog is not viable and a custom frontend panel is disproportionate.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .mathem_client import AliasMap

_LOGGER = logging.getLogger(__name__)


class Pantry:
    """Loads, mutates, and persists the alias map."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.aliases = AliasMap()

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.aliases = AliasMap(data.get("aliases") or {})

    async def async_save(self) -> None:
        await self._store.async_save({"aliases": self.aliases.as_dict()})

    async def async_set_alias(self, keyword: str, data: dict[str, Any]) -> None:
        self.aliases.add(keyword, data)
        await self.async_save()

    async def async_remove_alias(self, keyword: str) -> bool:
        removed = self.aliases.remove(keyword)
        if removed:
            await self.async_save()
        return removed

    def export(self) -> dict[str, Any]:
        return {"aliases": self.aliases.as_dict()}

    async def async_import(self, data: dict[str, Any], *, replace: bool = False) -> int:
        """Merge (or replace) aliases from an imported dict. Returns row count."""
        incoming = data.get("aliases") or {}
        if replace:
            self.aliases = AliasMap()
        for keyword, entry in incoming.items():
            self.aliases.add(keyword, entry)
        await self.async_save()
        return len(incoming)

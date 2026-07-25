"""Diagnostic button to resync Mathem on demand."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .data import MathemConfigEntry
from .entity import MathemEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MathemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([MathemResyncButton(entry.runtime_data.coordinator, entry.entry_id)])


class MathemResyncButton(MathemEntity, ButtonEntity):
    """Refresh the cart, orders and held delivery slot immediately.

    Sits in the device's diagnostics card, for when something was changed in the
    Mathem app and you do not want to wait for the next poll.
    """

    _attr_name = "Resync"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_resync"

    async def async_press(self) -> None:
        """Poll Mathem now, updating every entity from the response."""
        await self.coordinator.async_request_refresh()

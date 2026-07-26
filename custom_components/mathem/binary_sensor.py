"""Binary sensors: whether a delivery lands today."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .data import MathemConfigEntry
from .entity import MathemEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MathemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([MathemDeliveryTodayBinarySensor(entry.runtime_data.coordinator, entry.entry_id)])


class MathemDeliveryTodayBinarySensor(MathemEntity, BinarySensorEntity):
    """On when the next delivery's booked day is today.

    Dashboard visibility conditions can only test an entity's state, not an
    attribute or a template, so this exposes the day check as its own entity.
    It is also a natural trigger for delivery-day automations.
    """

    _attr_name = "Delivery today"
    _attr_icon = "mdi:truck-check"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_delivery_today"

    @property
    def is_on(self) -> bool:
        order = self.coordinator.data.next_delivery if self.coordinator.data else None
        if order is None:
            return False
        return order.is_delivery_today(dt_util.now())

"""Sensors: next delivery, cart total, selected slot."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .data import MathemConfigEntry
from .entity import MathemEntity
from .mathem_client.models import _parse_price


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MathemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            MathemNextDeliverySensor(coordinator, entry.entry_id),
            MathemCartTotalSensor(coordinator, entry.entry_id),
            MathemSelectedSlotSensor(coordinator, entry.entry_id),
        ]
    )


class MathemNextDeliverySensor(MathemEntity, SensorEntity):
    """The start of the next delivery window (device_class timestamp)."""

    entity_description = SensorEntityDescription(
        key="next_delivery",
        translation_key="next_delivery",
        device_class=SensorDeviceClass.TIMESTAMP,
    )
    _attr_name = "Next delivery"
    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_next_delivery"

    @property
    def native_value(self) -> datetime | None:
        order = self.coordinator.data.next_delivery if self.coordinator.data else None
        if order is None:
            return None
        start, _ = order.window(dt_util.now())
        return start

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        order = self.coordinator.data.next_delivery if self.coordinator.data else None
        if order is None:
            return {}
        _, end = order.window(dt_util.now())
        return {
            "order_number": order.order_number,
            "window": order.delivery_time_text,
            "window_end": end.isoformat() if end else None,
            "status": order.status_title,
            "edit_deadline": order.cutoff_text,
            "address": order.delivery_address,
            "doorstep_delivery": order.is_doorstep_delivery,
        }


class MathemCartTotalSensor(MathemEntity, SensorEntity):
    """Cart goods total (``displayPrice``) with fee breakdown in attributes."""

    _attr_name = "Cart total"
    _attr_native_unit_of_measurement = "SEK"
    _attr_icon = "mdi:cart"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_cart_total"

    @property
    def native_value(self) -> float | str | None:
        cart = self.coordinator.data.cart if self.coordinator.data else None
        if cart is None:
            return None
        # displayPrice is goods only; keep the numeric value where parseable.
        parsed = _parse_price(cart.display_price)
        return parsed if parsed is not None else cart.display_price

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cart = self.coordinator.data.cart if self.coordinator.data else None
        if cart is None:
            return {}
        return {
            "total_gross_amount": cart.total_gross_amount,
            "summary_lines": [s.raw for s in cart.summary_lines],
            "line_count": cart.line_count,
            "unit_count": cart.unit_count,
            "currency": cart.currency,
        }


class MathemSelectedSlotSensor(MathemEntity, SensorEntity):
    """The most recently selected slot; display-only, may be stale."""

    _attr_name = "Selected slot"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_selected_slot"

    @property
    def native_value(self) -> str | None:
        selection = self.coordinator.data.selection if self.coordinator.data else None
        if selection is None:
            return None
        return selection.name_short or selection.name or str(selection.id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        selection = self.coordinator.data.selection if self.coordinator.data else None
        if selection is None:
            return {}
        return {
            "slot_id": selection.id,
            "window": selection.name,
            "hold_expires_at": selection.expire_at.isoformat() if selection.expire_at else None,
        }

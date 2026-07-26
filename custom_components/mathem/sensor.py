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
        """Start of the delivery window.

        Once Mathem narrows the booked window to an estimate, that is the more
        useful number, so the state follows it. The booked window stays
        available in the attributes.
        """
        order = self.coordinator.data.next_delivery if self.coordinator.data else None
        if order is None:
            return None
        start, _ = order.effective_window(dt_util.now())
        return start

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        order = self.coordinator.data.next_delivery if self.coordinator.data else None
        if order is None:
            return {}
        now = dt_util.now()
        booked_start, booked_end = order.window(now)
        est_start, est_end = order.estimated_window(now)
        _, effective_end = order.effective_window(now)
        return {
            "order_number": order.order_number,
            "window": order.delivery_time_text,
            # Compact "HH:MM - HH:MM" for a dashboard badge, where the day is
            # already implied. Follows the estimate when there is one.
            "window_short": order.window_short(now),
            # Follows the state, so start and end always describe one window.
            "window_end": effective_end.isoformat() if effective_end else None,
            "booked_start": booked_start.isoformat() if booked_start else None,
            "booked_end": booked_end.isoformat() if booked_end else None,
            "estimated_start": est_start.isoformat() if est_start else None,
            "estimated_end": est_end.isoformat() if est_end else None,
            "is_estimated": est_start is not None,
            "estimate_text": order.tracking_subtitle,
            "status": order.status_title,
            "tracking_step": order.tracking_step,
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
    """The delivery slot Mathem currently holds.

    Read from the slot list on every poll, so a slot booked in the Mathem app or
    on the website is reflected too, not only ones booked through this
    integration. Display only; nothing automates against it.
    """

    _attr_name = "Selected slot"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_selected_slot"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        if data.selected_slot is not None:
            return data.selected_slot.window_label
        if data.selection is not None:
            return data.selection.name_short or data.selection.name
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {}
        slot, selection = data.selected_slot, data.selection
        attrs: dict[str, Any] = {}
        if slot is not None:
            attrs = {
                "slot_id": slot.id,
                "window": slot.window_label,
                "window_start": slot.local_open.isoformat() if slot.local_open else None,
                "window_end": slot.local_close.isoformat() if slot.local_close else None,
                "price": slot.price,
                "cutoff": slot.cutoff_dt.isoformat() if slot.cutoff_dt else None,
            }
        elif selection is not None:
            attrs = {"slot_id": selection.id, "window": selection.name}
        # Only the set_delivery_slot echo carries the hold expiry, and only while
        # it still refers to the slot being displayed.
        if selection is not None and (slot is None or selection.id == slot.id):
            attrs["hold_expires_at"] = (
                selection.expire_at.isoformat() if selection.expire_at else None
            )
        return attrs

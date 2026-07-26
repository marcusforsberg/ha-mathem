"""Delivery calendar.

Served entirely from coordinator data. ``async_get_events`` must never issue its
own request, or scrolling the calendar UI would hammer the API.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .data import MathemConfigEntry
from .entity import MathemEntity
from .mathem_client.models import Order


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MathemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([MathemCalendar(coordinator, entry.entry_id)])


def _event_for(order: Order, now: datetime) -> CalendarEvent | None:
    """Build the event for an order.

    Deliberately spans the whole booked window rather than any narrowed
    estimate: the booked window is what Mathem committed to, and an estimate can
    still move. The estimate goes in the description instead, and the sharper
    time is on ``sensor.mathem_next_delivery``.
    """
    start, end = order.window(now)
    if start is None:
        return None
    if end is None:
        end = start + timedelta(hours=1)
    summary = "Mathem delivery"
    if order.order_number:
        summary = f"Mathem delivery #{order.order_number}"
    description = " ".join(
        part for part in (order.status_title, order.tracking_subtitle) if part
    )
    return CalendarEvent(
        start=start,
        end=end,
        summary=summary,
        description=description or None,
    )


class MathemCalendar(MathemEntity, CalendarEntity):
    """Shows upcoming deliveries drawn from active orders."""

    _attr_name = "Delivery"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_calendar"

    def _events(self) -> list[CalendarEvent]:
        data = self.coordinator.data
        if not data or not data.orders:
            return []
        now = dt_util.now()
        # Undelivered rather than "active": the API moves an order out of the
        # active group once it ships, and it is still a delivery until it lands.
        events = [_event_for(o, now) for o in data.orders.upcoming]
        return [e for e in events if e is not None]

    @property
    def event(self) -> CalendarEvent | None:
        upcoming = sorted(self._events(), key=lambda e: e.start)
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        # Served from coordinator data only; never fetches.
        return [
            event
            for event in self._events()
            if event.end > start_date and event.start < end_date
        ]

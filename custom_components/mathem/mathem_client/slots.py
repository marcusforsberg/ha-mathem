"""Delivery slot listing and selection.

Slot ids are ephemeral, so a preference is expressed as a predicate over the
local weekday and local open/close time, never as a stored id. Datetimes from
the API are UTC and are converted to Europe/Stockholm before matching.

The slot response also carries a ``checkoutUrl`` pointing at
``checkout/confirm``. It is never read here; the session layer refuses that path
regardless.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import time
from typing import Any, Iterable

from .models import Slot, SlotSelection
from .session import MathemSession

_LOGGER = logging.getLogger(__name__)

NUM_DAYS = 3  # the API serves 3 days per call; page with from-index

# Weekday tokens accepted in a predicate. Monday=0 .. Sunday=6.
_WEEKDAYS: dict[str, int] = {
    "mon": 0, "monday": 0, "må": 0, "mån": 0, "måndag": 0,
    "tue": 1, "tuesday": 1, "ti": 1, "tis": 1, "tisdag": 1,
    "wed": 2, "wednesday": 2, "on": 2, "ons": 2, "onsdag": 2,
    "thu": 3, "thursday": 3, "to": 3, "tor": 3, "torsdag": 3,
    "fri": 4, "friday": 4, "fr": 4, "fre": 4, "fredag": 4,
    "sat": 5, "saturday": 5, "lö": 5, "lör": 5, "lördag": 5,
    "sun": 6, "sunday": 6, "sö": 6, "sön": 6, "söndag": 6,
}


def _parse_weekday(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid weekday: {value!r}")
    if isinstance(value, int):
        if 0 <= value <= 6:
            return value
        raise ValueError(f"weekday out of range: {value}")
    key = str(value).strip().casefold()
    if key in _WEEKDAYS:
        return _WEEKDAYS[key]
    raise ValueError(f"unrecognised weekday: {value!r}")


def _parse_time(value: Any) -> time:
    if isinstance(value, time):
        return value
    text = str(value).strip()
    parts = text.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return time(hour=hour, minute=minute)


@dataclass(slots=True)
class SlotPredicate:
    """A preference over slots expressed in local (Europe/Stockholm) terms.

    All conditions are ANDed. ``open_from``/``open_to`` bound the slot's local
    opening time; a slot matches when its local open time is within the window.
    An empty predicate matches every bookable slot.
    """

    weekdays: frozenset[int] | None = None
    open_from: time | None = None
    open_to: time | None = None
    route_group: int | None = None
    only_bookable: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SlotPredicate:
        data = data or {}
        weekdays: frozenset[int] | None = None
        raw_days = data.get("weekdays") if "weekdays" in data else data.get("weekday")
        if raw_days is not None:
            if isinstance(raw_days, (str, int)):
                raw_days = [raw_days]
            weekdays = frozenset(_parse_weekday(d) for d in raw_days)
        return cls(
            weekdays=weekdays,
            open_from=_parse_time(data["open_from"]) if data.get("open_from") else None,
            open_to=_parse_time(data["open_to"]) if data.get("open_to") else None,
            route_group=data.get("route_group"),
            only_bookable=bool(data.get("only_bookable", True)),
        )

    def matches(self, slot: Slot) -> bool:
        if self.only_bookable and not slot.bookable:
            return False
        if self.route_group is not None and slot.route_group != self.route_group:
            return False
        local_open = slot.local_open
        if self.weekdays is not None:
            if local_open is None or local_open.weekday() not in self.weekdays:
                return False
        if self.open_from is not None or self.open_to is not None:
            if local_open is None:
                return False
            t = local_open.timetz().replace(tzinfo=None)
            if self.open_from is not None and t < self.open_from:
                return False
            if self.open_to is not None and t > self.open_to:
                return False
        return True


def find_matching(slots: Iterable[Slot], predicate: SlotPredicate) -> list[Slot]:
    """All slots satisfying the predicate, in the order supplied."""
    return [s for s in slots if predicate.matches(s)]


def cheapest_matching(slots: Iterable[Slot], predicate: SlotPredicate) -> Slot | None:
    """Cheapest slot matching the predicate.

    Wide delivery windows are frequently the cheapest, so this is a genuinely
    useful selector. Slots without a parseable price sort last.
    """
    matches = find_matching(slots, predicate)
    if not matches:
        return None
    return min(matches, key=lambda s: (s.price is None, s.price if s.price is not None else 0.0))


@dataclass(slots=True)
class SlotPage:
    """One page of slots plus the current selection echo."""

    slots: list[Slot]
    selection: SlotSelection | None
    has_earlier: bool = False
    has_later: bool = False
    from_index: int | None = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


class SlotsClient:
    """List delivery slots and select one on demand."""

    def __init__(self, session: MathemSession) -> None:
        self._session = session

    @staticmethod
    def _parse(data: dict[str, Any]) -> SlotPage:
        # The API returns deliverySlots at the top level. Fall back to the
        # slotData nesting for resilience against shape changes.
        raw_slots = data.get("deliverySlots")
        if raw_slots is None:
            raw_slots = (data.get("slotData") or {}).get("deliverySlots")
        slots = [Slot.from_api(s) for s in (raw_slots or [])]
        selection_raw = data.get("deliverySlot")
        selection = SlotSelection.from_api(selection_raw) if selection_raw else None
        return SlotPage(
            slots=slots,
            selection=selection,
            has_earlier=bool(data.get("hasEarlier")),
            has_later=bool(data.get("hasLater")),
            from_index=data.get("fromIndex"),
            raw=data,
        )

    async def list_slots(self, *, num_days: int = NUM_DAYS, from_index: int = 0) -> SlotPage:
        params = {"num-days": num_days, "from-index": from_index}
        data = await self._session.get("/slot-picker/slots/", params=params)
        return self._parse(data)

    async def list_slots_range(self, *, days: int = NUM_DAYS) -> list[Slot]:
        """List slots across ``days`` days, paging forward while more exist."""
        collected: list[Slot] = []
        from_index = 0
        pages = max(1, -(-days // NUM_DAYS))  # ceil(days / NUM_DAYS)
        for _ in range(pages):
            page = await self.list_slots(num_days=NUM_DAYS, from_index=from_index)
            collected.extend(page.slots)
            if not page.has_later:
                break
            from_index += NUM_DAYS
        return collected

    async def set_slot(
        self,
        slot_id: int,
        *,
        is_unattended: bool,
        delivery_address_id: int,
        num_days: int = NUM_DAYS,
        from_index: int = 0,
    ) -> SlotPage:
        """Select (or change) the delivery slot. Idempotent, no create/update split."""
        params = {"num-days": num_days, "from-index": from_index}
        payload = {
            "deliverySlotId": int(slot_id),
            "isUnattendedDelivery": bool(is_unattended),
            "inModal": True,
            "deliveryAddressId": int(delivery_address_id),
        }
        data = await self._session.post("/slot-picker/info/", params=params, json=payload)
        return self._parse(data)

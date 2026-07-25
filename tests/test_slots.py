"""Slot predicate matching, with the DST case the spec calls out."""

from __future__ import annotations

from mathem_client.models import Slot
from mathem_client.slots import SlotPredicate, SlotsClient, cheapest_matching, find_matching


def _slot(slot_id, open_z, close_z, *, price="19 kr", full=False, unavailable=False):
    return Slot.from_api(
        {
            "id": slot_id,
            "openDatetime": open_z,
            "closeDatetime": close_z,
            "cutoffTime": close_z,
            "price": price,
            "isFull": full,
            "isUnavailable": unavailable,
            "routeGroup": 1,
            "routeGroupStr": "Morning",
        }
    )


def test_utc_converts_to_local_across_dst():
    # 06:00 local is 04:00Z in summer and 05:00Z in winter.
    summer = _slot(1, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z")
    winter = _slot(2, "2026-01-15T05:00:00Z", "2026-01-15T11:00:00Z")
    assert summer.local_open.hour == 6
    assert winter.local_open.hour == 6


def test_time_window_predicate_is_dst_correct():
    summer_06 = _slot(1, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z")  # 06:00 local
    winter_06 = _slot(2, "2026-01-15T05:00:00Z", "2026-01-15T11:00:00Z")  # 06:00 local
    summer_07 = _slot(3, "2026-07-25T05:00:00Z", "2026-07-25T11:00:00Z")  # 07:00 local
    predicate = SlotPredicate.from_dict({"open_from": "06:00", "open_to": "06:30"})
    assert predicate.matches(summer_06)
    assert predicate.matches(winter_06)  # would fail if we matched on UTC
    assert not predicate.matches(summer_07)


def test_weekday_predicate():
    slot = _slot(1, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z")
    weekday = slot.local_weekday
    assert SlotPredicate.from_dict({"weekdays": [weekday]}).matches(slot)
    other = (weekday + 1) % 7
    assert not SlotPredicate.from_dict({"weekdays": [other]}).matches(slot)


def test_swedish_weekday_names():
    slot = _slot(1, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z")  # a Saturday
    assert slot.local_weekday == 5
    assert SlotPredicate.from_dict({"weekdays": ["lördag"]}).matches(slot)
    assert SlotPredicate.from_dict({"weekdays": ["sat"]}).matches(slot)


def test_cheapest_matching_ignores_full_and_unavailable():
    cheap_but_full = _slot(1, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z", price="9 kr", full=True)
    mid = _slot(2, "2026-07-25T04:00:00Z", "2026-07-25T06:00:00Z", price="59 kr")
    wide_cheap = _slot(3, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z", price="19 kr")
    chosen = cheapest_matching([cheap_but_full, mid, wide_cheap], SlotPredicate())
    assert chosen.id == 3  # 9 kr slot is full, so 19 kr wide window wins


def test_find_matching_only_bookable():
    ok = _slot(1, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z")
    full = _slot(2, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z", full=True)
    assert [s.id for s in find_matching([ok, full], SlotPredicate())] == [1]


def test_empty_predicate_matches_all_bookable():
    a = _slot(1, "2026-07-25T04:00:00Z", "2026-07-25T11:00:00Z")
    b = _slot(2, "2026-07-26T05:00:00Z", "2026-07-26T09:00:00Z")
    assert len(find_matching([a, b], SlotPredicate())) == 2


def test_parse_reads_top_level_delivery_slots():
    # The live API returns deliverySlots at the top level, not under slotData.
    payload = {
        "deliverySlots": [
            {
                "id": 1468590,
                "routeGroup": 1,
                "routeGroupStr": "Morning",
                "openDatetime": "2026-07-26T04:00:00Z",
                "closeDatetime": "2026-07-26T09:00:00Z",
                "price": "19 kr",
                "isFull": False,
                "isSelected": False,
            }
        ],
        "hasEarlier": False,
        "hasLater": True,
        "fromIndex": 0,
    }
    page = SlotsClient._parse(payload)
    assert [s.id for s in page.slots] == [1468590]
    assert page.slots[0].local_open.hour == 6  # 04:00Z -> 06:00 local (summer)
    assert page.has_later is True
    assert page.from_index == 0


def test_parse_falls_back_to_slotdata_nesting():
    payload = {
        "slotData": {
            "deliverySlots": [
                {"id": 2, "openDatetime": "2026-07-26T04:00:00Z", "closeDatetime": "2026-07-26T09:00:00Z", "price": "19 kr"}
            ]
        }
    }
    assert [s.id for s in SlotsClient._parse(payload).slots] == [2]

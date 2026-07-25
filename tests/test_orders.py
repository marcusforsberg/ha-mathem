"""Orders parsing.

The live ``/orders/`` endpoint returns snake_case even under the camel header,
carries no ISO datetimes, and expresses the delivery window as a localised
string. These tests pin the casing tolerance and the window reconstruction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mathem_client.models import STORE_TZ, parse_delivery_window
from mathem_client.orders import OrdersClient

# 2026-07-25 is a Saturday (weekday 5), local noon.
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=STORE_TZ)


# -- window parsing --------------------------------------------------------


def test_parse_relative_tomorrow_window():
    start, end = parse_delivery_window("imorgon, 06:00 - 11:00", NOW)
    assert start.date().isoformat() == "2026-07-26"
    assert (start.hour, start.minute) == (6, 0)
    assert (end.hour, end.minute) == (11, 0)
    assert start.tzinfo is not None


def test_parse_today():
    start, _ = parse_delivery_window("idag, 07:00 - 09:00", NOW)
    assert start.date().isoformat() == "2026-07-25"


def test_parse_weekday_resolves_next_occurrence():
    start, _ = parse_delivery_window("söndag, 08:00 - 10:00", NOW)  # NOW is Saturday
    assert start.date().isoformat() == "2026-07-26"


def test_parse_absolute_past_form_single_time():
    start, end = parse_delivery_window("sön 5. juli, 09:27", NOW)
    assert start.date().isoformat() == "2026-07-05"
    assert (start.hour, start.minute) == (9, 27)
    assert start == end


def test_parse_unparseable_returns_none():
    assert parse_delivery_window("när som helst", NOW) == (None, None)
    assert parse_delivery_window("", NOW) == (None, None)
    assert parse_delivery_window(None, NOW) == (None, None)


def test_parse_anchors_to_stockholm_regardless_of_now_tz():
    # 21:00Z is 23:00 in Stockholm summer; "imorgon" is still the next local day.
    utc_now = datetime(2026, 7, 25, 21, 0, tzinfo=timezone.utc)
    start, _ = parse_delivery_window("imorgon, 06:00 - 11:00", utc_now)
    assert start.date().isoformat() == "2026-07-26"


# -- orders response parsing ----------------------------------------------


class _OrdersSession:
    def __init__(self, payload):
        self.payload = payload

    async def get(self, path, *, params=None):
        assert path == "/orders/"
        return self.payload


_SNAKE = {
    "get_more_url": None,
    "has_more": True,
    "results": [
        {
            "type": "active_orders",
            "name": "Nuvarande beställningar",
            "orders": [
                {
                    "status": {
                        "title": "Din beställning är bekräftad",
                        "content": "…",
                        "payment_status": "paid",
                        "payment_status_state": "ok",
                        "can_be_ordered_again": True,
                    },
                    "order_number": "abc123",
                    "delivery": {
                        "delivery_address": "Exempelgatan 1, 111 11 Stockholm",
                        "delivery_time": "imorgon, 06:00 - 11:00",
                        "cutoff_text": "Du har till 20:00 idag …",
                        "tracking": {"data": {"is_doorstep_delivery": True, "live_tracked_order": None}},
                    },
                }
            ],
        },
        {
            "type": "month",
            "name": "Juli",
            "orders": [
                {
                    "status": {"title": "Levererad"},
                    "order_number": "old1",
                    "delivery": {"delivery_time": "sön 5. juli, 09:27", "delivery_address": "x"},
                }
            ],
        },
    ],
}


async def test_get_orders_parses_snake_case():
    result = await OrdersClient(_OrdersSession(_SNAKE)).get_orders()
    assert result.has_more is True
    assert len(result.orders) == 2
    assert len(result.active) == 1

    order = result.next_delivery
    assert order.order_number == "abc123"
    assert order.delivery_address.startswith("Exempelgatan")
    assert order.delivery_time_text == "imorgon, 06:00 - 11:00"
    assert order.status_title == "Din beställning är bekräftad"
    assert order.payment_status == "paid"
    assert order.is_doorstep_delivery is True
    assert order.live_tracked_order is None

    start, end = order.window(NOW)
    assert start.date().isoformat() == "2026-07-26"
    assert start.hour == 6 and end.hour == 11


async def test_get_orders_tolerates_camel_case():
    camel = {
        "getMoreUrl": None,
        "hasMore": False,
        "results": [
            {
                "type": "active_orders",
                "orders": [
                    {
                        "status": {"title": "Bekräftad", "canBeOrderedAgain": True, "paymentStatus": "paid"},
                        "orderNumber": "z9",
                        "delivery": {
                            "deliveryAddress": "A",
                            "deliveryTime": "imorgon, 06:00 - 11:00",
                            "tracking": {"data": {"isDoorstepDelivery": False, "liveTrackedOrder": {"active": 1}}},
                        },
                    }
                ],
            }
        ],
    }
    result = await OrdersClient(_OrdersSession(camel)).get_orders()
    order = result.next_delivery
    assert order.order_number == "z9"
    assert order.delivery_address == "A"
    assert order.can_be_ordered_again is True
    assert order.is_doorstep_delivery is False
    assert bool(order.live_tracked_order) is True

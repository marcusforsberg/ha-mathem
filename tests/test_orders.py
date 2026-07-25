"""Orders parsing.

The live ``/orders/`` endpoint returns snake_case even under the camel header,
carries no ISO datetimes, and expresses the delivery window as a localised
string. These tests pin the casing tolerance and the window reconstruction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mathem_client.models import STORE_TZ, OrderDetail, parse_delivery_window
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


# -- order detail ----------------------------------------------------------

# Mirrors the live GET /orders/{number}/ shape (camelCase, grouped lines, and
# fee/credit/total rows in extraItemGroups). All values are invented.
_DETAIL = {
    "summary": {
        "status": {"title": "Kvitto", "paymentStatus": "Betald", "canBeOrderedAgain": True},
        "orderNumber": "a1b2c3",
        "delivery": {
            "deliveryAddress": "Exempelgatan 1, 111 11 Stockholm",
            "deliveryTime": "sön 5. juli, 09:27",
        },
        "currency": "SEK",
        "grossAmount": 120.5,
        "invoiceLinks": [],
    },
    "items": {
        "productCount": 4,
        "productCountDelivered": 4,
        "itemGroups": [
            {
                "type": "category",
                "name": "Skafferi",
                "items": [
                    {"productId": 111, "description": "Havregryn 1 kg", "quantity": 2.0,
                     "uncreditedQuantity": 2.0, "grossAmount": 40.0, "currency": "SEK",
                     "vatText": "Moms 12%"},
                    {"productId": 222, "description": "Rapsolja 900 ml", "quantity": 1.0,
                     "uncreditedQuantity": 0.0, "grossAmount": 30.0, "currency": "SEK",
                     "vatText": "Moms 12%"},
                ],
            },
            {
                "type": "category",
                "name": "Frukt & grönt",
                "items": [
                    {"productId": 333, "description": "Bananer", "quantity": 1.0,
                     "uncreditedQuantity": 1.0, "grossAmount": 25.0, "currency": "SEK",
                     "vatText": "Moms 12%"},
                ],
            },
        ],
        "extraItemGroups": [
            {"displayStyle": "secondary", "items": [{"description": "4 varor", "grossAmount": 95.0}]},
            {"displayStyle": "secondary", "items": [
                {"description": "Rapsolja 900 ml", "grossAmount": -30.0},
                {"description": "Leverans", "grossAmount": 19.0},
                {"description": "Lådor", "grossAmount": 14.0},
            ]},
            {"displayStyle": "primary", "items": [{"description": "Totalt inkl. moms", "grossAmount": 120.5}]},
        ],
        "alertBanner": None,
    },
}


def test_order_detail_flattens_grouped_lines_with_category():
    detail = OrderDetail.from_api(_DETAIL)
    assert detail.order_number == "a1b2c3"
    assert detail.total == 120.5
    assert detail.currency == "SEK"
    assert detail.product_count == 4
    assert [(l.product_id, l.category) for l in detail.lines] == [
        (111, "Skafferi"), (222, "Skafferi"), (333, "Frukt & grönt")
    ]
    assert detail.lines[0].quantity == 2.0
    assert detail.lines[0].gross_amount == 40.0


def test_order_detail_lines_total_excludes_fees():
    detail = OrderDetail.from_api(_DETAIL)
    assert detail.lines_total == 95.0  # 40 + 30 + 25, no delivery/box fees


def test_order_detail_exposes_fees_and_credits_in_order():
    detail = OrderDetail.from_api(_DETAIL)
    assert [(a.description, a.gross_amount) for a in detail.adjustments] == [
        ("4 varor", 95.0),
        ("Rapsolja 900 ml", -30.0),
        ("Leverans", 19.0),
        ("Lådor", 14.0),
        ("Totalt inkl. moms", 120.5),
    ]


def test_fully_credited_line_is_flagged():
    detail = OrderDetail.from_api(_DETAIL)
    by_id = {l.product_id: l for l in detail.lines}
    assert by_id[222].is_fully_credited is True   # uncredited 0 of 1
    assert by_id[111].is_fully_credited is False


def test_order_detail_reuses_summary_for_status_and_delivery():
    detail = OrderDetail.from_api(_DETAIL)
    assert detail.order.status_title == "Kvitto"
    assert detail.order.payment_status == "Betald"
    assert detail.order.delivery_time_text == "sön 5. juli, 09:27"
    start, _ = detail.order.window(NOW)
    assert start.date().isoformat() == "2026-07-05"


def test_order_detail_tolerates_missing_items():
    detail = OrderDetail.from_api({"summary": {"orderNumber": "x", "grossAmount": 0}})
    assert detail.lines == [] and detail.adjustments == []
    assert detail.lines_total == 0


async def test_get_latest_order_picks_the_first_listed():
    class _S:
        def __init__(self): self.paths = []
        async def get(self, path, *, params=None):
            self.paths.append(path)
            if path == "/orders/":
                return _SNAKE
            return _DETAIL
    session = _S()
    detail = await OrdersClient(session).get_latest_order()
    assert session.paths == ["/orders/", "/orders/abc123/"]  # active order first
    assert detail.order_number == "a1b2c3"


def test_tracking_step_distinguishes_delivered_from_upcoming():
    delivered = OrderDetail.from_api({
        "summary": {"orderNumber": "d1", "grossAmount": 10,
                    "delivery": {"deliveryTime": "sön 5. juli, 09:27",
                                 "tracking": {"stepName": "DELIVERED", "data": {}}}},
    })
    upcoming = OrderDetail.from_api({
        "summary": {"orderNumber": "u1", "grossAmount": 10,
                    "delivery": {"deliveryTime": "imorgon, 06:00 - 11:00",
                                 "tracking": {"stepName": "CONFIRMED", "data": {}}}},
    })
    assert delivered.order.tracking_step == "DELIVERED"
    assert delivered.order.is_delivered is True
    assert upcoming.order.is_delivered is False
    # Unknown/missing tracking must not claim delivered.
    assert OrderDetail.from_api({"summary": {"orderNumber": "x"}}).order.is_delivered is False

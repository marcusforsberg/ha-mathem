"""Order history and the active-order lookup that feeds the delivery sensor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .models import Order, OrderDetail, _pick
from .session import MathemSession

_LOGGER = logging.getLogger(__name__)

ACTIVE_GROUP_TYPES = ("active_orders", "activeOrders")


@dataclass(slots=True)
class OrdersResult:
    """The parsed ``GET /orders/`` payload."""

    orders: list[Order]  # flattened, all groups
    active: list[Order]  # only the active_orders group
    has_more: bool
    get_more_url: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def latest(self) -> Order | None:
        """The most recent order, active ones first as the API returns them."""
        return self.orders[0] if self.orders else None

    @property
    def upcoming(self) -> list[Order]:
        """Orders that have not been delivered yet, however they are grouped.

        Mathem regroups an order once it ships, so membership of the
        ``active_orders`` group is not a dependable test. A tracking step that
        is present and not DELIVERED is.
        """
        return [o for o in self.orders if o.tracking_step and not o.is_delivered]

    @property
    def next_delivery(self) -> Order | None:
        """The imminent order, whether or not the API still calls it active.

        Prefers the active group, then falls back to the first undelivered
        order, so the sensor keeps working while an order is out for delivery.
        Its window text is turned into datetimes by ``Order.window``.
        """
        if self.active:
            return self.active[0]
        upcoming = self.upcoming
        return upcoming[0] if upcoming else None


class OrdersClient:
    def __init__(self, session: MathemSession) -> None:
        self._session = session

    async def get_orders(self) -> OrdersResult:
        data = await self._session.get("/orders/")
        orders: list[Order] = []
        active: list[Order] = []
        for group in _pick(data, "results", default=[]) or []:
            group_orders = [Order.from_api(o) for o in (_pick(group, "orders", default=[]) or [])]
            orders.extend(group_orders)
            if _pick(group, "type") in ACTIVE_GROUP_TYPES:
                active.extend(group_orders)
        if not active and orders:
            # The active group is how the API used to mark an in-flight order.
            # Log what it actually sent when that group is missing, so a
            # regrouping is diagnosable instead of silently blanking the sensor.
            _LOGGER.debug(
                "no active order group; groups=%s steps=%s",
                [_pick(g, "type") for g in _pick(data, "results", default=[]) or []],
                [(o.order_number, o.tracking_step) for o in orders[:3]],
            )
        return OrdersResult(
            orders=orders,
            active=active,
            has_more=bool(_pick(data, "has_more", "hasMore")),
            get_more_url=_pick(data, "get_more_url", "getMoreUrl"),
            raw=data,
        )

    async def get_order(self, order_number: str) -> OrderDetail:
        """Fetch one order with its itemised lines.

        The order list exposes only totals, so the lines come from this
        endpoint. Unlike the list, it responds in camelCase.
        """
        data = await self._session.get(f"/orders/{order_number}/")
        return OrderDetail.from_api(data)

    async def get_latest_order(self) -> OrderDetail | None:
        """Fetch the most recent order in full, or ``None`` if there are none."""
        result = await self.get_orders()
        latest = result.latest
        if latest is None or latest.order_number is None:
            return None
        return await self.get_order(latest.order_number)

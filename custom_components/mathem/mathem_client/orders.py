"""Order history and the active-order lookup that feeds the delivery sensor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .models import Order, _pick
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
    def next_delivery(self) -> Order | None:
        """The imminent active order.

        The API returns active orders first, so the first one is the next
        delivery. Its window text is turned into datetimes by ``Order.window``.
        """
        return self.active[0] if self.active else None


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
        return OrdersResult(
            orders=orders,
            active=active,
            has_more=bool(_pick(data, "has_more", "hasMore")),
            get_more_url=_pick(data, "get_more_url", "getMoreUrl"),
            raw=data,
        )

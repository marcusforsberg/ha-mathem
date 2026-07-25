"""Data coordinator.

30-minute base poll, dropping to a couple of minutes on delivery day. The poll
is mostly a safety net for changes made in the Mathem app plus a session
keep-alive / early 403 detector. Mutating services push fresh state in with
``async_set_updated_data`` instead of triggering a refetch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BASE_POLL_INTERVAL, DELIVERY_DAY_POLL_INTERVAL, DOMAIN
from .mathem_client import MathemAuthError, MathemClient
from .mathem_client.models import Cart, SlotSelection
from .mathem_client.orders import OrdersResult
from .mathem_client.models import Order

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MathemData:
    """Everything the entities render, all served from here."""

    cart: Cart | None = None
    orders: OrdersResult | None = None
    # The most recent slot selection (from set_delivery_slot). The cart-side
    # hold is not durable, so this is display-only and may be stale/None.
    selection: SlotSelection | None = None

    @property
    def next_delivery(self) -> Order | None:
        return self.orders.next_delivery if self.orders else None


class MathemCoordinator(DataUpdateCoordinator[MathemData]):
    """Polls cart and orders; entities never call the API themselves."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: MathemClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=BASE_POLL_INTERVAL,
            config_entry=entry,
        )
        self.client = client

    async def _async_update_data(self) -> MathemData:
        try:
            cart = await self.client.cart.get_cart()
            orders = await self.client.orders.get_orders()
        except MathemAuthError as err:
            # Surface as a reauth-worthy failure; the 30-day sessionid expired.
            raise UpdateFailed(f"authentication failed: {err}") from err

        # Preserve the last known slot selection across polls (it is not part of
        # the cart/orders payloads and is only refreshed on set_delivery_slot).
        selection = self.data.selection if self.data else None
        data = MathemData(cart=cart, orders=orders, selection=selection)
        self._retune_interval(data)
        return data

    def apply_cart(self, cart: Cart) -> None:
        """Push a cart returned by a mutation straight into state."""
        current = self.data or MathemData()
        self.async_set_updated_data(replace(current, cart=cart))

    def apply_selection(self, selection: SlotSelection) -> None:
        current = self.data or MathemData()
        self.async_set_updated_data(replace(current, selection=selection))

    def _retune_interval(self, data: MathemData) -> None:
        """Tighten the poll on delivery day, relax it otherwise."""
        interval = BASE_POLL_INTERVAL
        order = data.next_delivery
        if order is not None:
            now = datetime.now(timezone.utc)
            start, end = order.window(now)
            in_window = start is not None and end is not None and start <= now <= end
            if bool(order.live_tracked_order) or in_window:
                interval = DELIVERY_DAY_POLL_INTERVAL
        if interval != self.update_interval:
            _LOGGER.debug("retuning poll interval to %s", interval)
            self.update_interval = interval

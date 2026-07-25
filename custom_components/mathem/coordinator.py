"""Data coordinator.

Polls on a configurable base interval, dropping to a shorter configurable
interval while an order is inside its delivery window or being live tracked. The
poll is mostly a safety net for changes made in the Mathem app plus a session
keep-alive / early 401 detector. Mutating services push fresh state in with
``async_set_updated_data`` instead of triggering a refetch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .mathem_client import MathemAuthError, MathemClient, MathemError
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

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: MathemClient,
        *,
        base_interval: timedelta,
        delivery_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=base_interval,
            config_entry=entry,
        )
        self.client = client
        self._base_interval = base_interval
        self._delivery_interval = delivery_interval

    async def _async_update_data(self) -> MathemData:
        try:
            data = await self._fetch()
        except MathemAuthError:
            # The sessionid is not durable (it lives only in the in-memory
            # cookie jar and expires), so re-login once before giving up.
            try:
                await self._relogin()
                data = await self._fetch()
            except MathemAuthError as err:
                raise ConfigEntryAuthFailed(f"authentication failed: {err}") from err
            except MathemError as err:
                raise UpdateFailed(f"error talking to Mathem: {err}") from err
        except MathemError as err:
            raise UpdateFailed(f"error talking to Mathem: {err}") from err
        self._retune_interval(data)
        return data

    async def _fetch(self) -> MathemData:
        cart = await self.client.cart.get_cart()
        orders = await self.client.orders.get_orders()
        # Preserve the last known slot selection across polls (it is not part of
        # the cart/orders payloads and is only refreshed on set_delivery_slot).
        selection = self.data.selection if self.data else None
        return MathemData(cart=cart, orders=orders, selection=selection)

    async def _relogin(self) -> None:
        creds = self.config_entry.data
        await self.client.session.login(creds[CONF_USERNAME], creds[CONF_PASSWORD])

    def apply_cart(self, cart: Cart) -> None:
        """Push a cart returned by a mutation straight into state."""
        current = self.data or MathemData()
        self.async_set_updated_data(replace(current, cart=cart))

    def apply_selection(self, selection: SlotSelection) -> None:
        current = self.data or MathemData()
        self.async_set_updated_data(replace(current, selection=selection))

    def _retune_interval(self, data: MathemData) -> None:
        """Tighten the poll during the delivery window, relax it otherwise.

        Uses the configured base interval as the resting value (rather than a
        constant), so a non-default poll interval is respected.
        """
        interval = self._base_interval
        order = data.next_delivery
        if order is not None:
            now = datetime.now(timezone.utc)
            start, end = order.window(now)
            in_window = start is not None and end is not None and start <= now <= end
            if bool(order.live_tracked_order) or in_window:
                interval = self._delivery_interval
        if interval != self.update_interval:
            _LOGGER.debug("retuning poll interval to %s", interval)
            self.update_interval = interval

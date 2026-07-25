"""Cart read and mutation.

One endpoint handles every mutation. Quantities are **deltas, not absolutes**:
there is no PATCH, no DELETE, and no ``quantity: 0`` semantic. Removal is a
decrement to zero.
"""

from __future__ import annotations

import logging

from .models import Cart
from .session import MathemSession

_LOGGER = logging.getLogger(__name__)

_CART_PARAMS = {"group-by": "recipes"}  # hyphen, not underscore


class CartClient:
    """Read the cart and adjust it by deltas."""

    def __init__(self, session: MathemSession) -> None:
        self._session = session

    async def get_cart(self) -> Cart:
        data = await self._session.get("/cart/", params=_CART_PARAMS)
        return Cart.from_api(data)

    async def _adjust(self, product_id: int, delta: int) -> Cart:
        """The single mutation primitive: add ``delta`` to a product's quantity.

        Positive adds/increases, negative decreases/removes. The tracking and
        ``fromListItemPosition`` fields the live client sends are attribution
        analytics and are deliberately omitted. The response is the full
        updated cart, returned as-is so callers need not refetch.
        """
        if delta == 0:
            # No verified no-op semantic; just return current state.
            return await self.get_cart()
        payload = {"items": [{"productId": int(product_id), "quantity": int(delta)}]}
        data = await self._session.post(
            "/cart/items/", params=_CART_PARAMS, json=payload
        )
        return Cart.from_api(data)

    async def add_item(self, product_id: int, quantity: int = 1) -> Cart:
        """Add ``quantity`` units of a product (a positive delta)."""
        if quantity <= 0:
            raise ValueError("add_item quantity must be positive")
        return await self._adjust(product_id, quantity)

    async def set_quantity(self, product_id: int, quantity: int) -> Cart:
        """Set an absolute quantity by reading the cart and sending the diff."""
        if quantity < 0:
            raise ValueError("set_quantity target must be >= 0")
        cart = await self.get_cart()
        current = cart.quantity_of(product_id)
        delta = quantity - current
        if delta == 0:
            return cart
        return await self._adjust(product_id, delta)

    async def remove_item(self, product_id: int) -> Cart:
        """Remove a product entirely by sending exactly ``-current``.

        Reads the current quantity and decrements by that amount rather than
        relying on unverified clamping for an overshoot.
        """
        cart = await self.get_cart()
        current = cart.quantity_of(product_id)
        if current == 0:
            return cart
        return await self._adjust(product_id, -current)

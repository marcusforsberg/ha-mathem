"""Standalone Mathem API client.

Imports nothing from Home Assistant. The package is a clean subtree so that
publishing it later is mechanical: push to PyPI, delete this directory, add one
``requirements`` line to the integration's manifest.

Typical use inside Home Assistant::

    session = MathemSession(async_get_clientsession(hass))
    client = MathemClient(session)
    cart = await client.cart.get_cart()

Standalone::

    async with MathemClient.standalone() as client:
        await client.session.login(user, pw)
        print(await client.products.search("mjölk"))
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiohttp

from .cart import CartClient
from .errors import (
    CheckoutForbiddenError,
    MathemAuthError,
    MathemError,
    MathemProtocolError,
    MathemRequestError,
)
from .orders import OrdersClient
from .products import ProductsClient, SearchResult
from .resolve import AliasEntry, AliasMap, Candidate, ResolveResult, ResolveStatus, Resolver
from .session import MathemSession
from .slots import SlotPage, SlotPredicate, SlotsClient, cheapest_matching, find_matching

__all__ = [
    "MathemClient",
    "MathemSession",
    "ProductsClient",
    "CartClient",
    "SlotsClient",
    "OrdersClient",
    "Resolver",
    "AliasMap",
    "AliasEntry",
    "Candidate",
    "ResolveResult",
    "ResolveStatus",
    "SlotPredicate",
    "SlotPage",
    "SearchResult",
    "cheapest_matching",
    "find_matching",
    "MathemError",
    "MathemAuthError",
    "MathemRequestError",
    "MathemProtocolError",
    "CheckoutForbiddenError",
]


class MathemClient:
    """Facade bundling the per-area sub-clients over one session."""

    def __init__(self, session: MathemSession) -> None:
        self.session = session
        self.products = ProductsClient(session)
        self.cart = CartClient(session)
        self.slots = SlotsClient(session)
        self.orders = OrdersClient(session)

    def resolver(
        self,
        aliases: AliasMap,
        profiles: dict,
        *,
        default_profile: str | None,
    ) -> Resolver:
        """Build a resolver bound to this client's product lookups."""
        return Resolver(
            self.products, aliases, profiles, default_profile=default_profile
        )

    @classmethod
    @asynccontextmanager
    async def standalone(cls) -> AsyncIterator["MathemClient"]:
        """Create a client owning its own aiohttp session (non-HA use)."""
        async with aiohttp.ClientSession() as http:
            yield cls(MathemSession(http))

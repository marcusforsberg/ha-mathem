"""Session-level guarantees: the checkout tripwire and the required headers."""

from __future__ import annotations

import aiohttp
import pytest

from mathem_client.errors import CheckoutForbiddenError
from mathem_client.session import MathemSession


async def test_checkout_path_is_refused_before_any_request():
    async with aiohttp.ClientSession() as http:
        session = MathemSession(http)
        with pytest.raises(CheckoutForbiddenError):
            await session.request("GET", "checkout/confirm/")
        with pytest.raises(CheckoutForbiddenError):
            await session.request("POST", "/checkout/confirm/", json={})
        with pytest.raises(CheckoutForbiddenError):
            await session.request("GET", "https://www.mathem.se/api/v1/checkout/confirm/", absolute=True)


def test_required_headers_present():
    session = MathemSession(None)  # header building does not touch the transport
    headers = session._base_headers()
    assert headers["x-client-app"] == "tienda-web"
    assert headers["x-requested-case"] == "camel"
    assert headers["x-language"] == "sv"
    assert headers["x-country"] == "se"
    assert headers["accept"] == "application/json"
    assert headers["origin"] == "https://www.mathem.se"

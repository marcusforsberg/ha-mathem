"""Cart delta semantics: quantities are deltas, removal is a decrement to zero."""

from __future__ import annotations

import pytest
from conftest import FakeCartSession

from mathem_client.cart import CartClient


async def test_add_sends_positive_delta():
    session = FakeCartSession()
    cart = await CartClient(session).add_item(2190, 1)
    assert session.posts[-1] == {"items": [{"productId": 2190, "quantity": 1}]}
    assert cart.quantity_of(2190) == 1
    assert cart.unit_count == 1
    assert cart.line_count == 1


async def test_add_zero_or_negative_rejected():
    with pytest.raises(ValueError):
        await CartClient(FakeCartSession()).add_item(2190, 0)


async def test_set_quantity_sends_difference_up():
    session = FakeCartSession()
    session.quantities[2190] = 1
    await CartClient(session).set_quantity(2190, 3)
    assert session.posts[-1] == {"items": [{"productId": 2190, "quantity": 2}]}
    assert session.quantities[2190] == 3


async def test_set_quantity_sends_difference_down():
    session = FakeCartSession()
    session.quantities[5454] = 3
    await CartClient(session).set_quantity(5454, 1)
    assert session.posts[-1] == {"items": [{"productId": 5454, "quantity": -2}]}


async def test_set_quantity_noop_sends_nothing():
    session = FakeCartSession()
    session.quantities[5454] = 2
    await CartClient(session).set_quantity(5454, 2)
    assert session.posts == []


async def test_remove_sends_exactly_negative_current():
    session = FakeCartSession()
    session.quantities[5454] = 2
    await CartClient(session).remove_item(5454)
    assert session.posts[-1] == {"items": [{"productId": 5454, "quantity": -2}]}
    assert session.quantities[5454] == 0


async def test_remove_absent_item_is_noop():
    session = FakeCartSession()
    await CartClient(session).remove_item(999)
    assert session.posts == []


async def test_summary_lines_named_lookup():
    session = FakeCartSession()
    session.quantities[1] = 1
    cart = await CartClient(session).get_cart()
    assert cart.summary_line("GrossTotalAmount") is not None
    assert cart.summary_line("DeliveryFeeManipulator") is not None
    assert cart.summary_line("nope") is None

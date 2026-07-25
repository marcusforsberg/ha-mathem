"""Delivery-address extraction used by the config flow's auto-detected picker."""

from __future__ import annotations

from config_helpers import extract_addresses


def test_extracts_from_slot_picker_top_level():
    payload = {
        "deliverySlots": [],
        "deliveryAddresses": [
            {"id": 10000001, "streetAddress": "Testgatan 2", "zipCode": "111 11", "city": "Stockholm"},
            {"id": 99, "street": "Testgatan 2", "city": "Stockholm"},
        ],
    }
    addresses = extract_addresses(payload)
    assert addresses[10000001] == "Testgatan 2, 111 11, Stockholm"
    assert addresses[99] == "Testgatan 2, Stockholm"


def test_extracts_from_cart_info():
    payload = {"cartInfo": {"deliveryAddress": {"id": 7, "streetAddress": "Gata 1", "city": "Ort"}}}
    assert extract_addresses(payload) == {7: "Gata 1, Ort"}


def test_container_entry_with_only_a_name_is_still_picked_up():
    payload = {"deliveryAddresses": [{"id": 3, "displayName": "Hemma"}]}
    assert extract_addresses(payload) == {3: "Hemma"}


def test_unrelated_id_name_objects_are_not_mistaken_for_addresses():
    # No deliveryAddress container, so the strict fallback must ignore products.
    payload = {"items": [{"id": 1, "name": "Mjölk"}, {"id": 2, "name": "Bröd"}]}
    assert extract_addresses(payload) == {}


def test_empty_when_nothing_addresslike():
    assert extract_addresses({"foo": "bar"}) == {}

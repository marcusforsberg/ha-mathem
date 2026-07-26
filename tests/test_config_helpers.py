"""Delivery-address extraction used by the config flow's auto-detected picker.

The payloads here mirror what the live API returns.
"""

from __future__ import annotations

from config_helpers import extract_addresses

# Field names and shape are verbatim from GET /slot-picker/slots/; the
# values are synthetic.
SLOT_PICKER = {
    "deliverySlots": [],
    "deliveryAddresses": [
        {
            "id": 10000001,
            "addressDisplay": "Testgatan 2",
            "addressDisplayFull": "Testgatan 2, 111 11 Stockholm",
            "isPrimary": True,
            "recipientName": "Test Person",
            "isDeliveryAvailable": True,
            "userSpecifiedName": None,
            "isBoatDelivery": False,
        },
        {
            "id": 10000002,
            "addressDisplay": "Andra Vägen 5",
            "addressDisplayFull": "Andra Vägen 5, 222 22 Exempelby",
            "isPrimary": False,
            "recipientName": "Test Person",
            "isDeliveryAvailable": True,
            "userSpecifiedName": None,
            "isBoatDelivery": False,
        },
    ],
}


def test_extracts_both_addresses_from_slot_picker():
    addresses = extract_addresses(SLOT_PICKER)
    assert addresses == {
        10000001: "Testgatan 2, 111 11 Stockholm",
        10000002: "Andra Vägen 5, 222 22 Exempelby",
    }


def test_primary_address_is_listed_first():
    # Insertion order decides the picker's default, so primary must lead even
    # when the payload lists it second.
    reversed_payload = {"deliveryAddresses": list(reversed(SLOT_PICKER["deliveryAddresses"]))}
    assert list(extract_addresses(reversed_payload)) == [10000001, 10000002]


def test_extracts_active_address_from_cart_info():
    payload = {
        "cartInfo": {
            "deliveryAddress": {
                "id": 10000001,
                "addressDisplay": "Testgatan 2",
                "addressDisplayFull": "Testgatan 2, 111 11 Stockholm",
                "isPrimary": True,
            }
        }
    }
    assert extract_addresses(payload) == {10000001: "Testgatan 2, 111 11 Stockholm"}


def test_nickname_and_unavailable_are_surfaced():
    payload = {
        "deliveryAddresses": [
            {
                "id": 1,
                "addressDisplayFull": "Testgatan 2, 111 11 Stockholm",
                "userSpecifiedName": "Sommarstuga",
                "isDeliveryAvailable": False,
            }
        ]
    }
    label = extract_addresses(payload)[1]
    assert "Sommarstuga" in label
    assert "delivery unavailable" in label


def test_falls_back_to_street_zip_city_shape():
    payload = {"deliveryAddresses": [{"id": 7, "street": "Gata 1", "zipCode": "111 11", "city": "Ort"}]}
    assert extract_addresses(payload) == {7: "Gata 1, 111 11, Ort"}


def test_unrelated_id_name_objects_are_not_mistaken_for_addresses():
    # No deliveryAddress container, so the strict fallback must ignore products.
    payload = {"items": [{"id": 1, "name": "Mjölk"}, {"id": 2, "name": "Bröd"}]}
    assert extract_addresses(payload) == {}


def test_empty_when_nothing_addresslike():
    assert extract_addresses({"foo": "bar"}) == {}
    assert extract_addresses({"deliveryAddresses": None}) == {}

"""Parsing helpers and model shaping."""

from __future__ import annotations

from datetime import timezone

from conftest import make_category, make_detail, make_product

from mathem_client.models import (
    Cart,
    ProductDetail,
    _parse_dt,
    _parse_price,
)


def test_parse_price_decimal_and_display_strings():
    assert _parse_price("15.95") == 15.95
    assert _parse_price("19 kr") == 19.0
    assert _parse_price("19\xa0kr") == 19.0  # non-breaking space
    assert _parse_price("9,50") == 9.5
    assert _parse_price(20) == 20.0
    assert _parse_price(None) is None
    assert _parse_price("gratis") is None


def test_parse_dt_is_utc_aware():
    dt = _parse_dt("2026-07-25T18:00:00Z")
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)
    assert _parse_dt(None) is None


def test_cart_flattens_groups_and_counts_units():
    payload = {
        "id": "c1",
        "productQuantityCount": 5,  # units, not lines
        "displayPrice": "120.00",
        "totalGrossAmount": "139.00",
        "currency": "SEK",
        "summaryLines": [{"type": "GrossTotalAmount", "value": "139.00"}],
        "groups": [
            {"items": [
                {"itemId": 1, "product": make_product(10, "A"), "quantity": 2},
                {"itemId": 2, "product": make_product(11, "B"), "quantity": 3},
            ]}
        ],
    }
    cart = Cart.from_api(payload)
    assert cart.unit_count == 5
    assert cart.line_count == 2
    assert cart.quantity_of(10) == 2
    assert cart.summary_line("GrossTotalAmount").value == "139.00"


def test_detail_allergens_absent_is_none_not_empty():
    detail = ProductDetail.from_api(make_detail(1, "X", ingredients="mjöl", allergens=None))
    assert detail.allergens_text is None  # unknown, never "safe"
    assert detail.ingredients_text == "mjöl"


def test_detail_allergens_present():
    detail = ProductDetail.from_api(make_detail(1, "X", ingredients="mjöl", allergens="vete, korn"))
    assert detail.allergens_text == "vete, korn"


def test_classification_excludes_prismatch_tree():
    detail = ProductDetail.from_api(
        make_detail(
            1,
            "X",
            categories=[
                make_category(92, "Mellanmjölk", parents=[{"id": 911, "name": "Prismatch"}]),
                make_category(134, "Växtdryck", parents=[{"id": 78, "name": "Mejeri"}]),
            ],
        )
    )
    ids = [c.id for c in detail.classification_categories()]
    assert 92 not in ids  # Prismatch tree ignored
    assert 134 in ids


def test_cart_line_availability_helpers():
    payload = {
        "productQuantityCount": 1,
        "groups": [
            {
                "items": [
                    {
                        "itemId": 1,
                        "product": make_product(83, "Laoganma Krispig Chili"),
                        "quantity": 1,
                        "availability": {
                            "isAvailable": False,
                            "description": "Slut hos leverantör",
                            "descriptionShort": "Slut hos leverantör",
                            "code": "sold_out_supplier",
                        },
                        "hasAlternativeProducts": True,
                    },
                    {
                        "itemId": 2,
                        "product": make_product(65962, "Alpro Sojadryck Protein"),
                        "quantity": 1,
                        "availability": {"isAvailable": True, "code": "available"},
                        "hasAlternativeProducts": False,
                    },
                ]
            }
        ],
    }
    cart = Cart.from_api(payload)
    sold_out, available = cart.lines
    assert sold_out.is_available is False
    assert sold_out.availability_note == "Slut hos leverantör"
    assert sold_out.has_alternative_products is True
    assert available.is_available is True
    assert available.availability_note is None


def test_promotion_block_passthrough_verbatim():
    detail = ProductDetail.from_api(
        make_detail(1, "X", promotion={"title": "2 för 25", "displayStyle": "price_match"})
    )
    block = detail.product.promotion_block()
    assert block["promotion"] == {"title": "2 för 25", "displayStyle": "price_match"}

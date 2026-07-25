"""Search parsing, the zero-results-vs-error distinction, and filter discovery."""

from __future__ import annotations

from conftest import FakeCatalogSession, make_detail, make_product

from mathem_client.products import ProductsClient, _extract_filter_tokens


class _OneShot:
    def __init__(self, payload):
        self.payload = payload

    async def get(self, path, *, params=None):
        return self.payload


async def test_total_reads_product_count_not_recipe_and_filters_items():
    payload = {
        "items": [
            {"id": 1, "type": "product", "attributes": make_product(1, "Tomat Krossad")},
            {"id": 2, "type": "recipe", "attributes": {"id": 2, "title": "Tomatsoppa"}},
        ],
        "attributes": {
            "page": 1,
            "hasMoreItems": False,
            "requestTypes": [
                {"type": "product", "count": 434},
                {"type": "recipe", "count": 12},
            ],
        },
        "filters": [],
    }
    result = await ProductsClient(_OneShot(payload)).search("tomat")
    assert result.total == 434  # product count, not recipe
    assert [p.id for p in result.products] == [1]  # recipe item dropped


async def test_bogus_filter_returns_zero_not_error():
    session = FakeCatalogSession([make_detail(1, "Gurka", badges=["badges:is_vegan"])])
    result = await ProductsClient(session).search("gurka", filters=["badges:is_not_a_real_badge"])
    assert result.total == 0
    assert result.products == []


async def test_valid_filter_narrows_result():
    session = FakeCatalogSession(
        [
            make_detail(1, "Gurka Eko", badges=["badges:is_vegan", "badges:is_organic"]),
            make_detail(2, "Gurka Vanlig", badges=[]),
        ]
    )
    result = await ProductsClient(session).search("gurka", filters=["badges:is_vegan"])
    assert [p.id for p in result.products] == [1]


async def test_filters_are_comma_joined_not_repeated():
    session = FakeCatalogSession([make_detail(1, "X", badges=["a", "b"])])
    await ProductsClient(session).search("x", filters=["a", "b"])
    _, params = session.get_calls[-1]
    assert params["filters"] == "a,b"


async def test_discover_filters_unions_vocabulary():
    filters_payload = [
        {
            "id": "badges",
            "label": "Märkningar",
            "options": [
                {"value": "is_vegan", "displayValue": "Vegansk"},
                {"value": "is_organic", "displayValue": "Ekologisk"},
            ],
        },
        {
            "id": "allergens_free",
            "label": "Fritt från",
            "options": [{"value": "gluten_free", "displayValue": "Gluten"}],
        },
    ]
    session = FakeCatalogSession([make_detail(1, "mjölk")], filters_payload=filters_payload)
    vocab = await ProductsClient(session).discover_filters(["mjölk"])
    assert vocab["badges:is_vegan"] == "Vegansk"
    assert vocab["badges:is_organic"] == "Ekologisk"
    assert vocab["allergens_free:gluten_free"] == "Gluten"


def test_extract_filter_tokens_handles_prejoined_tokens():
    payload = [{"value": "badges:is_vegan", "label": "Vegansk"}]
    assert _extract_filter_tokens(payload) == {"badges:is_vegan": "Vegansk"}


async def test_previously_bought_products_sorted_first():
    # A product_list group ("Tidigare handlat") should float to the top and
    # dedupe against the flat results.
    payload = {
        "items": [
            {"type": "product", "attributes": make_product(2, "Sojadryck Naturell")},
            {
                "type": "product_list",
                "attributes": {"id": "prev_bought_products", "displayName": "Tidigare handlat"},
                "items": [
                    {"type": "product", "attributes": make_product(64776, "Alpro Sojadryck Protein Choklad")},
                    {"type": "product", "attributes": make_product(2, "Sojadryck Naturell")},
                ],
            },
            {"type": "product", "attributes": make_product(3, "Sojadryck Vanilj")},
        ],
        "attributes": {"page": 1, "hasMoreItems": False, "requestTypes": [{"type": "product", "count": 167}]},
        "filters": [],
    }
    result = await ProductsClient(_OneShot(payload)).search("alpro soja")
    assert [p.id for p in result.products] == [64776, 2, 3]  # prev-bought first, no dupe
    assert result.previously_bought_ids == {64776, 2}
    assert result.total == 167

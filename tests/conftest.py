"""Test fixtures and fake sessions for the vendored client.

These stand in for recorded live captures: synthetic payloads shaped exactly
like the documented API so the pure client and resolver can be exercised on a
workstation with no Home Assistant and no network.
"""

from __future__ import annotations

from typing import Any

from mathem_client.errors import MathemRequestError

# ---------------------------------------------------------------------------
# Payload builders (documented shapes)
# ---------------------------------------------------------------------------


def make_product(product_id: int, full_name: str, *, gross_price: str = "15.95", **extra: Any) -> dict[str, Any]:
    return {
        "id": product_id,
        "fullName": full_name,
        "name": full_name,
        "brand": extra.pop("brand", None),
        "nameExtra": extra.pop("name_extra", None),
        "grossPrice": gross_price,
        "currency": "SEK",
        "availability": {"isAvailable": True},
        **extra,
    }


def make_category(cat_id: int, name: str, *, parents: list[dict] | None = None, slug: str | None = None) -> dict[str, Any]:
    return {
        "id": cat_id,
        "name": name,
        "slug": slug or name.casefold(),
        "uri": f"/{cat_id}",
        "parent": (parents[-1]["id"] if parents else None),
        "parents": parents or [],
    }


def make_detail(
    product_id: int,
    full_name: str,
    *,
    categories: list[dict] | None = None,
    ingredients: str | None = None,
    allergens: str | None = None,
    nutrition: dict[str, Any] | None = None,
    badges: list[str] | None = None,
    promotion: dict | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A ``/products/{id}/`` payload.

    ``allergens=None`` means *no row* (unknown). ``nutrition`` is passed through
    as the ``nutritionInfoTable`` block; ``None`` omits the table.
    """
    rows: list[dict[str, Any]] = []
    if ingredients is not None:
        rows.append({"key": "Ingredienser", "keyId": None, "value": ingredients})
    if allergens is not None:
        rows.append({"key": "Allergener", "keyId": None, "value": allergens})
    detail = make_product(product_id, full_name, **extra)
    detail["categories"] = categories or []
    local: dict[str, Any] = {
        "language": "sv",
        "contentsTable": {"title": "Innehåll", "rows": rows},
    }
    if nutrition is not None:
        local["nutritionInfoTable"] = nutrition
    detail["detailedInfo"] = {"country": "SE", "local": [local]}
    if promotion is not None:
        detail["promotion"] = promotion
    # Test-only marker for badge-filter matching; ignored by the real model.
    detail["_badges"] = badges or []
    return detail


def make_search_payload(
    products: list[dict],
    *,
    total: int | None = None,
    has_more: bool = False,
    page: int = 1,
    filters: Any = None,
    recipe_count: int = 3,
) -> dict[str, Any]:
    items = [
        {"id": p["id"], "type": "product", "attributes": p, "trackingProperties": {}}
        for p in products
    ]
    return {
        "items": items,
        "attributes": {
            "page": page,
            "hasMoreItems": has_more,
            "requestTypes": [
                {"type": "product", "count": total if total is not None else len(products)},
                {"type": "recipe", "count": recipe_count},
            ],
        },
        "filters": filters if filters is not None else [],
    }


# ---------------------------------------------------------------------------
# Fake sessions (mimic MathemSession.get / .post)
# ---------------------------------------------------------------------------


class FakeCatalogSession:
    """Serves search and product-detail from an in-memory catalogue."""

    def __init__(self, details: list[dict], *, filters_payload: Any = None) -> None:
        self.details = {d["id"]: d for d in details}
        self.filters_payload = filters_payload if filters_payload is not None else []
        self.get_calls: list[tuple[str, dict]] = []

    @staticmethod
    def _match(query: str, filters: list[str], detail: dict) -> bool:
        if query and query.casefold() not in str(detail.get("fullName", "")).casefold():
            return False
        badges = set(detail.get("_badges", []))
        return all(token in badges for token in filters)

    async def get(self, path: str, *, params: dict | None = None) -> Any:
        params = params or {}
        self.get_calls.append((path, params))
        if path == "/search/mixed/":
            query = params.get("q", "")
            filters = [t for t in str(params.get("filters", "")).split(",") if t]
            matches = [d for d in self.details.values() if self._match(query, filters, d)]
            return make_search_payload(matches, total=len(matches), filters=self.filters_payload)
        if path.startswith("/products/"):
            pid = int(path.strip("/").split("/")[-1])
            if pid not in self.details:
                raise MathemRequestError(404, "GET", path)
            return self.details[pid]
        raise AssertionError(f"unexpected GET {path}")

    async def post(self, path: str, *, params: dict | None = None, json: Any | None = None) -> Any:
        raise AssertionError(f"unexpected POST {path}")


class FakeCartSession:
    """Stateful cart: applies deltas and records every POST payload."""

    def __init__(self) -> None:
        self.quantities: dict[int, int] = {}
        self.posts: list[dict] = []

    def _payload(self) -> dict[str, Any]:
        items = [
            {
                "itemId": 100000 + pid,
                "product": make_product(pid, f"Product {pid}"),
                "quantity": qty,
                "discountedQuantity": 0,
                "displayPriceTotal": f"{qty * 10}.00",
                "availability": {"isAvailable": True},
                "hasAlternativeProducts": False,
            }
            for pid, qty in self.quantities.items()
            if qty > 0
        ]
        units = sum(q for q in self.quantities.values() if q > 0)
        return {
            "id": "cart-1",
            "productQuantityCount": units,
            "displayPrice": f"{units * 10}.00",
            "totalGrossAmount": f"{units * 10 + 19}.00",
            "currency": "SEK",
            "summaryLines": [
                {"type": "GrossTotalAmount", "label": "Totalt", "value": f"{units * 10 + 19}.00"},
                {"type": "DeliveryFeeManipulator", "label": "Leverans", "value": "19.00"},
            ],
            "groups": [{"items": items}],
        }

    async def get(self, path: str, *, params: dict | None = None) -> Any:
        assert path == "/cart/"
        return self._payload()

    async def post(self, path: str, *, params: dict | None = None, json: Any | None = None) -> Any:
        assert path == "/cart/items/"
        self.posts.append(json)
        for item in json["items"]:
            pid = int(item["productId"])
            self.quantities[pid] = self.quantities.get(pid, 0) + int(item["quantity"])
        return self._payload()

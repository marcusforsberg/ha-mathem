"""Product search, product detail, and filter-vocabulary discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from .errors import MathemProtocolError
from .models import Product, ProductDetail
from .session import MathemSession

_LOGGER = logging.getLogger(__name__)

PAGE_SIZE = 30

# The search response can include a ``product_list`` group of the household's
# previously bought products (the native "Tidigare handlat" section). Its items
# are floated to the top of the results, matching the native ordering.
PREV_BOUGHT_LIST_ID = "prev_bought_products"

# Field names to try when pulling a token / a human label out of an unknown
# filter node. Kept generous because the exact ``filters[]`` shape is not
# pinned down and Mathem may add fields.
_TOKEN_KEYS = ("value", "token", "id", "key", "filter", "slug")
_LABEL_KEYS = ("displayValue", "label", "name", "title", "text")
_CHILD_KEYS = ("options", "children", "values", "items", "filters", "subFilters")


@dataclass(slots=True)
class SearchResult:
    """One page of a product search."""

    products: list[Product]
    total: int | None
    page: int
    has_more: bool
    filters: dict[str, str]
    previously_bought_ids: set[int] = field(default_factory=set)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def _extract_filter_tokens(node: Any, prefix: str | None = None) -> dict[str, str]:
    """Recursively pull ``token -> label`` pairs out of a ``filters[]`` tree.

    Tolerant by design: the exact shape is undocumented and must not be
    hardcoded. A token is preferred in ``group:value`` form (e.g.
    ``badges:is_vegan``); a bare value is namespaced with its parent group key
    when one is known.
    """
    found: dict[str, str] = {}

    if isinstance(node, list):
        for item in node:
            found.update(_extract_filter_tokens(item, prefix))
        return found

    if not isinstance(node, dict):
        return found

    # Determine this node's own token value and label, if any.
    raw_token: str | None = None
    for key in _TOKEN_KEYS:
        val = node.get(key)
        if isinstance(val, str) and val:
            raw_token = val
            break
    label: str | None = None
    for key in _LABEL_KEYS:
        val = node.get(key)
        if isinstance(val, str) and val:
            label = val
            break

    # Decide whether this node is a group (has children) or a leaf option.
    child_prefix = prefix
    has_children = any(k in node for k in _CHILD_KEYS)
    if has_children and raw_token and ":" not in raw_token:
        # This node names a group; its value becomes the namespace for leaves.
        child_prefix = raw_token

    if raw_token and label and not has_children:
        if ":" in raw_token:
            token = raw_token
        elif prefix:
            token = f"{prefix}:{raw_token}"
        else:
            token = raw_token
        found[token] = label

    for key in _CHILD_KEYS:
        if key in node:
            found.update(_extract_filter_tokens(node[key], child_prefix))

    return found


class ProductsClient:
    """Search and detail lookups, plus filter discovery."""

    def __init__(self, session: MathemSession) -> None:
        self._session = session

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        filters: Iterable[str] | None = None,
        item_type: str = "product",
    ) -> SearchResult:
        """Run a search. ``filters`` are AND-combined with a single comma.

        Repeating the ``filters`` query param breaks the response, so tokens are
        always joined into one comma-separated value.
        """
        params: dict[str, Any] = {"q": query, "type": item_type, "page": page}
        token_list = [t for t in (filters or []) if t]
        if token_list:
            params["filters"] = ",".join(token_list)

        data = await self._session.get("/search/mixed/", params=params)
        if not isinstance(data, dict):
            raise MathemProtocolError("search response was not an object")

        attributes = data.get("attributes") or {}
        items = data.get("items") or []

        flat: list[Product] = []
        prev_bought: list[Product] = []
        for item in items:
            item_type = item.get("type")
            if item_type == "product" and item.get("attributes"):
                flat.append(Product.from_api(item["attributes"]))
            elif item_type == "product_list":
                group = item.get("attributes") or {}
                nested = [
                    Product.from_api(n["attributes"])
                    for n in (item.get("items") or [])
                    if n.get("type") == "product" and n.get("attributes")
                ]
                if group.get("id") == PREV_BOUGHT_LIST_ID:
                    prev_bought.extend(nested)
                else:
                    # Other named groups still contribute their products.
                    flat.extend(nested)

        # Previously bought first (native "Tidigare handlat"), then the rest,
        # deduped by id so a repeat product is not listed twice.
        prev_ids = {p.id for p in prev_bought}
        products = list(prev_bought)
        products.extend(p for p in flat if p.id not in prev_ids)

        total: int | None = None
        for entry in attributes.get("requestTypes") or []:
            if entry.get("type") == "product":
                total = entry.get("count")
                break

        return SearchResult(
            products=products,
            total=total,
            page=int(attributes.get("page") or page),
            has_more=bool(attributes.get("hasMoreItems")),
            filters=_extract_filter_tokens(data.get("filters")),
            previously_bought_ids=prev_ids,
            raw=data,
        )

    async def search_paged(
        self,
        query: str,
        *,
        filters: Iterable[str] | None = None,
        limit: int = PAGE_SIZE,
    ) -> list[Product]:
        """Fetch up to ``limit`` products across pages.

        Previously bought products surface on the first page and are kept at the
        front; duplicates across pages are dropped.
        """
        collected: list[Product] = []
        seen: set[int] = set()
        page = 1
        filters = list(filters or [])
        while len(collected) < limit:
            result = await self.search(query, page=page, filters=filters)
            for product in result.products:
                if product.id not in seen:
                    seen.add(product.id)
                    collected.append(product)
            if not result.has_more or not result.products:
                break
            page += 1
        return collected[:limit]

    async def get_product(self, product_id: int) -> ProductDetail:
        """Fetch the detail record for one product."""
        data = await self._session.get(f"/products/{product_id}/")
        if not isinstance(data, dict):
            raise MathemProtocolError("product detail response was not an object")
        return ProductDetail.from_api(data)

    async def discover_filters(self, probe_queries: Iterable[str]) -> dict[str, str]:
        """Union the filter vocabulary across several broad queries.

        ``filters[]`` only returns tokens applicable to the current result set,
        so a single query undercounts. Callers should cache the result and
        refresh it occasionally rather than hardcoding the list.
        """
        vocabulary: dict[str, str] = {}
        for query in probe_queries:
            try:
                result = await self.search(query)
            except MathemProtocolError:
                _LOGGER.warning("filter discovery failed for query %r", query)
                continue
            vocabulary.update(result.filters)
        return vocabulary

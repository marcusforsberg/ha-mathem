"""Service registration and handlers.

Services are the integration's public surface. Each is registered with a
response, so the result is available to scripts and automations via
``response_variable`` and to conversation agents that can call services. No
service can reach ``checkout/confirm``, the session layer refuses that path
regardless.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .config_helpers import extract_addresses
from .const import DOMAIN
from .data import MathemConfigEntry, MathemRuntime
from .mathem_client import MathemError, ResolveStatus, SlotPredicate, cheapest_matching
from .mathem_client.models import Cart, ProductDetail, Slot
from .mathem_client.profiles import Profile
from .mathem_client.resolve import Resolver

_LOGGER = logging.getLogger(__name__)

# Service names.
SERVICE_SEARCH = "search_products"
SERVICE_GET_PRODUCT = "get_product"
SERVICE_ADD_ITEM = "add_item"
SERVICE_SET_QUANTITY = "set_quantity"
SERVICE_REMOVE_ITEM = "remove_item"
SERVICE_GET_CART = "get_cart"
SERVICE_AUDIT_CART = "audit_cart"
SERVICE_LIST_SLOTS = "list_delivery_slots"
SERVICE_SET_SLOT = "set_delivery_slot"
SERVICE_SET_ALIAS = "set_alias"
SERVICE_REMOVE_ALIAS = "remove_alias"
SERVICE_EXPORT_PANTRY = "export_pantry"
SERVICE_IMPORT_PANTRY = "import_pantry"
SERVICE_AUDIT_PANTRY = "audit_pantry"

_PROFILE = vol.Optional("profile")

# Schemas.
_SEARCH_SCHEMA = vol.Schema(
    {vol.Required("query"): cv.string, _PROFILE: cv.string, vol.Optional("limit", default=10): vol.All(int, vol.Range(min=1, max=60))}
)
_GET_PRODUCT_SCHEMA = vol.Schema({vol.Required("product_id"): vol.Coerce(int)})
_ADD_ITEM_SCHEMA = vol.Schema(
    {
        vol.Optional("query"): cv.string,
        vol.Optional("product_id"): vol.Coerce(int),
        vol.Optional("quantity", default=1): vol.All(int, vol.Range(min=1)),
        _PROFILE: cv.string,
    }
)
_SET_QUANTITY_SCHEMA = vol.Schema(
    {vol.Required("product_id"): vol.Coerce(int), vol.Required("quantity"): vol.All(int, vol.Range(min=0))}
)
_REMOVE_ITEM_SCHEMA = vol.Schema({vol.Required("product_id"): vol.Coerce(int)})
_AUDIT_CART_SCHEMA = vol.Schema({_PROFILE: cv.string})
_LIST_SLOTS_SCHEMA = vol.Schema(
    {vol.Optional("days", default=3): vol.All(int, vol.Range(min=1, max=14)), _PROFILE: cv.string}
)
_SET_SLOT_SCHEMA = vol.Schema(
    {
        vol.Optional("slot_id"): vol.Coerce(int),
        vol.Optional("predicate"): dict,
        vol.Optional("days", default=5): vol.All(int, vol.Range(min=1, max=14)),
    }
)
_SET_ALIAS_SCHEMA = vol.Schema(
    {vol.Required("keyword"): cv.string, vol.Required("product_id"): vol.Coerce(int)}
)
_REMOVE_ALIAS_SCHEMA = vol.Schema({vol.Required("keyword"): cv.string})
_IMPORT_PANTRY_SCHEMA = vol.Schema(
    {vol.Required("aliases"): dict, vol.Optional("replace", default=False): cv.boolean}
)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _product_dict(product) -> dict[str, Any]:
    """Core product fields plus the promotion block passed through verbatim."""
    return {
        "product_id": product.id,
        "full_name": product.full_name,
        "brand": product.brand,
        "name": product.name,
        "name_extra": product.name_extra,
        "gross_price": product.gross_price,
        "currency": product.currency,
        "availability": product.availability,
        **product.promotion_block(),
    }


def _detail_dict(detail: ProductDetail) -> dict[str, Any]:
    return {
        **_product_dict(detail.product),
        "is_restricted": detail.is_restricted,
        "restriction_age_limit": detail.restriction_age_limit,
        "ingredients": detail.ingredients_text,
        "allergens": detail.allergens_text,
        "categories": [
            {"id": c.id, "name": c.name, "slug": c.slug, "parents": c.parents}
            for c in detail.classification_categories()
        ],
    }


def _cart_dict(cart: Cart) -> dict[str, Any]:
    return {
        "id": cart.id,
        "display_price": cart.display_price,
        "total_gross_amount": cart.total_gross_amount,
        "currency": cart.currency,
        "unit_count": cart.unit_count,
        "line_count": cart.line_count,
        "summary_lines": [s.raw for s in cart.summary_lines],
        "lines": [
            {
                "item_id": line.item_id,
                "product_id": line.product.id,
                "name": line.product.full_name,
                "quantity": line.quantity,
                "discounted_quantity": line.discounted_quantity,
                "display_price_total": line.display_price_total,
                "availability": line.availability,
                "available": line.is_available,
                "availability_note": line.availability_note,
                "has_alternative_products": line.has_alternative_products,
                **line.product.promotion_block(),
            }
            for line in cart.lines
        ],
    }


def _added_line_info(cart: Cart, product_id: int) -> dict[str, Any]:
    """Availability of a just-added line, so callers can flag out-of-stock adds."""
    line = next((line for line in cart.lines if line.product.id == product_id), None)
    if line is None:
        return {"available": None, "availability_note": None, "has_alternatives": None}
    return {
        "available": line.is_available,
        "availability_note": line.availability_note,
        "has_alternatives": line.has_alternative_products,
    }


def _slot_dict(slot: Slot) -> dict[str, Any]:
    lo = slot.local_open
    lc = slot.local_close
    return {
        "slot_id": slot.id,
        "route_group": slot.route_group_str,
        "open_local": lo.isoformat() if lo else None,
        "close_local": lc.isoformat() if lc else None,
        "weekday": slot.local_weekday,
        "price": slot.price,
        "currency": "SEK",
        "is_selected": slot.is_selected,
        "is_full": slot.is_full,
        "is_unavailable": slot.is_unavailable,
        "unavailable_description": slot.unavailable_description,
        "is_cheapest": slot.is_cheapest,
        "bookable": slot.bookable,
        "tag": slot.tag,
    }


# ---------------------------------------------------------------------------
# Runtime lookup
# ---------------------------------------------------------------------------


def _runtime(hass: HomeAssistant) -> MathemRuntime:
    entries: list[MathemConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("Mathem is not set up")
    return entries[0].runtime_data


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def async_register_services(hass: HomeAssistant) -> None:
    """Register every Mathem service once."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_CART):
        return

    async def search_products(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        try:
            result = await rt.client.products.search(
                call.data["query"], filters=None
            )
            products = result.products[: call.data["limit"]]
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err
        prev = result.previously_bought_ids
        return {
            "query": call.data["query"],
            "total": result.total,
            "returned": len(products),
            "previously_bought": sorted(prev),
            "products": [
                {**_product_dict(p), "previously_bought": p.id in prev} for p in products
            ],
        }

    async def get_product(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        try:
            detail = await rt.client.products.get_product(call.data["product_id"])
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err
        return _detail_dict(detail)

    async def add_item(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        query = call.data.get("query")
        product_id = call.data.get("product_id")
        quantity = call.data["quantity"]
        if (query is None) == (product_id is None):
            raise ServiceValidationError("Provide exactly one of query or product_id")

        try:
            if product_id is not None:
                # A raw id is a deliberate assertion (like a pin); no inference.
                cart = await rt.client.cart.add_item(product_id, quantity)
                rt.coordinator.apply_cart(cart)
                return {
                    "status": "added",
                    "product_id": product_id,
                    "quantity": quantity,
                    **_added_line_info(cart, product_id),
                    "cart": _cart_dict(cart),
                }

            resolver: Resolver = rt.resolver()
            result = await resolver.resolve(query, profile=call.data.get("profile"))
            if result.status is not ResolveStatus.RESOLVED:
                return {"status": result.status.value, **result.as_dict()}

            cart = await rt.client.cart.add_item(result.product_id, quantity)  # type: ignore[arg-type]
            rt.coordinator.apply_cart(cart)
            return {
                "status": "added",
                "product_id": result.product_id,
                "quantity": quantity,
                "tier": result.tier,
                "resolved_name": result.candidate.name if result.candidate else None,
                "warnings": result.warnings,
                **_added_line_info(cart, result.product_id),  # type: ignore[arg-type]
                "cart": _cart_dict(cart),
            }
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err

    async def set_quantity(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        try:
            cart = await rt.client.cart.set_quantity(
                call.data["product_id"], call.data["quantity"]
            )
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err
        rt.coordinator.apply_cart(cart)
        return {"status": "ok", "cart": _cart_dict(cart)}

    async def remove_item(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        try:
            cart = await rt.client.cart.remove_item(call.data["product_id"])
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err
        rt.coordinator.apply_cart(cart)
        return {"status": "ok", "cart": _cart_dict(cart)}

    async def get_cart(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        try:
            cart = await rt.client.cart.get_cart()
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err
        rt.coordinator.apply_cart(cart)
        return _cart_dict(cart)

    async def audit_cart(call: ServiceCall) -> ServiceResponse:
        """Audit every cart line against one profile or the whole matrix.

        This is a prompt to read the label, never a clearance: no ingredient
        parser is medically reliable.
        """
        rt = _runtime(hass)
        requested = call.data.get("profile")
        profiles: dict[str, Profile]
        if requested:
            prof = rt.profiles.get(requested)
            profiles = {requested: prof} if prof else {}
        else:
            profiles = rt.profiles

        try:
            cart = await rt.client.cart.get_cart()
            # One detail fetch per line; cart lines lack categories/detailedInfo.
            details = {
                line.product.id: await rt.client.products.get_product(line.product.id)
                for line in cart.lines
            }
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err

        resolver = rt.resolver()
        rows: list[dict[str, Any]] = []
        for line in cart.lines:
            detail = details[line.product.id]
            verdicts: dict[str, Any] = {}
            for name, prof in profiles.items():
                v = resolver._vet(detail, prof)  # noqa: SLF001 - deliberate reuse
                verdicts[name] = {"safe": v.safe, "reason": v.reason, "warnings": v.warnings}
            rows.append(
                {
                    "product_id": line.product.id,
                    "name": line.product.full_name,
                    "quantity": line.quantity,
                    "verdicts": verdicts,
                }
            )
        return {
            "disclaimer": "Advisory only. Read the label before consuming.",
            "profiles": list(profiles),
            "lines": rows,
        }

    async def list_delivery_slots(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        try:
            slots = await rt.client.slots.list_slots_range(days=call.data["days"])
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err
        return {"count": len(slots), "slots": [_slot_dict(s) for s in slots]}

    async def set_delivery_slot(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        slot_id = call.data.get("slot_id")
        predicate_raw = call.data.get("predicate")
        if (slot_id is None) == (predicate_raw is None):
            raise ServiceValidationError("Provide exactly one of slot_id or predicate")

        try:
            # A slot list is needed for a predicate, and doubles as the source
            # for auto-detecting the delivery address when none is configured.
            page = await rt.client.slots.list_slots(num_days=3, from_index=0)
            address_id = rt.delivery_address_id
            if address_id is None:
                detected = extract_addresses(page.raw)
                if not detected:
                    raise ServiceValidationError(
                        "No delivery address found on the account; set one in the "
                        "integration options"
                    )
                address_id = next(iter(detected))

            if predicate_raw is not None:
                predicate = SlotPredicate.from_dict(predicate_raw)
                slots = await rt.client.slots.list_slots_range(days=call.data["days"])
                chosen = cheapest_matching(slots, predicate)
                if chosen is None:
                    return {
                        "status": "no_match",
                        "message": "No bookable slot matched the predicate",
                    }
                slot_id = chosen.id

            page = await rt.client.slots.set_slot(
                slot_id,
                is_unattended=rt.unattended,
                delivery_address_id=address_id,
            )
        except MathemError as err:
            raise HomeAssistantError(str(err)) from err

        if page.selection:
            rt.coordinator.apply_selection(page.selection)
        return {
            "status": "selected",
            "selection": {
                "slot_id": page.selection.id if page.selection else slot_id,
                "name": page.selection.name if page.selection else None,
                "name_short": page.selection.name_short if page.selection else None,
                "hold_expires_at": page.selection.expire_at.isoformat()
                if page.selection and page.selection.expire_at
                else None,
            },
            "slots": [_slot_dict(s) for s in page.slots],
        }

    async def set_alias(call: ServiceCall) -> ServiceResponse:
        """Pin a keyword to a product id, verifying the id resolves to a name.

        Fetching the product means a wrong id fails loudly instead of quietly
        poisoning the map.
        """
        rt = _runtime(hass)
        product_id = call.data["product_id"]
        try:
            detail = await rt.client.products.get_product(product_id)
        except MathemError as err:
            raise ServiceValidationError(
                f"Product id {product_id} did not resolve: {err}"
            ) from err
        await rt.pantry.async_set_alias(call.data["keyword"], {"product_id": product_id})
        return {
            "status": "ok",
            "keyword": call.data["keyword"],
            "product_id": product_id,
            "resolved_name": detail.product.full_name,
        }

    async def remove_alias(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        removed = await rt.pantry.async_remove_alias(call.data["keyword"])
        return {"status": "ok" if removed else "not_found", "keyword": call.data["keyword"]}

    async def export_pantry(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        return rt.pantry.export()

    async def import_pantry(call: ServiceCall) -> ServiceResponse:
        rt = _runtime(hass)
        data = {"aliases": call.data["aliases"]}
        count = await rt.pantry.async_import(data, replace=call.data["replace"])
        return {"status": "ok", "imported": count}

    async def audit_pantry(call: ServiceCall) -> ServiceResponse:
        """Check every pinned/ambiguous id still resolves to a live product."""
        rt = _runtime(hass)
        rows: list[dict[str, Any]] = []
        for keyword, entry in rt.pantry.aliases.as_dict().items():
            ids: list[int] = []
            if entry.get("product_id") is not None:
                ids.append(int(entry["product_id"]))
            ids.extend(int(a) for a in entry.get("ambiguous", []))
            for pid in ids:
                try:
                    detail = await rt.client.products.get_product(pid)
                    rows.append({"keyword": keyword, "product_id": pid, "ok": True, "name": detail.product.full_name})
                except MathemError as err:
                    rows.append({"keyword": keyword, "product_id": pid, "ok": False, "error": str(err)})
        broken = [r for r in rows if not r["ok"]]
        return {"checked": len(rows), "broken": len(broken), "entries": rows}

    ONLY = SupportsResponse.ONLY
    OPTIONAL = SupportsResponse.OPTIONAL
    registrations = [
        (SERVICE_SEARCH, search_products, _SEARCH_SCHEMA, ONLY),
        (SERVICE_GET_PRODUCT, get_product, _GET_PRODUCT_SCHEMA, ONLY),
        (SERVICE_ADD_ITEM, add_item, _ADD_ITEM_SCHEMA, OPTIONAL),
        (SERVICE_SET_QUANTITY, set_quantity, _SET_QUANTITY_SCHEMA, OPTIONAL),
        (SERVICE_REMOVE_ITEM, remove_item, _REMOVE_ITEM_SCHEMA, OPTIONAL),
        (SERVICE_GET_CART, get_cart, vol.Schema({}), ONLY),
        (SERVICE_AUDIT_CART, audit_cart, _AUDIT_CART_SCHEMA, ONLY),
        (SERVICE_LIST_SLOTS, list_delivery_slots, _LIST_SLOTS_SCHEMA, ONLY),
        (SERVICE_SET_SLOT, set_delivery_slot, _SET_SLOT_SCHEMA, OPTIONAL),
        (SERVICE_SET_ALIAS, set_alias, _SET_ALIAS_SCHEMA, OPTIONAL),
        (SERVICE_REMOVE_ALIAS, remove_alias, _REMOVE_ALIAS_SCHEMA, OPTIONAL),
        (SERVICE_EXPORT_PANTRY, export_pantry, vol.Schema({}), ONLY),
        (SERVICE_IMPORT_PANTRY, import_pantry, _IMPORT_PANTRY_SCHEMA, OPTIONAL),
        (SERVICE_AUDIT_PANTRY, audit_pantry, vol.Schema({}), ONLY),
    ]
    for name, handler, schema, response in registrations:
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=response)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last entry unloads."""
    for name in (
        SERVICE_SEARCH, SERVICE_GET_PRODUCT, SERVICE_ADD_ITEM, SERVICE_SET_QUANTITY,
        SERVICE_REMOVE_ITEM, SERVICE_GET_CART, SERVICE_AUDIT_CART, SERVICE_LIST_SLOTS,
        SERVICE_SET_SLOT, SERVICE_SET_ALIAS, SERVICE_REMOVE_ALIAS, SERVICE_EXPORT_PANTRY,
        SERVICE_IMPORT_PANTRY, SERVICE_AUDIT_PANTRY,
    ):
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)

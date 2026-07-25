"""Pure helpers for the config flow (no Home Assistant imports)."""

from __future__ import annotations

from typing import Any


def _address_label(addr: dict[str, Any]) -> str:
    parts = [
        addr.get("street") or addr.get("streetAddress") or addr.get("addressLine1"),
        addr.get("zipCode") or addr.get("postalCode"),
        addr.get("city"),
    ]
    label = ", ".join(str(p) for p in parts if p)
    return label or (addr.get("name") or f"Address {addr.get('id')}")


def extract_addresses(cart_raw: dict[str, Any]) -> dict[int, str]:
    """Pull ``{id: label}`` delivery addresses out of a cart payload.

    The address lives under ``cartInfo.deliveryAddress`` in captures, but the
    exact nesting is not pinned down, so several shapes are tolerated. Returns
    an empty dict when nothing address-like is found; the flow then falls back
    to manual id entry.
    """
    candidates: list[dict[str, Any]] = []

    def _collect(node: Any) -> None:
        if isinstance(node, dict):
            if "id" in node and any(
                k in node for k in ("street", "streetAddress", "addressLine1", "zipCode", "postalCode", "city")
            ):
                candidates.append(node)
            for value in node.values():
                _collect(value)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    cart_info = cart_raw.get("cartInfo") or {}
    delivery = cart_info.get("deliveryAddress") or cart_raw.get("deliveryAddress")
    if delivery is not None:
        _collect(delivery)
    if not candidates:
        # Last resort: scan the whole payload for address-shaped dicts.
        _collect(cart_raw)

    addresses: dict[int, str] = {}
    for addr in candidates:
        try:
            addr_id = int(addr["id"])
        except (KeyError, TypeError, ValueError):
            continue
        addresses.setdefault(addr_id, _address_label(addr))
    return addresses

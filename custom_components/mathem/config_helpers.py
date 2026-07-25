"""Pure helpers for the config flow (no Home Assistant imports)."""

from __future__ import annotations

from typing import Any

# Keys that reliably mark an address (used for detection outside a known
# address container, so a product's {id, name} is not mistaken for one).
_STRONG_KEYS = (
    "street",
    "streetAddress",
    "addressLine1",
    "zipCode",
    "postalCode",
    "city",
    "formattedAddress",
    "address",
)
# Inside a known deliveryAddress container an entry is already an address, so a
# looser set (adding name-like keys) is enough to pick it up and label it.
_LOOSE_KEYS = _STRONG_KEYS + ("displayName", "name", "label")


def _address_label(addr: dict[str, Any]) -> str:
    parts = [
        addr.get("street") or addr.get("streetAddress") or addr.get("addressLine1"),
        addr.get("zipCode") or addr.get("postalCode"),
        addr.get("city"),
    ]
    label = ", ".join(str(p) for p in parts if p)
    return label or str(
        addr.get("formattedAddress")
        or addr.get("displayName")
        or addr.get("name")
        or addr.get("label")
        or f"Address {addr.get('id')}"
    )


def _collect(node: Any, out: dict[int, str], keys: tuple[str, ...]) -> None:
    """Collect address-shaped dicts (an ``id`` plus one of ``keys``) into ``out``."""
    if isinstance(node, dict):
        if node.get("id") is not None and any(k in node for k in keys):
            try:
                out.setdefault(int(node["id"]), _address_label(node))
            except (TypeError, ValueError):
                pass
        for value in node.values():
            _collect(value, out, keys)
    elif isinstance(node, list):
        for item in node:
            _collect(item, out, keys)


def extract_addresses(payload: dict[str, Any]) -> dict[int, str]:
    """Pull ``{id: label}`` delivery addresses out of an API payload.

    Both the cart (``cartInfo.deliveryAddress``) and the slot picker (top-level
    ``deliveryAddresses``) expose addresses, in slightly different shapes. Any
    ``deliveryAddress`` / ``deliveryAddresses`` container is scanned first with a
    loose key set; only if none is found does it fall back to a strict scan of
    the whole payload (so unrelated ``{id, name}`` objects are not misread as
    addresses). Returns an empty dict when nothing address-like is found.
    """
    containers: list[Any] = []

    def _find_containers(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("deliveryAddress", "deliveryAddresses"):
                    containers.append(value)
                _find_containers(value)
        elif isinstance(node, list):
            for item in node:
                _find_containers(item)

    _find_containers(payload)

    out: dict[int, str] = {}
    for container in containers:
        _collect(container, out, _LOOSE_KEYS)
    if not out:
        _collect(payload, out, _STRONG_KEYS)
    return out

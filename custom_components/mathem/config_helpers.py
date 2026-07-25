"""Pure helpers for the config flow (no Home Assistant imports)."""

from __future__ import annotations

from typing import Any

# Field names an address id may arrive under.
_ID_KEYS = ("id", "addressId", "deliveryAddressId")

# Keys that reliably mark an address. Mathem returns addressDisplay and
# addressDisplayFull; the street/zip/city names are accepted too so a shape
# change does not silently break detection.
_STRONG_KEYS = (
    "addressDisplayFull",
    "addressDisplay",
    "street",
    "streetAddress",
    "addressLine1",
    "zipCode",
    "postalCode",
    "city",
    "formattedAddress",
)
# Inside a known deliveryAddress container an entry is already an address, so a
# looser set is enough to pick it up and label it.
_LOOSE_KEYS = _STRONG_KEYS + (
    "recipientName",
    "userSpecifiedName",
    "isPrimary",
    "displayName",
    "name",
    "label",
)


def _address_id(node: dict[str, Any]) -> int | None:
    for key in _ID_KEYS:
        value = node.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _address_label(addr: dict[str, Any]) -> str:
    """Human label for the picker, e.g. ``Testgatan 2, 111 11 Stockholm``."""
    label = addr.get("addressDisplayFull") or addr.get("addressDisplay")
    if not label:
        parts = [
            addr.get("street") or addr.get("streetAddress") or addr.get("addressLine1"),
            addr.get("zipCode") or addr.get("postalCode"),
            addr.get("city"),
        ]
        label = ", ".join(str(p) for p in parts if p)
    if not label:
        label = str(
            addr.get("formattedAddress")
            or addr.get("userSpecifiedName")
            or addr.get("displayName")
            or addr.get("name")
            or addr.get("label")
            or f"Address {_address_id(addr)}"
        )
    # A nickname is more recognisable than the street alone when set.
    nickname = addr.get("userSpecifiedName")
    if nickname:
        label = f"{nickname} ({label})"
    if addr.get("isDeliveryAvailable") is False:
        label = f"{label} (delivery unavailable)"
    return label


def _collect(node: Any, out: list[dict[str, Any]], keys: tuple[str, ...]) -> None:
    """Collect address-shaped dicts (an id plus one of ``keys``) into ``out``."""
    if isinstance(node, dict):
        if _address_id(node) is not None and any(k in node for k in keys):
            out.append(node)
        for value in node.values():
            _collect(value, out, keys)
    elif isinstance(node, list):
        for item in node:
            _collect(item, out, keys)


def extract_addresses(payload: dict[str, Any]) -> dict[int, str]:
    """Pull ``{id: label}`` delivery addresses out of an API payload.

    The slot picker returns them as a top-level ``deliveryAddresses`` list, and
    the cart exposes the active one under ``cartInfo.deliveryAddress``. Those
    containers are scanned first with a loose key set; only if none is found does
    it fall back to a strict scan of the whole payload, so unrelated ``{id,
    name}`` objects are not misread as addresses. The primary address is listed
    first, so it becomes the picker's default. Returns an empty dict when nothing
    address-like is found.
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

    nodes: list[dict[str, Any]] = []
    for container in containers:
        _collect(container, nodes, _LOOSE_KEYS)
    if not nodes:
        _collect(payload, nodes, _STRONG_KEYS)

    # Stable sort: primary first, otherwise payload order.
    nodes.sort(key=lambda n: not bool(n.get("isPrimary")))

    addresses: dict[int, str] = {}
    for node in nodes:
        addr_id = _address_id(node)
        if addr_id is not None:
            addresses.setdefault(addr_id, _address_label(node))
    return addresses

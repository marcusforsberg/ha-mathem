"""Typed views over the Mathem API JSON.

Every response is consumed with ``x-requested-case: camel`` so keys arrive in
camelCase. These dataclasses keep the raw dict around (``raw``) because some
service responses must pass the promotion block through verbatim, and because
the API carries far more than we model.

Nothing here imports Home Assistant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# The store operates in Swedish local time. Slot datetimes arrive as UTC and
# must be converted before any weekday/time predicate, or DST shifts the match
# twice a year (06:00 local is 04:00Z in summer, 05:00Z in winter).
STORE_TZ = ZoneInfo("Europe/Stockholm")

# Marketing "Prismatch" category tree. Its membership is a promotion, not a
# classification, so it is ignored when vetoing categories.
PRISMATCH_ROOT_ID = 911


def _parse_price(value: Any) -> float | None:
    """Parse a Mathem price into a float.

    Handles decimal strings (``"15.95"``) and display strings (``"19 kr"``).
    Returns ``None`` for missing/unparseable input rather than guessing 0.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace("kr", "").replace("\xa0", " ")
    text = text.replace(",", ".").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp into an aware datetime."""
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

# Keys that make up the promotion block. Services that surface products must
# pass these through verbatim so a future consumer can spot multibuys; the
# resolver must never read them for ranking.
PROMOTION_KEYS = ("promotion", "promotions", "pills", "discount", "bonusInfo")


@dataclass(slots=True)
class Product:
    """A product as it appears in search results or on a cart line.

    Cart lines and search hits share this shape. It carries no categories and
    no ``detailedInfo``; anything diet-related has to come from the detail
    endpoint (:class:`ProductDetail`).
    """

    id: int
    full_name: str
    brand: str | None
    name: str | None
    name_extra: str | None
    gross_price: float | None
    currency: str | None
    availability: Any
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Product:
        return cls(
            id=int(data["id"]),
            full_name=data.get("fullName") or data.get("name") or "",
            brand=data.get("brand"),
            name=data.get("name"),
            name_extra=data.get("nameExtra"),
            gross_price=_parse_price(data.get("grossPrice")),
            currency=data.get("currency"),
            availability=data.get("availability"),
            raw=data,
        )

    def promotion_block(self) -> dict[str, Any]:
        """Return the promotion-related keys verbatim (empty dict if absent)."""
        return {k: self.raw[k] for k in PROMOTION_KEYS if k in self.raw}


@dataclass(slots=True)
class Category:
    """A category membership with its ancestor chain.

    ``id``/``name``/``slug`` describe the leaf node this product sits at within
    one tree; ``parents`` is the ancestor chain toward the root. Vetoes match
    the leaf, allowlists may match anywhere in the chain.
    """

    id: int | None
    name: str | None
    uri: str | None
    slug: str | None
    parent: Any
    parents: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Category:
        return cls(
            id=int(data["id"]) if data.get("id") is not None else None,
            name=data.get("name"),
            uri=data.get("uri"),
            slug=data.get("slug"),
            parent=data.get("parent"),
            parents=list(data.get("parents") or []),
        )

    @property
    def root_id(self) -> int | None:
        """Id of the topmost ancestor (used to spot the Prismatch tree)."""
        if self.parents:
            first = self.parents[0]
            if isinstance(first, dict) and first.get("id") is not None:
                return int(first["id"])
        return self.id

    def ancestor_tokens(self) -> set[str]:
        """Ids (as str) and lowercased names/slugs for the whole chain."""
        tokens: set[str] = set()
        for node in (*self.parents, {"id": self.id, "name": self.name, "slug": self.slug}):
            if not isinstance(node, dict):
                continue
            if node.get("id") is not None:
                tokens.add(str(node["id"]))
            for key in ("name", "slug"):
                if node.get(key):
                    tokens.add(str(node[key]).casefold())
        return tokens

    def leaf_tokens(self) -> set[str]:
        """Ids (as str) and lowercased name/slug for the leaf node only."""
        tokens: set[str] = set()
        if self.id is not None:
            tokens.add(str(self.id))
        for value in (self.name, self.slug):
            if value:
                tokens.add(str(value).casefold())
        return tokens


@dataclass(slots=True)
class ContentsRow:
    """A row from ``detailedInfo.local[sv].contentsTable``.

    Only the two description rows carry stable ``key_id`` values; Ingredienser
    and Allergener must be matched on the localised ``key`` label.
    """

    key: str | None
    key_id: str | None
    value: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ContentsRow:
        return cls(key=data.get("key"), key_id=data.get("keyId"), value=data.get("value"))


# Localised labels for the two rows the resolver cares about. keyId is null for
# both, so matching is on the label string.
INGREDIENTS_LABEL = "ingredienser"
ALLERGENS_LABEL = "allergener"


@dataclass(slots=True)
class ProductDetail:
    """Superset of :class:`Product` from ``GET /products/{id}/``."""

    product: Product
    categories: list[Category]
    is_restricted: bool
    restriction_age_limit: int | None
    contents_rows: list[ContentsRow]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def id(self) -> int:
        return self.product.id

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ProductDetail:
        detailed = data.get("detailedInfo") or {}
        local_list = detailed.get("local") or []
        sv = next((entry for entry in local_list if entry.get("language") == "sv"), None)
        if sv is None and local_list:
            # Some payloads key the language differently; take the first entry
            # only as a last resort so we do not silently read another language.
            sv = local_list[0]
        contents = (sv or {}).get("contentsTable") or {}
        rows = [ContentsRow.from_api(r) for r in (contents.get("rows") or [])]
        return cls(
            product=Product.from_api(data),
            categories=[Category.from_api(c) for c in (data.get("categories") or [])],
            is_restricted=bool(data.get("isRestricted")),
            restriction_age_limit=data.get("restrictionAgeLimit"),
            contents_rows=rows,
            raw=data,
        )

    def _row(self, label: str) -> ContentsRow | None:
        target = label.casefold()
        for row in self.contents_rows:
            if row.key and row.key.casefold() == target:
                return row
        return None

    @property
    def ingredients_text(self) -> str | None:
        row = self._row(INGREDIENTS_LABEL)
        return row.value if row else None

    @property
    def allergens_text(self) -> str | None:
        """The Allergener row value, or ``None`` if the row is absent.

        ``None`` means *unknown*, never *safe*. The resolver fails closed on it.
        """
        row = self._row(ALLERGENS_LABEL)
        return row.value if row else None

    def classification_categories(self) -> list[Category]:
        """Categories usable for classification (Prismatch tree removed)."""
        return [c for c in self.categories if c.root_id != PRISMATCH_ROOT_ID]


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SummaryLine:
    """A named line from the cart's ``summaryLines[]`` (fees, totals)."""

    type: str | None
    label: str | None
    value: Any
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SummaryLine:
        return cls(
            type=data.get("type") or data.get("name"),
            label=data.get("label") or data.get("title"),
            value=data.get("value") if "value" in data else data.get("amount"),
            raw=data,
        )


@dataclass(slots=True)
class CartLine:
    """A single line item, flattened out of ``groups[].items[]``."""

    item_id: int
    product: Product
    quantity: int
    discounted_quantity: int | None
    display_price_total: Any
    availability: Any
    has_alternative_products: bool
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CartLine:
        return cls(
            item_id=int(data["itemId"]),
            product=Product.from_api(data["product"]),
            quantity=int(data.get("quantity") or 0),
            discounted_quantity=data.get("discountedQuantity"),
            display_price_total=data.get("displayPriceTotal"),
            availability=data.get("availability"),
            has_alternative_products=bool(data.get("hasAlternativeProducts")),
            raw=data,
        )

    @property
    def is_available(self) -> bool | None:
        """``isAvailable`` for the line, or ``None`` when unknown."""
        if isinstance(self.availability, dict):
            return self.availability.get("isAvailable")
        return None

    @property
    def availability_note(self) -> str | None:
        """Human note for an unavailable line, e.g. 'Slut hos leverantör'."""
        if isinstance(self.availability, dict):
            return (
                self.availability.get("descriptionShort")
                or self.availability.get("description")
                or None
            )
        return None


@dataclass(slots=True)
class Cart:
    """The whole cart. ``lines`` is ``groups[].items[]`` flattened."""

    id: Any
    display_price: Any
    total_gross_amount: Any
    product_quantity_count: int
    currency: str | None
    summary_lines: list[SummaryLine]
    lines: list[CartLine]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Cart:
        lines: list[CartLine] = []
        for group in data.get("groups") or []:
            for item in group.get("items") or []:
                lines.append(CartLine.from_api(item))
        return cls(
            id=data.get("id"),
            display_price=data.get("displayPrice"),
            total_gross_amount=data.get("totalGrossAmount"),
            product_quantity_count=int(data.get("productQuantityCount") or 0),
            currency=data.get("currency"),
            summary_lines=[SummaryLine.from_api(s) for s in (data.get("summaryLines") or [])],
            lines=lines,
            raw=data,
        )

    @property
    def unit_count(self) -> int:
        """Total units in the cart (``productQuantityCount``)."""
        return self.product_quantity_count

    @property
    def line_count(self) -> int:
        """Number of distinct lines."""
        return len(self.lines)

    def quantity_of(self, product_id: int) -> int:
        """Current quantity of a product, summed across lines (0 if absent)."""
        return sum(line.quantity for line in self.lines if line.product.id == product_id)

    def summary_line(self, type_name: str) -> SummaryLine | None:
        """Look up a named summary line, e.g. ``GrossTotalAmount``."""
        for line in self.summary_lines:
            if line.type == type_name:
                return line
        return None


# ---------------------------------------------------------------------------
# Delivery slots
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Slot:
    """A delivery slot.

    Ids are ephemeral (adjacent days reuse unrelated ids), so never persist one.
    Express a preference as a predicate over ``local_weekday`` and the local
    open/close times exposed here.
    """

    id: int
    route_group: int | None
    route_group_str: str | None
    open_dt: datetime | None
    close_dt: datetime | None
    cutoff_dt: datetime | None
    is_selected: bool
    is_full: bool
    is_unavailable: bool
    unavailable_description: str | None
    price: float | None
    is_cheapest: bool
    tag: Any
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Slot:
        return cls(
            id=int(data["id"]),
            route_group=data.get("routeGroup"),
            route_group_str=data.get("routeGroupStr"),
            open_dt=_parse_dt(data.get("openDatetime")),
            close_dt=_parse_dt(data.get("closeDatetime")),
            cutoff_dt=_parse_dt(data.get("cutoffTime")),
            is_selected=bool(data.get("isSelected")),
            is_full=bool(data.get("isFull")),
            is_unavailable=bool(data.get("isUnavailable")),
            unavailable_description=data.get("unavailableDescription"),
            price=_parse_price(data.get("price")),
            is_cheapest=bool(data.get("isCheapest")),
            tag=data.get("tag"),
            raw=data,
        )

    @property
    def bookable(self) -> bool:
        return not (self.is_full or self.is_unavailable)

    @property
    def local_open(self) -> datetime | None:
        return self.open_dt.astimezone(STORE_TZ) if self.open_dt else None

    @property
    def local_close(self) -> datetime | None:
        return self.close_dt.astimezone(STORE_TZ) if self.close_dt else None

    @property
    def local_weekday(self) -> int | None:
        """Local weekday, Monday=0 .. Sunday=6, or ``None`` if no open time."""
        lo = self.local_open
        return lo.weekday() if lo else None

    @property
    def window_label(self) -> str | None:
        """Local window as ``YYYY-MM-DD HH:MM-HH:MM`` (locale independent)."""
        lo, lc = self.local_open, self.local_close
        if lo is None or lc is None:
            return None
        return f"{lo.strftime('%Y-%m-%d %H:%M')}-{lc.strftime('%H:%M')}"


@dataclass(slots=True)
class SlotSelection:
    """The ``deliverySlot`` echo returned when a slot is selected."""

    id: int
    name: str | None
    name_short: str | None
    cutoff_dt: datetime | None
    expire_at: datetime | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SlotSelection:
        return cls(
            id=int(data["id"]),
            name=data.get("name"),
            name_short=data.get("nameShort"),
            cutoff_dt=_parse_dt(data.get("cutoffTime")),
            expire_at=_parse_dt(data.get("expireAt")),
            raw=data,
        )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def _pick(data: Any, *names: str, default: Any = None) -> Any:
    """First present key among ``names`` (tolerates snake_case vs camelCase)."""
    if isinstance(data, dict):
        for name in names:
            if name in data:
                return data[name]
    return default


# The ``/orders/`` endpoint returns localised display strings for the delivery
# window, never an ISO datetime, so the window is reconstructed relative to the
# current time in Europe/Stockholm.
_SV_WEEKDAYS = {
    "måndag": 0, "mån": 0, "tisdag": 1, "tis": 1, "onsdag": 2, "ons": 2,
    "torsdag": 3, "tor": 3, "tors": 3, "fredag": 4, "fre": 4,
    "lördag": 5, "lör": 5, "söndag": 6, "sön": 6,
}
_SV_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "augusti": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}
_SV_RELATIVE_DAYS = {"idag": 0, "imorgon": 1, "i övermorgon": 2, "i overmorgon": 2}
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})")


def _resolve_delivery_date(day_part: str, now_local: datetime) -> date | None:
    if not day_part:
        return None
    if day_part in _SV_RELATIVE_DAYS:
        return (now_local + timedelta(days=_SV_RELATIVE_DAYS[day_part])).date()
    # "sön 5. juli" style: day number followed by a month name. The year is
    # never stated, so pick the one that lands nearest today: a December date
    # read in January belongs to last year, and a January date read in December
    # belongs to next year. Assuming the current year would put the first of
    # those eleven months in the future.
    match = re.search(r"(\d{1,2})\.?\s+([a-zåäö]+)", day_part)
    if match and match.group(2) in _SV_MONTHS:
        day, month = int(match.group(1)), _SV_MONTHS[match.group(2)]
        candidates: list[date] = []
        for year in (now_local.year - 1, now_local.year, now_local.year + 1):
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                continue  # e.g. 29 February in a non-leap year
        if not candidates:
            return None
        return min(candidates, key=lambda d: abs((d - now_local.date()).days))
    # A bare weekday name resolves to its next occurrence within a week.
    token = day_part.split()[0]
    if token in _SV_WEEKDAYS:
        delta = (_SV_WEEKDAYS[token] - now_local.weekday()) % 7
        return (now_local + timedelta(days=delta)).date()
    return None


def parse_delivery_window(text: str | None, now: datetime) -> tuple[datetime | None, datetime | None]:
    """Parse a string like ``"imorgon, 06:00 - 11:00"`` into (start, end).

    ``now`` anchors relative days ("idag"/"imorgon"/weekday). Times are Swedish
    local. Returns ``(None, None)`` when the string cannot be parsed.
    """
    if not text or now is None:
        return (None, None)
    now_local = now.astimezone(STORE_TZ)
    day_part, _, time_part = text.partition(",")
    times = _TIME_RE.findall(time_part)
    if not times:
        return (None, None)
    day = _resolve_delivery_date(day_part.strip().casefold(), now_local)
    if day is None:
        return (None, None)
    start_h, start_m = int(times[0][0]), int(times[0][1])
    end_h, end_m = (int(times[1][0]), int(times[1][1])) if len(times) > 1 else (start_h, start_m)
    start = datetime(day.year, day.month, day.day, start_h, start_m, tzinfo=STORE_TZ)
    end = datetime(day.year, day.month, day.day, end_h, end_m, tzinfo=STORE_TZ)
    if end < start:
        end += timedelta(days=1)
    return (start, end)


@dataclass(slots=True)
class Order:
    """One order from ``GET /orders/``.

    The endpoint returns snake_case even with the camel header and exposes no
    ISO datetimes, so keys are read casing-tolerantly and the delivery window is
    held as its localised text; :meth:`window` reconstructs the timestamps.
    """

    order_number: str | None
    status_title: str | None
    status_content: str | None
    payment_status: str | None
    payment_status_state: str | None
    can_be_ordered_again: bool
    delivery_address: str | None
    delivery_time_text: str | None
    cutoff_text: str | None
    is_doorstep_delivery: bool | None
    live_tracked_order: Any
    # CONFIRMED / PROCESSING / ON_THE_WAY / DELIVERED. More reliable than the
    # localised status title for telling a past order from an upcoming one.
    tracking_step: str | None = None
    # Free text around the tracking steps. The narrowed delivery estimate
    # appears in the subtitle while packing and moves to the title once the
    # order ships, so both are kept and both are searched.
    tracking_subtitle: str | None = None
    tracking_title: str | None = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Order:
        status = _pick(data, "status", default={}) or {}
        delivery = _pick(data, "delivery", default={}) or {}
        tracking = _pick(delivery, "tracking", default={}) or {}
        tdata = _pick(tracking, "data", default={}) or {}
        number = _pick(data, "order_number", "orderNumber")
        return cls(
            order_number=str(number) if number is not None else None,
            status_title=_pick(status, "title"),
            status_content=_pick(status, "content"),
            payment_status=_pick(status, "payment_status", "paymentStatus"),
            payment_status_state=_pick(status, "payment_status_state", "paymentStatusState"),
            can_be_ordered_again=bool(_pick(status, "can_be_ordered_again", "canBeOrderedAgain")),
            delivery_address=_pick(delivery, "delivery_address", "deliveryAddress"),
            delivery_time_text=_pick(delivery, "delivery_time", "deliveryTime"),
            cutoff_text=_pick(delivery, "cutoff_text", "cutoffText"),
            is_doorstep_delivery=_pick(tdata, "is_doorstep_delivery", "isDoorstepDelivery"),
            live_tracked_order=_pick(tdata, "live_tracked_order", "liveTrackedOrder"),
            tracking_step=_pick(tracking, "step_name", "stepName"),
            tracking_subtitle=_pick(tdata, "subtitle"),
            tracking_title=_pick(tdata, "title"),
            raw=data,
        )

    @property
    def is_delivered(self) -> bool:
        """Whether the order has already been delivered."""
        return (self.tracking_step or "").upper() == "DELIVERED"

    def window(self, now: datetime) -> tuple[datetime | None, datetime | None]:
        """The booked delivery window, reconstructed from its localised text."""
        return parse_delivery_window(self.delivery_time_text, now)

    def estimated_window(self, now: datetime) -> tuple[datetime | None, datetime | None]:
        """Mathem's narrowed estimate, if it has published one yet.

        The estimate sits in the tracking subtitle while the order is being
        packed and in the title once it ships, so both are searched. A range
        equal to the booked window is the booked window restated, not an
        estimate, so it is skipped; that test needs no Swedish phrase matching.
        Anchored to the booked date, since the text carries clock times only.
        """
        booked_start, booked_end = self.window(now)
        for text in (self.tracking_subtitle, self.tracking_title):
            start, end = parse_estimated_window(text, booked_start)
            if start is None or (start, end) == (booked_start, booked_end):
                continue
            return (start, end)
        return (None, None)

    def effective_window(self, now: datetime) -> tuple[datetime | None, datetime | None]:
        """The estimate when there is one, otherwise the booked window."""
        start, end = self.estimated_window(now)
        if start is not None:
            return (start, end)
        return self.window(now)

    def window_text(self, now: datetime) -> str | None:
        """The effective window as ``HH:MM - HH:MM`` in local time.

        Intended for a compact display such as a dashboard badge, where the day
        is already implied. ``None`` when no window can be resolved.
        """
        start, end = self.effective_window(now)
        if start is None or end is None:
            return None
        local_start = start.astimezone(STORE_TZ)
        local_end = end.astimezone(STORE_TZ)
        return f"{local_start:%H:%M} - {local_end:%H:%M}"

    def is_delivery_today(self, now: datetime) -> bool:
        """Whether the booked delivery day is the current local day.

        Keyed on the booked window rather than the estimate, so it does not
        change as the estimate moves around within the day.
        """
        start, _ = self.window(now)
        if start is None:
            return False
        return start.astimezone(STORE_TZ).date() == now.astimezone(STORE_TZ).date()


# Once an order is being packed, Mathem narrows the booked window to an estimate
# and states it only in free text, e.g. "Vi tror att vi är hos dig mellan
# 08:25–09:25." Note the en dash; an ordinary hyphen and a period separator are
# accepted too so a wording change does not silently drop the estimate.
_ESTIMATE_RE = re.compile(r"(\d{1,2})[:.](\d{2})\s*[–—−-]\s*(\d{1,2})[:.](\d{2})")


def parse_estimated_window(
    text: str | None, booked_start: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Pull a narrowed delivery estimate out of the tracking subtitle.

    The text carries only clock times, so the date is taken from the booked
    window. Returns ``(None, None)`` when no time range is present, which is the
    normal case before an order is packed.
    """
    if not text or booked_start is None:
        return (None, None)
    match = _ESTIMATE_RE.search(text)
    if not match:
        return (None, None)
    start_h, start_m, end_h, end_m = (int(g) for g in match.groups())
    day = booked_start.astimezone(STORE_TZ)
    try:
        start = day.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end = day.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    except ValueError:  # nonsense hour/minute in the text
        return (None, None)
    if end < start:  # window crosses midnight
        end += timedelta(days=1)
    return (start, end)


@dataclass(slots=True)
class OrderLine:
    """One product line on a placed order.

    ``quantity`` is a float because Mathem bills weighted goods fractionally.
    ``uncredited_quantity`` is what remains after any refund, so it can be lower
    than ``quantity`` on a partially credited order.
    """

    product_id: int | None
    description: str | None
    quantity: float | None
    uncredited_quantity: float | None
    gross_amount: float | None
    currency: str | None
    vat_text: str | None
    category: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any], category: str | None = None) -> OrderLine:
        product_id = _pick(data, "product_id", "productId")
        return cls(
            product_id=int(product_id) if product_id is not None else None,
            description=_pick(data, "description"),
            quantity=_pick(data, "quantity"),
            uncredited_quantity=_pick(data, "uncredited_quantity", "uncreditedQuantity"),
            gross_amount=_pick(data, "gross_amount", "grossAmount"),
            currency=_pick(data, "currency"),
            vat_text=_pick(data, "vat_text", "vatText"),
            category=category,
            raw=data,
        )

    @property
    def is_fully_credited(self) -> bool:
        """True when the whole line was refunded."""
        return self.uncredited_quantity == 0 and (self.quantity or 0) > 0


@dataclass(slots=True)
class OrderAdjustment:
    """A non-product amount on an order: a fee, a deposit, a credit, a total."""

    description: str | None
    gross_amount: float | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> OrderAdjustment:
        return cls(
            description=_pick(data, "description"),
            gross_amount=_pick(data, "gross_amount", "grossAmount"),
        )


@dataclass(slots=True)
class OrderDetail:
    """A placed order with its itemised lines, from ``GET /orders/{number}/``.

    The order list carries only totals, so the lines come from here. ``summary``
    repeats the list entry (in camelCase), so it is parsed as an :class:`Order`.
    """

    order: Order
    lines: list[OrderLine]
    adjustments: list[OrderAdjustment]
    product_count: int | None
    product_count_delivered: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> OrderDetail:
        summary = _pick(data, "summary", default={}) or {}
        items = _pick(data, "items", default={}) or {}

        lines: list[OrderLine] = []
        for group in _pick(items, "item_groups", "itemGroups", default=[]) or []:
            category = _pick(group, "name")
            for line in _pick(group, "items", default=[]) or []:
                lines.append(OrderLine.from_api(line, category))

        # Fees, deposits, credits and the totals live in their own groups.
        adjustments: list[OrderAdjustment] = []
        for group in _pick(items, "extra_item_groups", "extraItemGroups", default=[]) or []:
            for line in _pick(group, "items", default=[]) or []:
                adjustments.append(OrderAdjustment.from_api(line))

        return cls(
            order=Order.from_api(summary),
            lines=lines,
            adjustments=adjustments,
            product_count=_pick(items, "product_count", "productCount"),
            product_count_delivered=_pick(items, "product_count_delivered", "productCountDelivered"),
            raw=data,
        )

    @property
    def order_number(self) -> str | None:
        return self.order.order_number

    @property
    def total(self) -> float | None:
        """The order total, taken from the summary rather than re-derived."""
        return _pick(self.raw.get("summary") or {}, "gross_amount", "grossAmount")

    @property
    def currency(self) -> str | None:
        return _pick(self.raw.get("summary") or {}, "currency")

    @property
    def lines_total(self) -> float:
        """Sum of the product lines, excluding fees, deposits and credits."""
        return round(sum(line.gross_amount or 0.0 for line in self.lines), 2)

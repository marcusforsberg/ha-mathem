"""Dietary profiles.

Profiles are the only place diet rules live; nothing is hardcoded and the
integration ships with none, so it is usable by a household with no
restrictions. ``inherits`` lets a profile start from another and override
specific keys, so shared rules are maintained once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Policy values for a missing risk-data row.
ON_MISSING_REJECT = "reject"
ON_MISSING_WARN = "warn"

# Maps a human allergen name to the keyword fragments that betray its presence
# in the free-text ``Allergener`` row. Both Swedish and English keys are
# accepted. EU convention capitalises allergens inline (VETEmjöl), so matching
# is always case-insensitive. Unknown keys fall back to matching the key itself.
ALLERGEN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "gluten": (
        "gluten", "vete", "wheat", "råg", "rag", "rye", "korn", "barley",
        "havre", "oat", "dinkel", "spelt", "kamut", "durum", "bulgur",
        "couscous", "mannagryn", "seitan",
    ),
    "mjölk": ("mjölk", "mjolk", "laktos", "lactose", "milk", "grädde", "gradde",
              "ost", "smör", "smor", "vassle", "whey", "kasein", "casein", "dairy"),
    "laktos": ("laktos", "lactose", "mjölk", "mjolk", "milk"),
    "milk": ("milk", "mjölk", "mjolk", "laktos", "lactose", "dairy"),
    "ägg": ("ägg", "agg", "egg", "äggula", "äggvita", "albumin", "ovo"),
    "egg": ("egg", "ägg", "agg", "albumin"),
    "soja": ("soja", "soy", "soya"),
    "soy": ("soy", "soja", "soya"),
    "nöt": ("nöt", "not ", "mandel", "hasselnöt", "valnöt", "cashew", "pistage",
            "pekan", "paranöt", "macadamia", "nut", "almond", "walnut"),
    "nuts": ("nut", "nöt", "almond", "hazelnut", "cashew", "walnut", "pistachio"),
    "jordnöt": ("jordnöt", "jordnot", "peanut", "arachis"),
    "peanut": ("peanut", "jordnöt", "jordnot", "arachis"),
    "fisk": ("fisk", "fish", "torsk", "lax", "sill", "makrill", "tonfisk"),
    "fish": ("fish", "fisk", "cod", "salmon", "tuna"),
    "skaldjur": ("skaldjur", "räka", "raka", "krabba", "hummer", "crab", "shrimp",
                 "prawn", "musslor", "ostron", "shellfish", "crustacean"),
    "shellfish": ("shellfish", "skaldjur", "shrimp", "crab", "prawn", "mollusc"),
    "sesam": ("sesam", "sesame", "tahini"),
    "sesame": ("sesame", "sesam", "tahini"),
    "selleri": ("selleri", "celery"),
    "senap": ("senap", "mustard"),
    "mustard": ("mustard", "senap"),
    "sulfit": ("sulfit", "sulphite", "sulfite", "svaveldioxid"),
    "lupin": ("lupin",),
}


def allergen_keywords(name: str) -> tuple[str, ...]:
    """Keyword fragments for an allergen name, defaulting to the name itself."""
    return ALLERGEN_KEYWORDS.get(name.casefold(), (name.casefold(),))


def _tokens(values: Any) -> frozenset[str]:
    """Normalise a list of category tokens: ints stringified, names casefolded."""
    result: set[str] = set()
    for value in values or []:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            result.add(str(value))
        else:
            result.add(str(value).casefold())
    return frozenset(result)


def _lower_tuple(values: Any) -> tuple[str, ...]:
    return tuple(str(v).casefold() for v in (values or []))


@dataclass(slots=True, frozen=True)
class Profile:
    """A resolved dietary profile (inheritance already applied)."""

    name: str
    default: bool = False
    veto_categories: frozenset[str] = field(default_factory=frozenset)
    allow_categories: frozenset[str] = field(default_factory=frozenset)
    veto_ingredients: tuple[str, ...] = ()
    require_allergen_free: tuple[str, ...] = ()
    prefer_filters: tuple[str, ...] = ()
    require_filters: tuple[str, ...] = ()
    on_missing_allergen_data: str = ON_MISSING_WARN

    @property
    def has_restrictions(self) -> bool:
        return bool(
            self.veto_categories
            or self.veto_ingredients
            or self.require_allergen_free
            or self.require_filters
        )


# Keys a child profile may set; used to know what overrides the parent.
_PROFILE_KEYS = (
    "default",
    "veto_categories",
    "allow_categories",
    "veto_ingredients",
    "require_allergen_free",
    "prefer_filters",
    "require_filters",
    "on_missing_allergen_data",
)


def _resolve_raw(name: str, configs: dict[str, dict[str, Any]], _seen: set[str]) -> dict[str, Any]:
    """Merge a profile's raw config over its parent's, recursively."""
    if name in _seen:
        raise ValueError(f"circular profile inheritance involving {name!r}")
    if name not in configs:
        raise ValueError(f"profile {name!r} inherits from unknown profile")
    _seen.add(name)
    cfg = configs[name]
    parent_name = cfg.get("inherits")
    base: dict[str, Any] = {}
    if parent_name:
        base = _resolve_raw(parent_name, configs, _seen)
    merged = dict(base)
    for key in _PROFILE_KEYS:
        if key in cfg:
            merged[key] = cfg[key]
    return merged


def build_profiles(configs: dict[str, dict[str, Any]]) -> dict[str, Profile]:
    """Build resolved :class:`Profile` objects from raw config, applying inheritance."""
    profiles: dict[str, Profile] = {}
    for name in configs:
        merged = _resolve_raw(name, configs, set())
        profiles[name] = Profile(
            name=name,
            default=bool(merged.get("default", False)),
            veto_categories=_tokens(merged.get("veto_categories")),
            allow_categories=_tokens(merged.get("allow_categories")),
            veto_ingredients=_lower_tuple(merged.get("veto_ingredients")),
            require_allergen_free=_lower_tuple(merged.get("require_allergen_free")),
            prefer_filters=tuple(merged.get("prefer_filters") or ()),
            require_filters=tuple(merged.get("require_filters") or ()),
            on_missing_allergen_data=str(
                merged.get("on_missing_allergen_data", ON_MISSING_WARN)
            ).casefold(),
        )
    return profiles


def default_profile_name(profiles: dict[str, Profile]) -> str | None:
    """Name of the profile flagged ``default``, or the sole profile, or None."""
    for name, profile in profiles.items():
        if profile.default:
            return name
    if len(profiles) == 1:
        return next(iter(profiles))
    return None

"""Profile-driven resolver: turn a free-text query into a safe product id.

Safety tiers, applied in order, stopping at the first that resolves:

1. **Alias pin** - zero inference. A pinned id bypasses tiers 2 and 3, because
   the user has asserted the id and a sparse badge must not override that.
2. **Category veto** on leaf ids from the detail endpoint.
3. **Ingredient / allergen veto** on the Ingredienser and Allergener rows,
   failing closed when a risk row is absent.
4. **Badge filter** - opt-in per profile, a precision/ranking hint only.

If none establishes safety the result is ``needs_disambiguation`` with
candidates. The resolver never widens a query and never substitutes silently.

Hard invariants enforced here:
- The only lever a free-text caller has is the search string. A raw product id
  is treated as a deliberate assertion (like a pin), never inferred.
- Promotion and pill data never reaches ranking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .products import ProductsClient
from .profiles import ON_MISSING_REJECT, Profile, allergen_keywords

_LOGGER = logging.getLogger(__name__)

DEFAULT_CANDIDATE_LIMIT = 5


def normalize(text: str) -> str:
    return " ".join(str(text).casefold().split())


# ---------------------------------------------------------------------------
# Alias map
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AliasEntry:
    """One entry in the pantry alias map.

    Kinds are mutually exclusive in practice:
    - ``product_id`` set -> a pin (optionally with ``also`` synonyms).
    - ``ambiguous`` set -> never auto-resolves; prompts the user.
    - ``search`` set -> rewrites the query, optionally with ``require_filters``.
    """

    keyword: str
    product_id: int | None = None
    also: tuple[str, ...] = ()
    ambiguous: tuple[int, ...] = ()
    prompt: str | None = None
    search: str | None = None
    require_filters: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, keyword: str, data: dict[str, Any]) -> AliasEntry:
        return cls(
            keyword=keyword,
            product_id=int(data["product_id"]) if data.get("product_id") is not None else None,
            also=tuple(str(a) for a in (data.get("also") or ())),
            ambiguous=tuple(int(a) for a in (data.get("ambiguous") or ())),
            prompt=data.get("prompt"),
            search=data.get("search"),
            require_filters=tuple(data.get("require_filters") or ()),
        )

    @property
    def kind(self) -> str:
        if self.ambiguous:
            return "ambiguous"
        if self.product_id is not None:
            return "pinned"
        if self.search is not None:
            return "search"
        return "empty"


class AliasMap:
    """Lookup over pantry aliases, including ``also`` synonyms."""

    def __init__(self, raw: dict[str, dict[str, Any]] | None = None) -> None:
        self._entries: dict[str, AliasEntry] = {}
        self._index: dict[str, str] = {}  # normalized keyword/synonym -> canonical key
        for keyword, data in (raw or {}).items():
            self.add(keyword, data)

    def add(self, keyword: str, data: dict[str, Any]) -> AliasEntry:
        entry = AliasEntry.from_dict(keyword, data)
        self._entries[keyword] = entry
        self._index[normalize(keyword)] = keyword
        for synonym in entry.also:
            self._index[normalize(synonym)] = keyword
        return entry

    def remove(self, keyword: str) -> bool:
        entry = self._entries.pop(keyword, None)
        if entry is None:
            return False
        self._index = {k: v for k, v in self._index.items() if v != keyword}
        return True

    def get(self, query: str) -> AliasEntry | None:
        canonical = self._index.get(normalize(query))
        return self._entries.get(canonical) if canonical else None

    def as_dict(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for keyword, entry in self._entries.items():
            data: dict[str, Any] = {}
            if entry.product_id is not None:
                data["product_id"] = entry.product_id
            if entry.also:
                data["also"] = list(entry.also)
            if entry.ambiguous:
                data["ambiguous"] = list(entry.ambiguous)
            if entry.prompt:
                data["prompt"] = entry.prompt
            if entry.search:
                data["search"] = entry.search
            if entry.require_filters:
                data["require_filters"] = list(entry.require_filters)
            out[keyword] = data
        return out


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class ResolveStatus(str, Enum):
    RESOLVED = "resolved"
    NEEDS_DISAMBIGUATION = "needs_disambiguation"


@dataclass(slots=True)
class Candidate:
    """A product considered during resolution, safe or rejected."""

    product_id: int
    name: str
    safe: bool
    reason: str
    tier: str | None = None
    warnings: list[str] = field(default_factory=list)
    promotion: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "safe": self.safe,
            "reason": self.reason,
            "tier": self.tier,
            "warnings": self.warnings,
            "promotion": self.promotion,
        }


@dataclass(slots=True)
class ResolveResult:
    status: ResolveStatus
    product_id: int | None = None
    tier: str | None = None
    candidate: Candidate | None = None
    candidates: list[Candidate] = field(default_factory=list)
    prompt: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.status is ResolveStatus.RESOLVED

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "product_id": self.product_id,
            "tier": self.tier,
            "candidate": self.candidate.as_dict() if self.candidate else None,
            "candidates": [c.as_dict() for c in self.candidates],
            "prompt": self.prompt,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class _Verdict:
    safe: bool
    tier: str
    reason: str
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class Resolver:
    def __init__(
        self,
        products: ProductsClient,
        aliases: AliasMap,
        profiles: dict[str, Profile],
        *,
        default_profile: str | None,
    ) -> None:
        self._products = products
        self._aliases = aliases
        self._profiles = profiles
        self._default_profile = default_profile

    def _profile(self, name: str | None) -> Profile:
        chosen = name or self._default_profile
        if chosen and chosen in self._profiles:
            return self._profiles[chosen]
        # No profile configured, or an unknown name: fall back to an
        # unrestricted profile so a household with no diet rules just works.
        return Profile(name=chosen or "__none__")

    async def resolve(
        self,
        query: str,
        *,
        profile: str | None = None,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> ResolveResult:
        prof = self._profile(profile)
        search_query = query
        require_filters = list(prof.require_filters)

        # -- Tier 1: alias -------------------------------------------------
        alias = self._aliases.get(query)
        if alias is not None:
            if alias.kind == "pinned":
                return await self._pinned_result(alias.product_id)  # type: ignore[arg-type]
            if alias.kind == "ambiguous":
                return await self._ambiguous_result(alias)
            if alias.kind == "search":
                search_query = alias.search or query
                require_filters.extend(alias.require_filters)

        # -- Gather candidates --------------------------------------------
        products = await self._products.search_paged(
            search_query, filters=require_filters, limit=limit
        )
        if not products:
            return ResolveResult(
                status=ResolveStatus.NEEDS_DISAMBIGUATION,
                prompt=f"Inga träffar för {search_query!r}.",
                warnings=["no search results; check the query or filter tokens"],
            )

        ranked = await self._rank(products, search_query, prof, require_filters)

        # -- Tiers 2-4 per candidate, first safe wins ---------------------
        rejected: list[Candidate] = []
        for product in ranked:
            detail = await self._products.get_product(product.id)
            verdict = self._vet(detail, prof)
            name = detail.product.full_name
            promo = detail.product.promotion_block()
            if verdict.safe:
                candidate = Candidate(
                    product_id=product.id,
                    name=name,
                    safe=True,
                    reason=verdict.reason,
                    tier=verdict.tier,
                    warnings=verdict.warnings,
                    promotion=promo,
                )
                return ResolveResult(
                    status=ResolveStatus.RESOLVED,
                    product_id=product.id,
                    tier=verdict.tier,
                    candidate=candidate,
                    warnings=verdict.warnings,
                )
            rejected.append(
                Candidate(
                    product_id=product.id,
                    name=name,
                    safe=False,
                    reason=verdict.reason,
                    tier=verdict.tier,
                    warnings=verdict.warnings,
                    promotion=promo,
                )
            )

        return ResolveResult(
            status=ResolveStatus.NEEDS_DISAMBIGUATION,
            candidates=rejected,
            prompt=(
                f"Hittade inget som passar profilen {prof.name!r} för "
                f"{search_query!r}."
            ),
            warnings=["no candidate cleared the profile's vetoes"],
        )

    # -- alias helpers -----------------------------------------------------

    async def _pinned_result(self, product_id: int) -> ResolveResult:
        """A pin asserts the id; tiers 2-3 are bypassed. Fetch name if possible."""
        name = str(product_id)
        promo: dict[str, Any] = {}
        try:
            detail = await self._products.get_product(product_id)
            name = detail.product.full_name
            promo = detail.product.promotion_block()
        except Exception:  # noqa: BLE001 - name lookup is best-effort
            _LOGGER.debug("could not fetch name for pinned id %s", product_id)
        candidate = Candidate(
            product_id=product_id, name=name, safe=True, tier="alias-pin",
            reason="alias pin (user-asserted id)", promotion=promo,
        )
        return ResolveResult(
            status=ResolveStatus.RESOLVED,
            product_id=product_id,
            tier="alias-pin",
            candidate=candidate,
        )

    async def _ambiguous_result(self, alias: AliasEntry) -> ResolveResult:
        candidates: list[Candidate] = []
        for pid in alias.ambiguous:
            name = str(pid)
            promo: dict[str, Any] = {}
            try:
                detail = await self._products.get_product(pid)
                name = detail.product.full_name
                promo = detail.product.promotion_block()
            except Exception:  # noqa: BLE001
                pass
            candidates.append(
                Candidate(product_id=pid, name=name, safe=False, tier="ambiguous-alias",
                          reason="ambiguous alias; user must choose", promotion=promo)
            )
        return ResolveResult(
            status=ResolveStatus.NEEDS_DISAMBIGUATION,
            candidates=candidates,
            prompt=alias.prompt or f"Vilken {alias.keyword}?",
        )

    # -- ranking (never touches promotions/pills) --------------------------

    async def _rank(self, products, query, profile: Profile, require_filters):
        """Stable-sort candidates, floating prefer-filter matches to the top.

        Uses at most one extra filtered search to identify preferred ids. Reads
        no promotion or pill data.
        """
        if not profile.prefer_filters:
            return products
        combined = list(require_filters) + list(profile.prefer_filters)
        try:
            preferred = await self._products.search_paged(
                query, filters=combined, limit=len(products) or DEFAULT_CANDIDATE_LIMIT
            )
        except Exception:  # noqa: BLE001 - ranking is best-effort
            return products
        preferred_ids = {p.id for p in preferred}
        return sorted(products, key=lambda p: p.id not in preferred_ids)

    # -- vetting (tiers 2 and 3) ------------------------------------------

    def _vet(self, detail, profile: Profile) -> _Verdict:
        if not profile.has_restrictions:
            return _Verdict(True, "unrestricted", "no restrictions in profile")

        warnings: list[str] = []

        # Tier 2: category veto on leaf ids (Prismatch tree already excluded).
        cats = detail.classification_categories()
        allowlisted = any(
            profile.allow_categories & cat.ancestor_tokens() for cat in cats
        ) if profile.allow_categories else False
        if profile.veto_categories and not allowlisted:
            for cat in cats:
                hit = profile.veto_categories & cat.leaf_tokens()
                if hit:
                    return _Verdict(
                        False, "category-veto",
                        f"vetoed category {sorted(hit)} ({cat.name})",
                    )

        # Tier 3: ingredient veto.
        ingredients = detail.ingredients_text
        if profile.veto_ingredients:
            if ingredients is None:
                if profile.on_missing_allergen_data == ON_MISSING_REJECT:
                    return _Verdict(
                        False, "ingredient-veto",
                        "Ingredienser row absent; failing closed",
                    )
                warnings.append("Ingredienser row absent; could not check vetoed ingredients")
            else:
                haystack = ingredients.casefold()
                for banned in profile.veto_ingredients:
                    if banned in haystack:
                        return _Verdict(
                            False, "ingredient-veto",
                            f"contains vetoed ingredient {banned!r}",
                        )

        # Tier 3: allergen requirement, checked against the Allergener row.
        allergens = detail.allergens_text
        if profile.require_allergen_free:
            if allergens is None:
                # Missing row is unknown, never safe. Fail closed or warn.
                if profile.on_missing_allergen_data == ON_MISSING_REJECT:
                    return _Verdict(
                        False, "allergen-veto",
                        "Allergener row absent; failing closed",
                    )
                warnings.append("Allergener row absent; allergen-free requirement unverified")
            else:
                haystack = allergens.casefold()
                for allergen in profile.require_allergen_free:
                    for keyword in allergen_keywords(allergen):
                        if keyword in haystack:
                            return _Verdict(
                                False, "allergen-veto",
                                f"Allergener lists {allergen!r} (matched {keyword!r})",
                            )

        return _Verdict(True, "ingredient-allergen-clear", "cleared category and ingredient/allergen vetoes", warnings)

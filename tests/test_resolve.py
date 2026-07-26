"""Resolver safety: generic terms never resolve to forbidden products, missing
allergen data fails closed, and a pin bypasses the vetoes."""

from __future__ import annotations

import pytest
from conftest import FakeCatalogSession, make_category, make_detail

from mathem_client.products import ProductsClient
from mathem_client.profiles import Profile, build_profiles
from mathem_client.resolve import AliasMap, ResolveStatus, Resolver

# Shared products.
DAIRY = make_detail(
    92,
    "Arla Mellanmjölk 1.5%",
    categories=[make_category(92, "Mellanmjölk", parents=[{"id": 78, "name": "Mejeri"}, {"id": 91, "name": "Mjölk"}])],
    ingredients="mjölk",
    allergens="mjölk",
    badges=[],
    promotion={"title": "2 för 25 kr", "displayStyle": "multibuy"},
)
SOY = make_detail(
    5454,
    "Alpro Sojamjölk Naturell Osötad",
    categories=[make_category(134, "Växtbaserad dryck", parents=[{"id": 78, "name": "Mejeri"}, {"id": 133, "name": "Växtbaserat"}])],
    ingredients="vatten, sojabönor",
    allergens="soja",
    badges=["badges:is_vegan"],
)
BREAD_NO_ALLERGEN_ROW = make_detail(
    700,
    "Pågen Lingongrova",
    categories=[make_category(555, "Bröd", parents=[{"id": 500, "name": "Skafferi"}])],
    ingredients="vetemjöl, vatten, sirap",
    allergens=None,  # no Allergener row -> unknown
    badges=[],
)
PANCAKE = make_detail(
    800,
    "Färdig Pannkaka",
    ingredients="vetemjöl, ägg, mjölk",
    allergens="vete, ägg, mjölk",
    badges=[],
)


def _resolver(catalog, aliases=None, profiles=None, default="marcus"):
    session = FakeCatalogSession(catalog)
    products = ProductsClient(session)
    return Resolver(
        products,
        AliasMap(aliases or {}),
        profiles or PROFILES,
        default_profile=default,
    )


PROFILES = build_profiles(
    {
        "marcus": {
            "default": True,
            "veto_categories": ["kött", "chark", "fisk", "92"],
            "veto_ingredients": ["ägg"],
            "require_allergen_free": ["gluten"],
            "prefer_filters": ["badges:is_vegan"],
            "on_missing_allergen_data": "reject",
        }
    }
)


async def test_generic_term_never_resolves_to_vetoed_dairy():
    resolver = _resolver([DAIRY, SOY])
    result = await resolver.resolve("mjölk", profile="marcus")
    assert result.resolved
    assert result.product_id == 5454  # the plant drink, never the dairy
    assert result.product_id != 92


async def test_promotion_cannot_rescue_a_vetoed_product():
    # DAIRY carries a multibuy promotion; it must still be vetoed.
    resolver = _resolver([DAIRY])
    result = await resolver.resolve("mjölk", profile="marcus")
    assert result.status is ResolveStatus.NEEDS_DISAMBIGUATION
    assert all(c.product_id == 92 and not c.safe for c in result.candidates)
    assert result.candidates[0].tier == "category-veto"


async def test_missing_allergen_row_fails_closed_when_reject():
    profiles = build_profiles(
        {"strict": {"require_allergen_free": ["gluten"], "on_missing_allergen_data": "reject"}}
    )
    resolver = _resolver([BREAD_NO_ALLERGEN_ROW], profiles=profiles, default="strict")
    result = await resolver.resolve("Lingongrova", profile="strict")
    assert result.status is ResolveStatus.NEEDS_DISAMBIGUATION
    assert "absent" in result.candidates[0].reason


async def test_missing_allergen_row_warns_when_warn():
    profiles = build_profiles(
        {"lenient": {"require_allergen_free": ["gluten"], "on_missing_allergen_data": "warn"}}
    )
    resolver = _resolver([BREAD_NO_ALLERGEN_ROW], profiles=profiles, default="lenient")
    result = await resolver.resolve("Lingongrova", profile="lenient")
    assert result.resolved
    assert any("Allergener row absent" in w for w in result.warnings)


async def test_allergen_row_detects_gluten_grain():
    profiles = build_profiles(
        {"gf": {"require_allergen_free": ["gluten"], "on_missing_allergen_data": "reject"}}
    )
    bread = make_detail(701, "Rågbröd", ingredients="rågmjöl", allergens="vete, korn, råg")
    resolver = _resolver([bread], profiles=profiles, default="gf")
    result = await resolver.resolve("Rågbröd", profile="gf")
    assert result.status is ResolveStatus.NEEDS_DISAMBIGUATION
    assert result.candidates[0].tier == "allergen-veto"
    assert "vete" in result.candidates[0].reason


async def test_ingredient_veto():
    profiles = build_profiles({"noegg": {"veto_ingredients": ["ägg"]}})
    resolver = _resolver([PANCAKE], profiles=profiles, default="noegg")
    result = await resolver.resolve("Pannkaka", profile="noegg")
    assert result.status is ResolveStatus.NEEDS_DISAMBIGUATION
    assert "ägg" in result.candidates[0].reason


async def test_alias_pin_bypasses_category_veto():
    # 92 is dairy, which marcus vetoes; a pin asserts it anyway.
    resolver = _resolver([DAIRY], aliases={"lingonsylt": {"product_id": 92}})
    result = await resolver.resolve("lingonsylt", profile="marcus")
    assert result.resolved
    assert result.tier == "alias-pin"
    assert result.product_id == 92


async def test_ambiguous_alias_never_auto_resolves():
    resolver = _resolver([DAIRY, SOY], aliases={"mjölk": {"ambiguous": [92, 5454], "prompt": "Vilken mjölk?"}})
    result = await resolver.resolve("mjölk", profile="marcus")
    assert result.status is ResolveStatus.NEEDS_DISAMBIGUATION
    assert result.prompt == "Vilken mjölk?"
    assert {c.product_id for c in result.candidates} == {92, 5454}


async def test_category_veto_targets_leaf_not_ancestor():
    # Vetoing ancestor 91 must NOT block the dairy whose leaf is 92.
    profiles = build_profiles({"veto91": {"veto_categories": ["91"]}})
    resolver = _resolver([DAIRY], profiles=profiles, default="veto91")
    result = await resolver.resolve("mjölk", profile="veto91")
    assert result.resolved and result.product_id == 92

    profiles = build_profiles({"veto92": {"veto_categories": ["92"]}})
    resolver = _resolver([DAIRY], profiles=profiles, default="veto92")
    result = await resolver.resolve("mjölk", profile="veto92")
    assert result.status is ResolveStatus.NEEDS_DISAMBIGUATION


async def test_allowlist_subtree_overrides_leaf_veto():
    profiles = build_profiles({"p": {"veto_categories": ["134"], "allow_categories": ["133"]}})
    resolver = _resolver([SOY], profiles=profiles, default="p")
    result = await resolver.resolve("sojamjölk", profile="p")
    assert result.resolved and result.product_id == 5454

    profiles = build_profiles({"p": {"veto_categories": ["134"]}})
    resolver = _resolver([SOY], profiles=profiles, default="p")
    result = await resolver.resolve("sojamjölk", profile="p")
    assert result.status is ResolveStatus.NEEDS_DISAMBIGUATION


async def test_badge_is_a_ranking_hint_not_a_gate():
    # No badge, no restrictions -> still resolves. Badge never gates.
    profiles = build_profiles({"pref": {"prefer_filters": ["badges:is_vegan"]}})
    plain = make_detail(900, "Vanlig Gurka", ingredients="gurka", allergens="", badges=[])
    resolver = _resolver([plain], profiles=profiles, default="pref")
    result = await resolver.resolve("Gurka", profile="pref")
    assert result.resolved and result.product_id == 900


async def test_prefer_filter_floats_badged_product_over_promoted_one():
    # A promotes hard but has no badge; B has the badge. Ranking must pick B,
    # proving promotion data never reaches ranking.
    profiles = build_profiles({"pref": {"prefer_filters": ["badges:is_vegan"]}})
    promoted = make_detail(901, "Gurka Erbjudande", ingredients="gurka", allergens="",
                           badges=[], promotion={"title": "3 för 2", "displayStyle": "multibuy"})
    badged = make_detail(902, "Gurka Eko", ingredients="gurka", allergens="",
                         badges=["badges:is_vegan"])
    resolver = _resolver([promoted, badged], profiles=profiles, default="pref")
    result = await resolver.resolve("Gurka", profile="pref")
    assert result.resolved and result.product_id == 902


async def test_search_rewrite_alias_applies_query_and_required_filter():
    # 'bröd' rewrites to 'glutenfritt bröd' and pins a hard filter. Both
    # products match the rewritten text; only the badged one survives the
    # required filter.
    gf = make_detail(300, "Semper Glutenfritt Bröd", ingredients="majsstärkelse",
                     allergens="", badges=["allergens_free:gluten_free"])
    decoy = make_detail(301, "Semper Glutenfritt Bröd Frö", ingredients="majsstärkelse",
                        allergens="", badges=[])
    resolver = _resolver(
        [gf, decoy],
        aliases={"bröd": {"search": "glutenfritt bröd", "require_filters": ["allergens_free:gluten_free"]}},
        profiles={},
        default=None,
    )
    result = await resolver.resolve("bröd", profile=None)
    assert result.resolved
    assert result.product_id == 300


async def test_no_results_reports_disambiguation_not_crash():
    resolver = _resolver([SOY])
    result = await resolver.resolve("obefintlig produkt", profile="marcus")
    assert result.status is ResolveStatus.NEEDS_DISAMBIGUATION
    assert result.candidates == []


async def test_pinned_alias_carries_its_default_quantity():
    resolver = _resolver([SOY], aliases={"tvättmedel": {"product_id": 5454, "default_quantity": 2}})
    result = await resolver.resolve("tvättmedel", profile="marcus")
    assert result.resolved
    assert result.default_quantity == 2


async def test_pin_without_a_default_quantity_reports_none():
    resolver = _resolver([SOY], aliases={"sojamjölk": {"product_id": 5454}})
    result = await resolver.resolve("sojamjölk", profile="marcus")
    assert result.resolved
    assert result.default_quantity is None


async def test_search_alias_can_carry_a_default_quantity():
    gf = make_detail(300, "Semper Glutenfritt Bröd", ingredients="majsstärkelse",
                     allergens="", badges=["allergens_free:gluten_free"])
    resolver = _resolver(
        [gf],
        aliases={"bröd": {"search": "glutenfritt bröd", "default_quantity": 3}},
        profiles={}, default=None,
    )
    result = await resolver.resolve("bröd", profile=None)
    assert result.resolved and result.default_quantity == 3

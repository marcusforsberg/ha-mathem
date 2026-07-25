"""Profile inheritance: children override specified keys, inherit the rest."""

from __future__ import annotations

import pytest

from mathem_client.profiles import build_profiles


def test_inheritance_overrides_specified_keys_only():
    profiles = build_profiles(
        {
            "marcus": {
                "default": True,
                "veto_categories": ["kött", "chark", "fisk", "92"],
                "veto_ingredients": ["ägg", "avokado"],
                "require_allergen_free": ["gluten"],
                "prefer_filters": ["badges:is_vegan"],
                "on_missing_allergen_data": "reject",
            },
            "partner": {
                "inherits": "marcus",
                "require_allergen_free": [],
                "veto_ingredients": ["rödlök"],
                "on_missing_allergen_data": "warn",
            },
        }
    )
    marcus, partner = profiles["marcus"], profiles["partner"]
    # Inherited unchanged:
    assert "92" in partner.veto_categories
    assert partner.prefer_filters == ("badges:is_vegan",)
    # Overridden:
    assert partner.require_allergen_free == ()
    assert partner.veto_ingredients == ("rödlök",)
    assert partner.on_missing_allergen_data == "warn"
    # Parent untouched:
    assert marcus.require_allergen_free == ("gluten",)
    assert marcus.on_missing_allergen_data == "reject"


def test_category_tokens_normalised_ids_and_names():
    profiles = build_profiles({"p": {"veto_categories": [92, "Kött"]}})
    assert profiles["p"].veto_categories == frozenset({"92", "kött"})


def test_circular_inheritance_raises():
    with pytest.raises(ValueError):
        build_profiles({"a": {"inherits": "b"}, "b": {"inherits": "a"}})


def test_unknown_parent_raises():
    with pytest.raises(ValueError):
        build_profiles({"a": {"inherits": "ghost"}})


def test_empty_profile_has_no_restrictions():
    profiles = build_profiles({"none": {}})
    assert not profiles["none"].has_restrictions

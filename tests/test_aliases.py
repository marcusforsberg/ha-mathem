"""Alias map logic: lookup, synonyms, the alias kinds, removal, round-trip.

These are the pantry's substance. The HA ``Pantry`` wrapper is a thin adapter
over ``AliasMap`` (load -> AliasMap(raw), save -> as_dict), plus merge/replace on
import; the round-trip test here is what guards the persisted shape.
"""

from __future__ import annotations

import json

from mathem_client.resolve import AliasMap


def test_pin_lookup_is_case_insensitive():
    m = AliasMap({"lingonsylt": {"product_id": 9435}})
    entry = m.get("Lingonsylt")
    assert entry is not None
    assert entry.kind == "pinned"
    assert entry.product_id == 9435


def test_synonyms_resolve_to_the_canonical_entry():
    m = AliasMap({"sojamjölk": {"product_id": 5454, "also": ["soja", "sojadryck", "soymilk"]}})
    for term in ("soja", "SOJADRYCK", "soymilk", "sojamjölk"):
        entry = m.get(term)
        assert entry is not None and entry.product_id == 5454


def test_ambiguous_kind_exposes_candidates_and_prompt():
    m = AliasMap({"mjölk": {"ambiguous": [5454, 2190, 65962], "prompt": "Vilken mjölk?"}})
    entry = m.get("mjölk")
    assert entry.kind == "ambiguous"
    assert entry.ambiguous == (5454, 2190, 65962)
    assert entry.prompt == "Vilken mjölk?"


def test_search_rewrite_kind():
    m = AliasMap({"bröd": {"search": "glutenfritt bröd", "require_filters": ["allergens_free:gluten_free"]}})
    entry = m.get("bröd")
    assert entry.kind == "search"
    assert entry.search == "glutenfritt bröd"
    assert entry.require_filters == ("allergens_free:gluten_free",)


def test_add_then_lookup():
    m = AliasMap()
    m.add("kaffe", {"product_id": 111})
    assert m.get("kaffe").product_id == 111


def test_remove_clears_keyword_and_its_synonyms():
    m = AliasMap({"sojamjölk": {"product_id": 5454, "also": ["soja"]}})
    assert m.remove("sojamjölk") is True
    assert m.get("sojamjölk") is None
    assert m.get("soja") is None  # the synonym index entry is cleaned up too
    assert m.remove("does-not-exist") is False


def test_as_dict_round_trips_through_json():
    original = {
        "lingonsylt": {"product_id": 9435},
        "sojamjölk": {"product_id": 5454, "also": ["soja", "soymilk"]},
        "mjölk": {"ambiguous": [5454, 2190], "prompt": "Vilken mjölk?"},
        "bröd": {"search": "glutenfritt bröd", "require_filters": ["allergens_free:gluten_free"]},
    }
    m = AliasMap(original)
    dumped = m.as_dict()
    # Rebuilding from the dump yields the same dump (stable round-trip).
    assert AliasMap(dumped).as_dict() == dumped
    # And it survives the JSON serialization the Store performs.
    assert json.loads(json.dumps(dumped)) == dumped
    # The four kinds are all preserved.
    assert dumped["lingonsylt"] == {"product_id": 9435}
    assert dumped["sojamjölk"]["also"] == ["soja", "soymilk"]
    assert dumped["mjölk"]["ambiguous"] == [5454, 2190]
    assert dumped["bröd"]["require_filters"] == ["allergens_free:gluten_free"]


def test_unknown_keyword_returns_none():
    assert AliasMap({"kaffe": {"product_id": 1}}).get("te") is None

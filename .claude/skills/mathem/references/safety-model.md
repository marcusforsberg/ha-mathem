# Safety model, profiles and the pantry

Read this when a task touches dietary safety, when writing or repairing
`profiles_json`, or when deciding how much confidence to put behind a claim that
a product suits someone.

Contents:
- [Why the model is shaped this way](#why-the-model-is-shaped-this-way)
- [The four tiers](#the-four-tiers)
- [Reading a tier honestly](#reading-a-tier-honestly)
- [profiles_json schema](#profiles_json-schema)
- [Writing a profile that works](#writing-a-profile-that-works)
- [Allergen name matching](#allergen-name-matching)
- [The pantry alias map](#the-pantry-alias-map)
- [Integration options](#integration-options)

## Why the model is shaped this way

A generic spoken request like "add milk" must never silently put something
forbidden in the cart. The resolver's job is therefore not to find the best
match, it is to refuse to guess when guessing could be harmful. Two invariants
hold throughout:

- The only lever a free-text request has is the search string. A product id is
  used only when a human asserts it, as a pin or an explicit `product_id`.
- Promotion and pill data never reaches ranking, so a discount can never become
  a path around the diet gate.

This is worth internalising because it explains behaviour that otherwise looks
unhelpful. When resolution returns `needs_disambiguation` on a word the user
thinks is obvious, the correct response is to ask, not to work around it.

## The four tiers

Applied in order, stopping at the first that establishes safety.

**1. Alias pin.** A keyword the user pinned to a product id resolves with zero
inference and **bypasses tiers 2 and 3 entirely**. The reasoning: a household
buys roughly the same items, and a sparse or wrong badge must not override an
explicit human assertion. Tier string `alias-pin`.

**2. Category veto.** Leaf category ids from the product detail endpoint. More
reliable than marketing badges for excluding animal products, because badges
have poor recall. Tier string `category-veto` on rejection.

**3. Ingredient and allergen veto.** Substring matching against the free-text
Ingredienser and Allergener rows. When a required risk row is absent, the
profile's `on_missing_allergen_data` decides: `reject` fails closed, `warn`
allows but records a warning. Tier strings `ingredient-veto` and
`allergen-veto`; a clean pass is `ingredient-allergen-clear`.

**4. Badge filter.** Opt-in per profile via `prefer_filters`, used only as a
ranking and precision hint. Diet badges have high precision but poor recall, so
they are never the safety gate.

If nothing establishes safety, the result is `needs_disambiguation` carrying
every rejected candidate with a `reason` naming what disqualified it.

## Reading a tier honestly

The tier on a successful add is a claim about how much verification happened,
and conflating the tiers produces confidently wrong answers about food safety.

| Tier | What was actually checked |
| --- | --- |
| `alias-pin` | Nothing. The user asserted this product. |
| `unrestricted` | Nothing, because the profile has no restrictions. |
| `ingredient-allergen-clear` | Categories, ingredients and allergens all passed. |

So when someone asks "is that gluten free?" about an item added at
`alias-pin`, the integration has not answered that question. Call `get_product`
and read the Allergener row, or run `audit_cart`. And say which of the two you
did, because "the integration accepted it" is not the same claim as "the label
says it is free of gluten".

`audit_cart` is explicitly advisory. Its own response carries the disclaimer
"Advisory only. Read the label before consuming." Pass that along in substance
when the stakes are real, such as coeliac disease or a serious allergy. An
empty `verdicts` object with `profiles: []` means nothing was checked at all,
which must never be reported as a clean result.

## profiles_json schema

Profiles are the only place diet rules live. Nothing is hardcoded, and the
integration ships with none, so it works out of the box for a household with no
restrictions. Stored as a JSON object in the integration options, keyed by
profile name.

```json
{
  "marcus": {
    "default": true,
    "veto_categories": ["kött", "chark", "fisk", "mejeri_leaf", "ägg"],
    "veto_ingredients": ["ägg", "äggvita"],
    "require_allergen_free": ["gluten"],
    "prefer_filters": ["badges:is_vegan"],
    "on_missing_allergen_data": "reject"
  },
  "partner": {
    "inherits": "marcus",
    "require_allergen_free": [],
    "veto_ingredients": [],
    "on_missing_allergen_data": "warn"
  }
}
```

| Key | Meaning |
| --- | --- |
| `default` | Marks the profile used when a call names none. |
| `inherits` | Start from another profile and override only the differing keys. Circular inheritance raises an error at build time. |
| `veto_categories` | Leaf category ids or names to exclude. |
| `allow_categories` | Subtree ids or names that suppress a veto, for example `133 Växtbaserat`. |
| `veto_ingredients` | Substrings matched case-insensitively against the Ingredienser row. |
| `require_allergen_free` | Allergen names checked against the Allergener row, not the badge. Swedish and English both work. |
| `prefer_filters` | Badge tokens used only for ranking. |
| `require_filters` | Badge tokens applied as hard search filters. AND-combined. |
| `on_missing_allergen_data` | `reject` to fail closed, `warn` to allow and flag. |

If no profile is flagged `default` and exactly one profile exists, that one is
used. With several profiles and no default, calls that omit `profile` get the
unrestricted fallback.

## Writing a profile that works

**Target leaf categories, not broad parents.** Vetoing a parent like
`91 Mjölk` also blocks the plant drinks filed under it, which is the opposite of
what a vegan profile wants. Veto `92 Mellanmjölk` and its siblings instead, or
pair a broad veto with `allow_categories: ["133 Växtbaserat"]`.

**Set `on_missing_allergen_data` deliberately.** `reject` is the right choice
for coeliac disease or a genuine allergy, because a missing Allergener row means
unknown rather than safe. It will cause more disambiguation prompts. That is the
tradeoff working as intended, not a bug to tune away.

**Use `require_filters` sparingly.** They become hard search filters, so an
overly narrow token yields no results at all, which surfaces as
`needs_disambiguation` with an empty candidate list and a warning about the
query or filter tokens. Prefer `prefer_filters` unless the filter is genuinely
non-negotiable.

**Verify a name change took effect.** Because an unknown profile name silently
falls back to unrestricted, renaming a profile without updating the blueprint
inputs and the options default quietly disables all filtering. After any rename,
run `audit_cart` with the new name and confirm the response's `profiles[]` is
populated.

## Allergen name matching

`require_allergen_free` entries expand to keyword fragments matched
case-insensitively against the Allergener row. Recognised names include
`gluten`, `mjölk`, `laktos`, `milk`, `ägg`, `egg`, `soja`, `soy`, `nöt`, `nuts`,
`jordnöt`, `peanut`, `fisk`, `fish`, `skaldjur`, `shellfish`, `sesam`, `sesame`,
`selleri`, `senap`, `mustard`, `sulfit` and `lupin`.

`gluten` expands broadly, covering vete, råg, korn, havre, dinkel, spelt, kamut,
durum, bulgur, couscous, mannagryn and seitan alongside the English equivalents.
Note that oats are included: it will reject oat products whose Allergener row
mentions havre even where the user tolerates certified gluten-free oats. If that
is wrong for the household, pin the specific products rather than loosening the
allergen requirement.

An unrecognised name falls back to matching the name itself as a literal
substring, so a custom entry still works, just without synonym expansion.

## The pantry alias map

The pantry is the household's personal dictionary from everyday words to
products. It is the most reliable mechanism in the system, because it replaces
inference with an assertion, and it is the right fix whenever a user repeatedly
hits disambiguation on a word they use often.

Four entry kinds, mutually exclusive in practice, and one modifier any
of them can carry:

```yaml
# A straight pin.
lingonsylt:
  product_id: 9435

# A pin plus the synonyms Swedish speech-to-text actually produces.
sojamjölk:
  product_id: 5454
  also: [sojadryck, alpromjölk]

# default_quantity is how many to add when the request names no number.
tvättmedel:
  product_id: 8817
  also: [kulörtvätt]
  default_quantity: 2

# Never auto-resolves; asks which one.
mjölk:
  ambiguous: [5454, 2190, 65962]
  prompt: "Vilken mjölk?"

# A query rewrite with a required hard filter.
bröd:
  search: "glutenfritt bröd"
  require_filters: [allergens_free:gluten_free]
```

Lookup is normalised: casefolded with whitespace collapsed, and synonyms in
`also` resolve to the same canonical entry. `search` entries append their
`require_filters` to the profile's own before searching.

`set_alias` only creates pins. Ambiguous and search entries have to go through
`import_pantry`, and `export_pantry` first so a mistake is recoverable.

The `ambiguous` kind is the useful and under-appreciated one. For any word that
legitimately means several things in a household, an ambiguous entry with a
natural-language `prompt` turns a guessing problem into a one-question
conversation, which is both safer and faster than repeated corrections.

## Integration options

Read the live values with
`ha_get_integration(entry_id=..., include_options=True)` rather than assuming.

| Option | Notes |
| --- | --- |
| `delivery_address_id` | Read from the account. Falls back to the account address when unset. |
| `unattended_delivery` | Books slots as doorstep delivery. No effect until a slot is booked. |
| `poll_minutes` | Base refresh for cart and orders, default 30. |
| `delivery_day_poll_minutes` | Faster refresh used only inside a delivery window or during live tracking, default 2. |
| `ambiguity_behaviour` | `ask` or `reject`. |
| `filter_tokens` | Diet filters discovered at runtime and shown as checkboxes. |
| `profiles_json` | The profiles object as a JSON string. Empty means none. |

Filter tokens are discovered from Mathem's own `filters[]` tree rather than
hardcoded, because the vocabulary only reflects tokens applicable to the current
result set and changes over time. If a token in a profile stops matching
anything, it may simply have been renamed upstream.

# Mathem for Home Assistant

A custom [Home Assistant](https://www.home-assistant.io/) integration for
[Mathem](https://www.mathem.se/), the Swedish online grocery service. It exposes
product search, a diet-aware cart, delivery slot selection and order status as
Home Assistant services and entities, with Swedish voice control in mind.

> [!IMPORTANT]
> **Disclaimer.** This project was written by an AI coding assistant. It is an
> unofficial, community project. It is **not** official, **not** endorsed by and
> **not** affiliated with Mathem in any way. It was built for **educational and
> personal use**. It talks to Mathem's private web API, which can change or
> break at any time. Read Mathem's
> [terms of service](https://www.mathem.se/) and make sure you are comfortable
> with them before using this yourself. You use it at your own risk.

---

## Table of contents

- [What it does](#what-it-does)
- [What it deliberately does not do](#what-it-deliberately-does-not-do)
- [The safety model](#the-safety-model)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Dietary profiles](#dietary-profiles)
- [The pantry (alias map)](#the-pantry-alias-map)
- [Services](#services)
- [Entities](#entities)
- [Voice control](#voice-control)
- [Examples](#examples)
- [Development](#development)
- [Architecture](#architecture)
- [Credits](#credits)
- [License](#license)

---

## What it does

- **Product search** against the live catalogue, with the full promotion block
  passed through so multibuys stay visible to whatever consumes the result.
- **Diet-aware cart** management. Items are resolved through a per-household
  dietary profile before they are added, so a generic request like "add milk"
  never silently adds something the profile forbids.
- **Cart read and mutate**: add, set an absolute quantity, remove, and read the
  full cart with a fee breakdown, unit count and line count.
- **Delivery slots**: list slots with local times and prices, and select the
  cheapest slot that matches a preference such as "Saturday morning".
- **Order status** as a timestamp sensor and a calendar entity.
- **Cart audit** against one or all profiles, as an advisory label-reading
  prompt.

## What it deliberately does not do

This integration is built to help you fill a basket, never to spend money on
your behalf.

- It **never places an order**. No code path can reach the checkout confirm
  endpoint; the HTTP layer refuses that URL structurally, not behind a flag.
- No recipes and no shopping lists.
- The cart is always left for human review before checkout. The cart audit is a
  prompt to read the label, never a medical clearance.

## The safety model

When you ask for an item by name, the resolver works through four tiers in order
and stops at the first that establishes safety:

1. **Alias pin.** A keyword you have pinned to a specific product id resolves
   with zero inference. This is the primary mechanism: a household buys roughly
   the same items, and a pinned entry bypasses the veto tiers because you
   have asserted the product.
2. **Category veto** on leaf category ids from the product detail endpoint. This
   is more reliable than marketing badges for excluding eg. animal products.
3. **Ingredient and allergen veto** on the Ingredienser and Allergener rows of
   the product. When a required allergen row is missing, the resolver fails
   closed: a missing row is treated as unknown, never as safe.
4. **Badge filter**, opt in per profile, used only as a ranking and precision
   hint. Diet badges have high precision but poor recall, so they are never the
   safety gate.

If none of these establishes safety, the resolver returns a
`needs_disambiguation` result with candidates and the reason each was rejected.
It never widens a query and never substitutes silently.

Two invariants hold throughout:

- The only lever a free-text request has is the search string. A product id is
  only ever used when you assert it directly (a pin or an explicit id).
- Promotion and pill data never influences ranking, so a discount can never
  become a path around the diet gate.

## Requirements

- Home Assistant 2026.7.4 or newer.
- A Mathem account.

## Installation

### HACS (recommended)

1. In HACS, add this repository as a custom repository of type _Integration_.
2. Search for **Mathem** in HACS and install it.
3. Restart Home Assistant.
4. Go to **Settings -> Devices & Services -> Add Integration** and search for
   **Mathem**.

### Manual

1. Copy `custom_components/mathem` into your Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from **Settings -> Devices & Services**.

## Configuration

Configuration is done entirely in the UI.

### Initial setup

You are asked for your Mathem email and password. The credentials are validated
by logging in once. The session cookie lives only in memory, so the integration
logs in again on each Home Assistant restart.

### Options

Open the integration and choose **Configure** to set:

| Option                        | Description                                                                                    |
| ----------------------------- | ---------------------------------------------------------------------------------------------- |
| **Delivery address**          | Picked from the addresses on your account. Falls back to manual id entry if none can be read.  |
| **Leave at door**             | Whether deliveries are unattended (left at the door).                                          |
| **Poll interval**             | Base polling interval in minutes. The integration tightens this automatically on delivery day. |
| **When a query is ambiguous** | Whether to ask for disambiguation or reject.                                                   |
| **Available diet filters**    | Filter tokens discovered from Mathem at runtime, rendered as checkboxes.                       |
| **Default profile**           | The profile used when a service call does not name one.                                        |
| **Profiles (JSON)**           | The dietary profiles, see below.                                                               |

## Dietary profiles

Profiles are the only place diet rules live. Nothing is hardcoded, and the
integration ships with none, so a household with no restrictions can use it as
is. Profiles are entered as JSON in the options. `inherits` lets one profile
start from another and override specific keys, so shared rules are maintained
once.

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

Field reference:

- `veto_categories`: leaf category ids or names to exclude. Target leaves, for
  example `92 Mellanmjölk`, not a broad parent like `91 Mjölk`, so plant drinks
  filed under the same parent are not blocked.
- `allow_categories`: subtree ids or names that suppress a veto, for example
  `133 Växtbaserat`.
- `veto_ingredients`: substrings matched case-insensitively against the
  Ingredienser row.
- `require_allergen_free`: allergen names checked against the Allergener row, not
  the marketing badge. Both Swedish and English names are understood.
- `prefer_filters`: badge tokens used only as a ranking hint.
- `on_missing_allergen_data`: `reject` (fail closed) or `warn` (allow but flag)
  when a required risk row is absent.

## The pantry (alias map)

The pantry maps everyday words to products. It is stored in Home Assistant's
storage and managed through services rather than a form, because managing
roughly 150 rows through a dialog is not practical.

Entry kinds:

```yaml
# A straight pin.
lingonsylt:
  product_id: 9435

# A pin with the synonyms Swedish speech-to-text actually produces.
sojamjölk:
  product_id: 5454
  also: [sojadryck, alpromjölk]

# Never auto-resolves; asks which one.
mjölk:
  ambiguous: [5454, 2190, 65962]
  prompt: "Vilken mjölk?"

# A query rewrite with a required hard filter.
bröd:
  search: "glutenfritt bröd"
  require_filters: [allergens_free:gluten_free]
```

Bootstrap the pantry from your real order history and manage it with
`mathem.set_alias`, `mathem.remove_alias`, `mathem.export_pantry`,
`mathem.import_pantry` and `mathem.audit_pantry`. `set_alias` fetches the
product to confirm the id resolves, so a wrong id fails loudly instead of
quietly poisoning the map.

## Services

Every service returns a response (available to scripts via `response_variable`).
Every service that resolves items takes an optional `profile` that defaults to
the configured default.

| Service                      | Purpose                                                                                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `mathem.search_products`     | Search the catalogue. Returns products with the promotion block verbatim.                                                            |
| `mathem.get_product`         | Full detail for one product, including ingredients, allergens and categories.                                                        |
| `mathem.add_item`            | Add an item. Give a `query` to resolve safely, or a `product_id` to assert one. Returns `needs_disambiguation` rather than guessing. |
| `mathem.set_quantity`        | Set an absolute quantity (reads the cart and sends the delta).                                                                       |
| `mathem.remove_item`         | Remove a product entirely.                                                                                                           |
| `mathem.get_cart`            | Read the cart with lines, counts and fee breakdown.                                                                                  |
| `mathem.audit_cart`          | Advisory diet audit of every line. With no profile, a per-profile matrix.                                                            |
| `mathem.list_delivery_slots` | List slots with local times and prices.                                                                                              |
| `mathem.set_delivery_slot`   | Select a slot by `slot_id` or by a `predicate`.                                                                                      |
| `mathem.set_alias`           | Pin a keyword to a product id (verifies the id).                                                                                     |
| `mathem.remove_alias`        | Remove a pantry alias.                                                                                                               |
| `mathem.export_pantry`       | Return the whole alias map.                                                                                                          |
| `mathem.import_pantry`       | Import an alias map from a JSON file on an allowed path.                                                                             |
| `mathem.audit_pantry`        | Verify every pinned and ambiguous id still resolves.                                                                                 |

Slot ids are ephemeral (adjacent days reuse unrelated ids), so prefer a
predicate. Times in a predicate are local (Europe/Stockholm):

```yaml
service: mathem.set_delivery_slot
data:
  predicate:
    weekdays: [sat]
    open_from: "06:00"
    open_to: "11:00"
  days: 7
```

## Entities

| Entity                        | Description                                                                                                                                               |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sensor.mathem_next_delivery` | `timestamp` device class; state is the start of the next delivery window, with order number, window end, status, edit deadline and address in attributes. |
| `sensor.mathem_cart_total`    | Cart goods total, with the fee breakdown, line count and unit count in attributes.                                                                        |
| `sensor.mathem_selected_slot` | The most recently selected slot, including `hold_expires_at` for the 60 minute cart hold (display only).                                                  |
| `calendar.mathem`             | Upcoming deliveries, served entirely from coordinator data.                                                                                               |

## Voice control

The integration is designed to work with Home Assistant Assist. A few notes:

- Local sentence triggers only fire on the built-in conversation agent. With a
  language-model agent selected, enable **Prefer handling commands locally** so
  local intents run first.
- On a continued or follow-up turn, local matching is skipped, so first-utterance
  commands are the reliable ones.
- Test intents with `conversation.process` in **Developer Tools** before wiring
  up voice hardware.

## Examples

Add an item from a script and read the response:

```yaml
sequence:
  - service: mathem.add_item
    data:
      query: sojamjölk
      quantity: 2
    response_variable: result
  - choose:
      - conditions: "{{ result.status == 'added' }}"
        sequence:
          - service: notify.notify
            data:
              message: "La till {{ result.resolved_name }}."
      - conditions: "{{ result.status == 'needs_disambiguation' }}"
        sequence:
          - service: notify.notify
            data:
              message: "{{ result.prompt }}"
```

Pick the cheapest Saturday morning slot:

```yaml
service: mathem.set_delivery_slot
data:
  predicate:
    weekdays: [lördag]
    open_from: "06:00"
    open_to: "11:00"
response_variable: slot
```

## Development

The API client under `custom_components/mathem/mathem_client` is a clean
subpackage that imports nothing from Home Assistant, so it can be developed and
tested on a workstation without a running Home Assistant instance.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install aiohttp pytest pytest-asyncio
pytest
```

The test suite runs against synthetic fixtures shaped like the real API. The
tests assert the safety-critical behaviour directly: that generic terms never
resolve to a product a profile forbids, that a missing Allergener row is
rejected rather than passed, and that slot predicates stay correct across the
daylight-saving boundary.

### Against the live API

`scripts/try_live.py` exercises the client against the real Mathem API without
Home Assistant. It reads your credentials from the environment (never from the
command line) and only calls read-only endpoints, so it cannot change your cart
or place an order.

```bash
export MATHEM_USER="you@example.com"
export MATHEM_PASS="..."          # or leave unset to be prompted securely
./.venv/bin/python scripts/try_live.py "mjölk"
```

Add `--record tests/fixtures` to dump the raw JSON payloads, which is the
starting point for turning the synthetic fixtures into recorded ones.

## Architecture

- **Vendored client, not a pip requirement.** The client stays a subpackage so
  publishing it later is mechanical.
- **A single injected aiohttp session.** Home Assistant passes its shared
  session; standalone use creates its own.
- **A data update coordinator** on a 30 minute base interval that tightens to a
  couple of minutes on delivery day. Mutating services push fresh state straight
  in rather than refetching, so adding to the cart costs one request.
- **The cart mutation primitive is delta based.** Quantities are deltas, and
  removal is a decrement to zero.

## Credits

This project builds on the reverse-engineering work of others in the community:

- [ThePSAdmin/mathemcli](https://github.com/ThePSAdmin/mathemcli)
- [sleipner42/mathem-mcp-server](https://github.com/sleipner42/mathem-mcp-server)
- [Malm/mathem-ai-agent-skill](https://github.com/Malm/mathem-ai-agent-skill)

## License

Released under the [MIT License](LICENSE). Mathem and its logo are trademarks of
their respective owner and are used here only to describe what this project
talks to.

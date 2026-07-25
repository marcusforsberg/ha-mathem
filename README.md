# Mathem for Home Assistant

A custom [Home Assistant](https://www.home-assistant.io/) integration for
[Mathem](https://www.mathem.se/), the Swedish online grocery service. It exposes
product search, a diet-aware cart, delivery slot selection and order status as
Home Assistant services and entities, with Swedish [voice control](#voice-control)
in mind.

> [!IMPORTANT]
> **Disclaimer.** This project was written by an AI coding assistant. It is an
> unofficial, community project. It is **not** official, **not** endorsed by and
> **not** affiliated with Mathem in any way. It was built for **educational and
> personal use**. It talks to Mathem's private web API, which can change or
> break at any time. Read Mathem's
> [terms of service](https://www.mathem.se/) and make sure you are comfortable
> with them before using this yourself. The author makes no commitment to
> keeping it up to date or working as Mathem's API changes. You use it at your
> own risk.

---

## Table of contents

- [What it does](#what-it-does)
- [What it deliberately does not do](#what-it-deliberately-does-not-do)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Dietary profiles](#dietary-profiles)
- [The pantry (alias map)](#the-pantry-alias-map)
- [The safety model](#the-safety-model)
- [Services](#services)
- [Entities](#entities)
- [Voice control](#voice-control)
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

## Requirements

- Home Assistant 2026.7.4 or newer.
- A Mathem account.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=marcusforsberg&repository=ha-mathem&category=integration)

1. Click the button above, or in HACS add `marcusforsberg/ha-mathem` as a custom
   repository of type **Integration**.
2. Search for **Mathem** in HACS and install it.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for
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

| Option                          | Description                                                                                                           |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Delivery address**            | The address deliveries go to. Detected automatically from your account; see [Delivery address](#delivery-address).  |
| **Leave at door**               | Whether slots are booked as unattended (doorstep) delivery; see [Unattended delivery](#unattended-delivery).        |
| **Poll interval**               | How often the cart and orders are refreshed normally (minutes).                                                     |
| **Delivery-window poll interval** | A faster refresh used only during an order's delivery window or live tracking; see [Polling](#polling).           |
| **When a query is ambiguous**   | Whether to ask you which product you meant, or reject the request.                                                  |
| **Available diet filters**      | Diet filters Mathem currently supports, discovered at runtime and shown as checkboxes.                             |
| **Default profile**             | The profile used when a service call does not name one.                                                            |
| **Profiles (JSON)**             | The dietary profiles, see [Dietary profiles](#dietary-profiles).                                                   |

#### Delivery address

The integration reads the delivery addresses from your Mathem account and shows
them as a dropdown, so there is nothing to look up by hand. If your account has a
single address it is selected for you; if you have several, pick the one you want.
Delivery slot booking uses this address, and if it is ever left unset the
integration falls back to your account's address automatically.

#### Unattended delivery

**Leave at door** controls how the integration books a delivery slot. When on, it
asks Mathem for an unattended (doorstep) delivery, the order is left at your door
without you needing to be present. Turn it off if the delivery must be handed over
in person. It has no effect until the integration books a slot for you.

#### Polling

The integration refreshes the cart, orders and the currently held delivery slot
on the **Poll interval** (30 minutes by default). It automatically switches to the shorter
**Delivery-window poll interval** (2 minutes by default) only while an active
order is inside its delivery window or is being live tracked, so tracking stays
current without polling hard the rest of the time.

## Dietary profiles

A **profile** is a named set of dietary rules that the integration applies when
it turns a spoken or typed item into a real product. A profile decides what to
exclude (whole product categories, or specific ingredients), which allergens the
product must be free of, and which product badges to prefer. You can define one
profile per person or a single shared household profile.

Profiles are optional. With none configured, items resolve without any dietary
filtering, so the integration works just as well for a household with no dietary
needs. Profiles are written as JSON in the integration options; `inherits` lets
one profile build on another and override only the keys that differ, so shared
rules stay in one place.

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

The **pantry** is your personal dictionary that maps the everyday words you say
to specific products, so the assistant resolves them the way you mean. It is the
most reliable way to handle the items you buy regularly. An entry can pin a word
to an exact product, list synonyms for it, mark a word as ambiguous so the
assistant asks which one you meant, or rewrite a word into a more specific search
with required filters.

The pantry is stored by Home Assistant and managed through services rather than a
settings form, which keeps it easy to script, back up, and edit in bulk.

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
| `mathem.import_pantry`       | Import an alias map inline (keyword to entry); merges, or replaces with `replace: true`.                                             |
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
| `sensor.mathem_selected_slot` | The delivery slot Mathem currently holds, wherever it was booked (this integration, the app or the website). State is the local window as `YYYY-MM-DD HH:MM-HH:MM`; attributes carry `slot_id`, `window_start`, `window_end`, `price` and `cutoff`. `hold_expires_at` (the 60 minute cart hold) appears only for slots booked through the integration, since Mathem exposes it only in that response. Display only. |
| `calendar.mathem_delivery`    | Upcoming deliveries, served entirely from coordinator data.                                                                                               |
| `button.mathem_resync`        | Refreshes the cart, orders and held slot immediately, for when something changed in the Mathem app and you do not want to wait for the next poll. Categorised as diagnostic, so it appears in the device's Diagnostics card. |

## Voice control

Two blueprints ship with the integration under [`blueprints/`](blueprints), one
for each style of Assist. Import a blueprint with its **Import blueprint** button
below, or copy its file into your Home Assistant `config/blueprints/` directory
(keeping the `automation/mathem/` and `script/mathem/` paths).

The `mathem.*` services are also callable directly from your own scripts and
automations if you prefer to build your own flows (see [Services](#services)).

### Local sentences (no LLM)

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmarcusforsberg%2Fha-mathem%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fmathem%2Fmathem_local_voice.yaml)

**Mathem: local voice control** (automation blueprint) handles a fixed set of
Swedish phrases on the built-in conversation agent. Every phrase is an editable,
translatable blueprint input, so you can adapt or add sentences without touching
YAML. Defaults:

| Command         | Default phrases                                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------------------------------- |
| Add item        | `lägg [till ][{1..99:quantity} ]{item} i varukorgen`, plus `handla`/`köp`/`lägg till [N ]{item} på mathem`. An optional leading number sets how many, e.g. "lägg till 8 tofu i varukorgen". |
| Change quantity | `ändra {item} till {0..99:quantity}`, `sätt {item} till N`, `ändra antalet {item} till N` (each with optional ` på mathem`)                       |
| Check item      | `har jag {item} i varukorgen`, `hur många {item} har jag i varukorgen`, `hur många {item} finns i varukorgen` (each with optional ` på mathem`)   |
| Remove item     | `ta bort {item} från varukorgen`, `ta bort {item} från mathem`                                                      |
| Read cart       | `vad ligger i varukorgen`, `vad har (jag\|vi) i varukorgen`, `vad finns i varukorgen`, `hur mycket kostar varukorgen`, `visa varukorgen`, `summera varukorgen` (each with optional ` på mathem`) |
| Next delivery   | `när kommer min leverans`, `när är nästa leverans`, `när kommer mathem`                                             |
| Book slot       | `boka billigaste leverans`, `välj billigaste leveranstid`                                                           |

Create an automation from the blueprint and set your dietary profile (optional)
and the next-delivery sensor. It runs on the built-in **Home Assistant** agent;
if your default assistant is an LLM, enable **Prefer handling commands locally**
so these match first. Say the whole command in one utterance, local matching is
skipped on follow-up turns.

### Full LLM control

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmarcusforsberg%2Fha-mathem%2Fblob%2Fmain%2Fblueprints%2Fscript%2Fmathem%2Fmathem_assist_tool.yaml)

**Mathem: full LLM control** (script blueprint) exposes a single tool to a
language-model conversation agent, letting it search, add, change quantities,
remove, and read the cart from free-form language with no fixed phrases. Create
a script from the blueprint, then expose it via **Settings → Voice assistants →
your assistant → Expose**, and make sure that assistant is an LLM agent with
Home Assistant control enabled. The script's description and field descriptions
are what the model uses to decide when and how to call it; it surfaces
out-of-stock adds and disambiguation prompts so the agent can relay them.

### Testing

Before wiring up voice hardware, test from **Developer Tools → Actions** with
`conversation.process`, for example `köp havremjölk på mathem` or
`summera varukorgen`.

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

### Releasing

Releases are automated with
[release-please](https://github.com/googleapis/release-please) and driven by
[Conventional Commits](https://www.conventionalcommits.org/), so commit messages
decide the version bump: `fix:` gives a patch, `feat:` a minor, and a `!` or a
`BREAKING CHANGE:` footer a major.

Pushing to `main` opens or updates a release pull request. Merging that pull
request is what publishes: it tags the version, creates the GitHub release that
HACS reads to offer an update, writes `CHANGELOG.md`, and bumps the version in
both `custom_components/mathem/manifest.json` and `pyproject.toml`.

> [!NOTE]
> The first release is pinned to `1.0.0` by `release-as` in
> `release-please-config.json`. Remove that key once v1.0.0 is published, or
> every later release will keep trying to be 1.0.0.

Every push and pull request is also validated by the HACS action and by
Home Assistant's `hassfest`, which check the publishing requirements and the
integration manifest.

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

This project builds on the work of others in the community:

- [ThePSAdmin/mathemcli](https://github.com/ThePSAdmin/mathemcli) for the API reverse engineering
- [sleipner42/mathem-mcp-server](https://github.com/sleipner42/mathem-mcp-server) for the API reverse engineering
- [Malm/mathem-ai-agent-skill](https://github.com/Malm/mathem-ai-agent-skill) for the API reverse engineering
- [TheFes/ha-blueprints](https://github.com/TheFes/ha-blueprints) for the customizable-sentence voice blueprint pattern

## License

Released under the [MIT License](LICENSE). Mathem and its logo are trademarks of
their respective owner and are used here only to describe what this project
talks to.

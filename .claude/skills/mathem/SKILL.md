---
name: mathem
description: Operate the Mathem grocery integration in Home Assistant through its mathem.* services, with every service name, field schema and response shape documented so no service listing or probing is needed first. Covers searching the catalogue, adding and removing items, correcting quantities, reading the cart and its fee breakdown, auditing the cart against dietary profiles, listing and booking delivery slots, and managing the pantry alias map. Use this whenever the user mentions Mathem, matvaror, groceries, the shopping cart or varukorgen, adding food or household items to an order, delivery slots or leveranstid, or asks what is in the cart, what an order will cost, or when the next delivery arrives, even when they do not name Mathem or Home Assistant explicitly. Also use it when writing or debugging automations, scripts or voice sentences that call mathem.* services.
---

# Mathem via Home Assistant

`marcusforsberg/ha-mathem` is a custom integration exposing the Swedish grocery
service Mathem as 16 Home Assistant services plus five entities. Everything you
need to call them is in this file, so there is no reason to list services first.

**The one hard invariant: this integration never places an order.** There is no
checkout service, and the HTTP layer refuses any URL containing
`checkout/confirm` before the request leaves the process. Filling the cart is
the whole job. The last step is always the user confirming in the Mathem app or
website. Say so plainly when a task finishes rather than implying the groceries
are ordered.

## Calling convention

Every service returns a response, and you will get nothing back unless you ask
for it. Via the Home Assistant MCP tool:

```
ha_call_service(
  domain="mathem", service="add_item",
  data={"query": "tofu", "quantity": 8},
  return_response=True,
)
```

The payload arrives under `service_response`. In YAML, use `response_variable`:

```yaml
- action: mathem.add_item
  data: {query: tofu, quantity: 8}
  response_variable: result
```

## Service reference

Required fields are marked `*`. `profile` is accepted wherever items are
resolved and defaults to the configured default profile.

| Service | Fields |
| --- | --- |
| `mathem.search_products` | `query`\*, `profile`, `limit` (1-60, default 10) |
| `mathem.get_product` | `product_id`\* |
| `mathem.add_item` | `query` **xor** `product_id`, `quantity` (1-99, default 1), `profile` |
| `mathem.set_quantity` | `product_id`\*, `quantity`\* (0-99, absolute) |
| `mathem.remove_item` | `product_id`\* |
| `mathem.get_cart` | none |
| `mathem.audit_cart` | `profile` (omit for a per-profile matrix) |
| `mathem.list_delivery_slots` | `days` (1-14, default 3), `profile` |
| `mathem.set_delivery_slot` | `slot_id` **xor** `predicate`, `days` (1-14, default 5) |
| `mathem.get_orders` | `limit` (1-50, default 10) |
| `mathem.get_order` | `order_number` (omit for the most recent) |
| `mathem.set_alias` | `keyword`\*, `product_id`\* |
| `mathem.remove_alias` | `keyword`\* |
| `mathem.export_pantry` | none |
| `mathem.import_pantry` | `aliases`\* (object), `replace` (default false) |
| `mathem.audit_pantry` | none |

Field-by-field schemas with full example responses are in
`references/services.md`. Read it when you need a field this table does not
name, or when you are writing YAML that consumes a response.

## The fields you will actually read

`add_item` on success:

```json
{"status": "added", "product_id": 2751, "quantity": 8,
 "tier": "alias-pin", "resolved_name": "Eldorado Tofu Naturell",
 "warnings": [], "available": true, "availability_note": null,
 "has_alternatives": false, "cart": { ... }}
```

`add_item` when it will not guess:

```json
{"status": "needs_disambiguation", "prompt": "Vilken mjölk menar du?",
 "candidates": [{"product_id": 5454, "name": "...", "safe": false,
                 "reason": "ambiguous alias; user must choose",
                 "tier": "ambiguous-alias", "warnings": [], "promotion": {}}]}
```

A cart (returned standalone by `get_cart`, and nested under `cart` on every
mutation): `display_price`, `total_gross_amount`, `currency`, `unit_count`,
`line_count`, `summary_lines[]` for the fee breakdown, and `lines[]` where each
line has `item_id`, `product_id`, `name`, `quantity`, `display_price_total`,
`available`, `availability_note` and `has_alternative_products`.

`search_products`: `query`, `total`, `returned`, `previously_bought[]`, and
`products[]` with `product_id`, `full_name`, `brand`, `name`, `name_extra`,
`gross_price`, `currency`, `availability{}` and `previously_bought`.

## How resolution works, and what it means for you

`add_item` with a `query` runs a four-tier resolver that stops at the first tier
establishing safety: alias pin, category veto, ingredient and allergen veto,
then badge filters as a ranking hint only. It never widens a query and never
substitutes silently. If no tier clears, you get `needs_disambiguation` with
every rejected candidate and the reason for each.

The `tier` on a successful add tells you how much checking happened, and this
matters:

- `alias-pin` means the user pinned that keyword to that product id, so the
  diet vetoes were **deliberately bypassed**. Trusted, but unverified.
- `unrestricted` means the profile has no restrictions to apply.
- `ingredient-allergen-clear` means the vetoes actually ran and passed.

So `tier: alias-pin` is not evidence that an item is vegan or gluten free. If a
user asks you to confirm something is safe, read the product with
`get_product` and look at the Ingredienser and Allergener rows, or run
`audit_cart`. The audit is advisory, a prompt to read the label, never a
clearance. See `references/safety-model.md` for the tier semantics, the
`profiles_json` schema and the pantry entry kinds.

**Check whether profiles exist before relying on them.** Profiles live in the
integration options as JSON and the integration ships with none. With none
configured, or with a profile name that does not match a configured one, the
resolver silently falls back to an unrestricted profile. It does not error. That
means a typo in a profile name quietly disables all dietary filtering, and a
household with real restrictions gets no protection at all until profiles are
written. Read the current options with
`ha_get_integration(entry_id=..., include_options=True)` rather than assuming.

## Common tasks

**Add something.** One call with a free-text `query`. Let the resolver do its
job rather than searching first and passing an id; the query path is the one
with the safety tiers attached. Pass `quantity` in the same call.

**Handle `needs_disambiguation`.** Relay the `prompt` and list the candidates by
name. When the user picks one, call `add_item` again with that candidate's
`product_id`. Do not pick for them, and do not retry with a reworded query
hoping for a cleaner match.

**Correct a quantity.** `add_item` is additive, `set_quantity` is absolute. If
the user says "make that six" about something already in the cart, use
`set_quantity` with the `product_id`, not another `add_item`. Get the id from
`get_cart` rather than from memory of an earlier turn.

**Remove something.** `remove_item` with the `product_id`. `set_quantity` with
`quantity: 0` also works, but `remove_item` reads more clearly.

**Answer "is X in the cart".** Read `get_cart` and match against `lines[].name`.
Do not infer from earlier turns in the conversation; the cart is shared state
that a phone or a voice command may have changed.

**Book a delivery slot.** Prefer a `predicate` over a `slot_id`, because ids are
ephemeral and adjacent days reuse unrelated numbers. Times are local
Europe/Stockholm and `open_from`/`open_to` bound the slot's **opening** time,
not the whole window:

```yaml
- action: mathem.set_delivery_slot
  data:
    predicate: {weekdays: [sat], open_from: "06:00", open_to: "11:00"}
    days: 7
  response_variable: slot
```

Success is `status: "selected"` with a `selection` object; otherwise read
`message`. When listing slots, filter on `bookable`, which already accounts for
both `is_full` and `is_unavailable`. Wide windows are frequently far cheaper
than narrow ones, often by an order of magnitude, so if the user wants the
cheapest option, say what the window actually is rather than just the price.

**Read a past order.** `get_orders` lists recent orders with totals only. For
the itemised lines use `get_order`, which returns every product line with
`name`, `quantity` and `gross_amount`, plus `adjustments[]` for the fee, deposit
and credit rows and `lines_total` for the goods subtotal. Omit `order_number` to
get the most recent order. A line whose `fully_credited` is true was refunded, so
exclude it when summing, and `uncredited_quantity` is what the customer actually
paid for when a line was partially refunded.

**Manage the pantry.** The pantry is the alias map that makes everyday words
resolve to the right product, and it is the single most effective way to improve
results for regularly bought items. `set_alias` verifies the id resolves before
storing it, so a wrong id fails loudly. If a user keeps hitting
disambiguation on a word they use often, offer to pin it.

## Things that will otherwise cost you a wrong answer

**Check for an editable active order before telling the user to check out.**
`sensor.mathem_next_delivery` carries an `edit_deadline` attribute. While an
order is open for edits, items in the cart can be appended to that existing
delivery instead of becoming a separate order, which the user does by choosing
"Lägg till i min nuvarande beställning" at checkout. Mentioning the deadline is
often the most useful thing in the whole reply.

**Fee lines are not stable, so re-read rather than reusing an old echo.** The
cart summary includes a small-order fee below a threshold, a packaging fee and a
delivery fee, and which of them apply changes depending on whether the cart will
append to an existing order. A total quoted from an `add_item` response minutes
ago may no longer be right. Re-read `get_cart` or `sensor.mathem_cart_total`.

**Out of stock still adds.** An item can land in the cart with
`available: false`. Say so, relay `availability_note`, and mention that
alternatives exist when `has_alternatives` is true.

**`previously_bought` is a real signal.** Products the household has bought
before float to the top of search results and are flagged. When a user says
"the usual" or a bare product word, this is the best available hint.

**Prices are in SEK and product names are Swedish.** Search in Swedish;
"oat milk" will do far worse than "havremjölk".

## Entities

| Entity | Notes |
| --- | --- |
| `sensor.mathem_next_delivery` | Timestamp of the start of the window in force, switching to Mathem's narrowed estimate once the order is packed. Each attribute prefix names one concept: `window_*` is the window in force and matches the state (`window_text` compact "HH:MM - HH:MM", `window_end`, `is_estimated`); `booked_*` is what was reserved (`booked_text` Swedish text, `booked_start`, `booked_end`); `estimated_start`/`estimated_end` is the prediction; `tracking_step`/`tracking_text` is Mathem's commentary, which becomes a queue position once out for delivery. Also `order_number`, `status`, `edit_deadline`, `address`, `doorstep_delivery`. When answering when a delivery arrives, use the estimate if `is_estimated` is true, say it is an estimate, and mention the booked window too. |
| `sensor.mathem_last_delivery` | Timestamp of when the most recent order arrived. Use it to answer "has it been delivered yet" rather than inferring from the next-delivery sensor going empty. `image_url` carries a doorstep photo when there is one; it is often absent and the signed link expires 14 days after delivery, so never promise it exists. |
| `sensor.mathem_cart_total` | Goods total. Attributes: `total_gross_amount`, `summary_lines`, `line_count`, `unit_count`, `currency`. |
| `sensor.mathem_selected_slot` | The slot Mathem currently holds, wherever it was booked (integration, app or website); read from the slot list on every poll. State is the local window as `YYYY-MM-DD HH:MM-HH:MM`. Attributes: `slot_id`, `window`, `window_start`, `window_end`, `price`, `cutoff`, and `hold_expires_at` for the 60 minute cart hold, which Mathem only returns for slots booked through the integration. Display only. |
| `calendar.mathem_delivery` | Upcoming deliveries. Events always span the full booked window, never the narrowed estimate; the estimate is in the description. |
| `binary_sensor.mathem_delivery_today` | On when the next delivery's booked day is today. Prefer this over comparing dates yourself. |
| `button.mathem_resync` | Press (`button.press`) to refresh the cart, orders and held slot at once. Use it when the cart may have been changed in the Mathem app and you want the entities current before reading them; service calls already return fresh data, so it is not needed after a mutation. |

## Voice control and blueprints

Two blueprints ship with the integration: an automation blueprint for local
Swedish sentences on the built-in agent, and a script blueprint exposing one
tool to an LLM conversation agent. Both are installed on this instance as
`automation.mathem_local_voice_control` and `script.mathem_full_llm_control`.

Read `references/voice-and-blueprints.md` before editing sentences, adding
phrases, changing the exposed tool, or debugging why a spoken command did not
match. It covers the sentence wildcard syntax, the local-versus-LLM agent
routing trap, and the existing recurring slot-booking automation.

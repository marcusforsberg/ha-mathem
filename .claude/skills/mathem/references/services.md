# Service reference

Complete request and response schemas for all 14 `mathem.*` services. Examples
are real payloads, trimmed for length.

Contents:
- [Calling and responses](#calling-and-responses)
- [search_products](#search_products)
- [get_product](#get_product)
- [add_item](#add_item)
- [set_quantity](#set_quantity)
- [remove_item](#remove_item)
- [get_cart](#get_cart)
- [audit_cart](#audit_cart)
- [list_delivery_slots](#list_delivery_slots)
- [set_delivery_slot](#set_delivery_slot)
- [Pantry services](#pantry-services)
- [Failure modes](#failure-modes)

## Calling and responses

Every service returns a response. Request it explicitly or you get nothing:
`return_response=True` on the MCP tool call, `response_variable:` in YAML.

The MCP wrapper nests the payload twice, under `result.service_response` and
again at the top level as `service_response`. Read either.

`profile` is accepted by `search_products`, `add_item` and `audit_cart`. An
empty string or an unrecognised name falls back to an unrestricted profile
without error, so never pass a guessed name. Delivery slot services take no
profile.

## search_products

Search the live catalogue. Read-only. The promotion block is passed through
verbatim so multibuys stay visible, but promotions never influence resolution.

| Field | Type | Notes |
| --- | --- | --- |
| `query` | text, required | Free text, Swedish. |
| `profile` | text | Applies the profile's `require_filters` as hard search filters. |
| `limit` | 1-60, default 10 | Pages under the hood; the API serves 30 per page. |

```json
{"query": "havregryn", "profile": "marcus", "filters": [],
 "total": 75, "returned": 3, "previously_bought": [],
 "products": [
   {"product_id": 7075, "full_name": "AXA Havregryn", "brand": "AXA",
    "name": "Havregryn", "name_extra": "1,5 kg",
    "gross_price": 22.67, "currency": "SEK",
    "availability": {"isAvailable": true, "description": "",
                     "descriptionShort": "", "code": "available"},
    "promotion": null, "promotions": [], "pills": [],
    "discount": null, "bonusInfo": null, "previously_bought": false}]}
```

`profile` and `filters` echo what was actually applied, so a narrowed result
set is visible rather than guessed at. `total` is the catalogue match count,
`returned` is how many came back.
Previously bought products are floated to the front of `products[]` and also
listed in `previously_bought[]`, mirroring Mathem's own "Tidigare handlat"
ordering.

## get_product

Full detail for one product, including the rows the safety tiers read.

| Field | Type |
| --- | --- |
| `product_id` | number, required |

Returns the product plus its category tree and its contents rows. The two rows
that matter for diet questions are **Ingredienser** and **Allergener**, both
free text in Swedish. EU convention capitalises allergens inline (VETEmjöl), so
matching against them is always case-insensitive. A missing Allergener row means
unknown, never safe.

Use this when a user asks you to verify that something is vegan, gluten free or
free of a specific allergen. Do not answer from the product name.

## add_item

The main entry point. Give a `query` to resolve through the safety tiers, or a
`product_id` to assert an exact product. They are mutually exclusive.

| Field | Type | Notes |
| --- | --- | --- |
| `query` | text | Free text. Mutually exclusive with `product_id`. |
| `product_id` | number | Treated as a deliberate assertion, skips resolution. |
| `quantity` | 1-99, optional | Additive delta, not an absolute target. Omit it unless a number was asked for: the pantry entry's `default_quantity` applies when it is absent, and 1 when there is none. |
| `profile` | text | Defaults to the configured default. |

Success:

```json
{"status": "added", "product_id": 2751, "quantity": 8,
 "quantity_from_pantry": false, "tier": "alias-pin",
 "resolved_name": "Eldorado Tofu Naturell", "warnings": [],
 "available": true, "availability_note": null, "has_alternatives": false,
 "cart": { ... full cart, see get_cart ... }}
```

Needs the user to choose:

```json
{"status": "needs_disambiguation",
 "prompt": "Vilken mjölk menar du?",
 "candidates": [
   {"product_id": 5454, "name": "Alpro Sojadryck Osötad", "safe": false,
    "reason": "ambiguous alias; user must choose",
    "tier": "ambiguous-alias", "warnings": [], "promotion": {}}]}
```

`tier` values: `alias-pin`, `ambiguous-alias`, `unrestricted`,
`ingredient-allergen-clear`, `category-veto`, `ingredient-veto`,
`allergen-veto`. The last three appear on rejected candidates with a `reason`
naming the offending category, ingredient or allergen.

`warnings[]` is where a soft failure surfaces, for example
`"Allergener row absent; allergen-free requirement unverified"` when a profile
sets `on_missing_allergen_data: warn`. Relay these; they mean the check did not
actually happen.

No search results yields `needs_disambiguation` with an empty `candidates[]`,
`prompt: "Inga träffar för '<query>'."` and a warning about the query or filter
tokens. That is a signal to reword the query in Swedish, or to check whether a
profile's `require_filters` is too narrow.

## set_quantity

Absolute, unlike `add_item`. Reads the cart and sends the difference.

| Field | Type | Notes |
| --- | --- | --- |
| `product_id` | number, required | From `get_cart` or a search. |
| `quantity` | 0-99, required | Target, not a delta. `0` empties the line. |

Setting the current quantity is a no-op that returns the unchanged cart.

## remove_item

| Field | Type |
| --- | --- |
| `product_id` | number, required |

Removes the line entirely by decrementing by exactly the current quantity.
Removing something not in the cart returns the unchanged cart rather than
erroring.

## get_cart

No fields. The same cart object is nested under `cart` on every mutation, so a
follow-up read after an add is usually unnecessary.

```json
{"id": 0, "display_price": "113.20", "total_gross_amount": "238.20",
 "currency": "SEK", "unit_count": 8, "line_count": 1,
 "summary_lines": [
   {"id": "SummaryGroupSectionEnum.SUBTOTAL",
    "lines": [{"description": "8 varor", "grossAmount": "113.20",
               "name": "GrossAmount", "displayStyle": "secondary"},
              {"description": "Delsumma", "grossAmount": "113.20",
               "name": "GrossSubtotalAmount", "displayStyle": "primary"},
              {"description": "Avgift för liten varukorg",
               "longDescription": "Vi lägger till en liten avgift på ...",
               "grossAmount": "99.00", "name": "SmallOrderFeeManipulator"}]},
   {"id": "SummaryGroupSectionEnum.EXTRA_MANIPULATORS",
    "lines": [{"description": "Lådor", "grossAmount": "7.00",
               "name": "BagFeeManipulator"},
              {"description": "Leverans", "grossAmount": "19.00",
               "name": "DeliveryFeeManipulator"}]},
   {"id": "SummaryGroupSectionEnum.TOTAL",
    "lines": [{"description": "Totalt inkl. moms", "grossAmount": "238.20",
               "name": "GrossTotalAmount", "displayStyle": "primary"}]}],
 "lines": [
   {"item_id": 123577680, "product_id": 2751,
    "name": "Eldorado Tofu Naturell", "quantity": 8,
    "discounted_quantity": 0, "display_price_total": "113.20",
    "availability": {"isAvailable": true, "code": "available"},
    "available": true, "availability_note": null,
    "has_alternative_products": false,
    "promotion": null, "promotions": [], "pills": [],
    "discount": null, "bonusInfo": null}]}
```

`display_price` is goods only; `total_gross_amount` includes fees. `unit_count`
sums quantities, `line_count` counts distinct products.

The fee lines to know by `name`:

- `SmallOrderFeeManipulator`, charged below a threshold. Its `longDescription`
  names the next spend level that reduces it, which is genuinely useful to
  surface when a cart is small.
- `BagFeeManipulator`, estimated packaging, trued up at delivery.
- `DeliveryFeeManipulator`, the booked slot's price.

Which fees appear varies with whether the cart will append to an open order, so
do not cache a total across turns.

`pills[]` is display metadata rendered by Mathem's own UI. It can carry labels
that look like quantities but describe something else, so read `quantity` for
the count and ignore pills.

## audit_cart

Advisory diet audit of every cart line. Never a clearance.

| Field | Type | Notes |
| --- | --- | --- |
| `profile` | text | Omit for a per-profile matrix across all profiles. |

```json
{"disclaimer": "Advisory only. Read the label before consuming.",
 "profiles": [], "lines": [{"product_id": 2751, "name": "Eldorado Tofu Naturell",
                            "quantity": 8, "verdicts": {}}]}
```

`profiles: []` with empty `verdicts` means no profiles are configured, so nothing
was checked. Report that as "no dietary rules are configured", not as "no
problems found". The distinction matters.

## list_delivery_slots

Read-only.

| Field | Type | Notes |
| --- | --- | --- |
| `days` | 1-14, default 3 | Pages 3 days at a time internally. |

```json
{"count": 57,
 "slots": [
   {"slot_id": 1471287, "route_group": "Morning",
    "open_local": "2026-07-28T05:00:00+02:00",
    "close_local": "2026-07-28T09:00:00+02:00",
    "weekday": 1, "price": 9.0, "currency": "SEK",
    "is_selected": false, "is_full": false, "is_unavailable": false,
    "unavailable_description": null, "is_cheapest": true,
    "bookable": true, "tag": null}]}
```

`weekday` is Monday 0 through Sunday 6. `route_group` is `Morning` or `Evening`.
Filter on `bookable`, which already combines `is_full` and `is_unavailable`.
`is_selected` marks the currently held slot.

Pricing is strongly shaped by window width. In a representative sample, wide
windows such as 05:00-09:00 or 17:00-22:00 ran 9 to 29 SEK while two-hour
windows on the same day ran 39 to 99 SEK. When the user asks for cheap, tell
them the window, because the tradeoff is the point.

## set_delivery_slot

| Field | Type | Notes |
| --- | --- | --- |
| `slot_id` | number | Ephemeral. Mutually exclusive with `predicate`. |
| `predicate` | object | Preferred. Picks the cheapest match. |
| `days` | 1-14, default 5 | Search horizon when using a predicate. |

Predicate keys, all ANDed, all local Europe/Stockholm:

| Key | Accepts |
| --- | --- |
| `weekdays` | List of names or 0-6 ints. Swedish and English, long and short: `mon`, `monday`, `mån`, `måndag`. A bare string or int is accepted too. |
| `open_from` | `"HH:MM"`. Slot's opening time must be at or after this. |
| `open_to` | `"HH:MM"`. Slot's opening time must be at or before this. |
| `route_group` | Numeric route group. |
| `only_bookable` | Default true. |

`open_from` and `open_to` bound the **opening** time only. `open_to: "11:00"`
matches a slot that opens at 11:00 and closes at 16:00. An empty predicate
matches every bookable slot, and the cheapest wins.

Success returns `status: "selected"` with a `selection` object carrying `id`,
`name`, `name_short`, `cutoff_dt` and `expire_at`. Otherwise read `message`.
Selection is idempotent, so re-selecting is safe.

## Pantry services

The pantry is the alias map. Entry kinds and their semantics are in
`safety-model.md`.

| Service | Fields | Notes |
| --- | --- | --- |
| `set_alias` | `keyword`\*, `product_id`\*, `default_quantity` (1-99) | Fetches the product to verify the id, so a wrong id fails loudly instead of poisoning the map. Only creates pins, not ambiguous or search entries. Keeps the keyword's existing synonyms, and its existing `default_quantity` when you omit one. |
| `remove_alias` | `keyword`\* | Removes the canonical entry and its synonyms. |
| `export_pantry` | none | Returns `{"aliases": {keyword: entry}}`. Use it to back up before bulk edits. |
| `import_pantry` | `aliases`\* (object), `replace` (default false) | Merges by default. This is the only way to create ambiguous and search entries. |
| `audit_pantry` | none | Verifies every pinned and ambiguous id still resolves to a live product. Worth running after a long gap, since Mathem retires products. |

To create an ambiguous or query-rewrite entry, build the object and import it:

```yaml
- action: mathem.import_pantry
  data:
    aliases:
      mjölk: {ambiguous: [5454, 2190, 65962], prompt: "Vilken mjölk?"}
      bröd: {search: "glutenfritt bröd", require_filters: ["allergens_free:gluten_free"]}
      tvättmedel: {product_id: 8817, also: ["kulörtvätt"], default_quantity: 2}
```

Export first, since a botched `replace: true` loses the whole map.

## Failure modes

The client raises a small set of exceptions, which surface as service call
errors:

| Error | Meaning and response |
| --- | --- |
| `MathemAuthError` | 401 or 403. The `sessionid` cookie went stale. The session lives only in memory and the integration logs in again on Home Assistant restart, so a reload of the config entry usually fixes it. If not, the stored password needs re-entering. |
| `MathemRequestError` | Any other non-success HTTP status. Carries `status`, `method`, `path` and a truncated body. Usually transient; Mathem's private API changes without notice. |
| `MathemProtocolError` | Well-formed HTTP with an unexpected shape, raised deliberately rather than papering over a missing field with `None`. Strong signal that Mathem changed their API and the integration needs updating. |
| `CheckoutForbiddenError` | A tripwire. It should be impossible to see this. If it appears, some code path tried to reach a checkout URL, which is a bug worth reporting immediately. |

An `add_item` with `quantity` of 0 or less raises a `ValueError` from the client
rather than being clamped. Use `remove_item` or `set_quantity` for that.

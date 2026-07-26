# Voice control, blueprints and existing automations

Read this when editing voice sentences, changing what the LLM agent can do,
debugging a spoken command that did not match, or building a new automation on
top of the `mathem.*` services.

Contents:
- [Two blueprints, two agents](#two-blueprints-two-agents)
- [Local voice blueprint](#local-voice-blueprint)
- [Sentence syntax](#sentence-syntax)
- [Why a spoken command did not match](#why-a-spoken-command-did-not-match)
- [LLM tool blueprint](#llm-tool-blueprint)
- [Patterns worth reusing](#patterns-worth-reusing)
- [Testing](#testing)

## Two blueprints, two agents

| Blueprint | Domain | Agent | Path |
| --- | --- | --- | --- |
| Mathem: local voice control | automation | Built-in conversation agent, no LLM | `mathem/mathem_local_voice.yaml` |
| Mathem: full LLM control | script | LLM conversation agent | `mathem/mathem_assist_tool.yaml` |

Both are installed here as `automation.mathem_local_voice_control` and
`script.mathem_full_llm_control`. Both require Home Assistant 2024.8.0 or newer
and run `mode: queued` with `max: 10`, so two overlapping requests cannot race
the cart. Keep that when editing; the cart is shared mutable state and parallel
mode would produce lost updates.

## Local voice blueprint

Handles a fixed set of Swedish phrases entirely locally. Every phrase is a
blueprint input, so sentences can be adapted or translated without touching
YAML.

Inputs, in two sections:

**General**
- `profile`, the dietary profile for adds. Empty uses the integration default.
- `next_delivery_sensor`, default `sensor.mathem_next_delivery`, used to answer
  "when is my delivery" by reading its `window` attribute.

**Sentences**, one multi-value text input per command:

| Input | Command | Default phrases |
| --- | --- | --- |
| `add_sentences` | Add item | `lägg [till ][{1..99:quantity} ]{item} i varukorgen`, plus `lägg till`/`handla`/`köp [N ]{item} på mathem` |
| `set_quantity_sentences` | Change quantity | `ändra {item} till {0..99:quantity}`, `sätt {item} till N`, `ändra antalet {item} till N`, each with optional ` på mathem` |
| `count_sentences` | Check item | `har jag {item} i varukorgen`, `hur många {item} har jag i varukorgen`, `hur många {item} finns i varukorgen` |
| `remove_sentences` | Remove item | `ta bort {item} från varukorgen`, `ta bort {item} från mathem` |
| `cart_sentences` | Read cart | `vad ligger i varukorgen`, `vad har (jag\|vi) i varukorgen`, `vad finns i varukorgen`, `hur mycket kostar varukorgen`, `visa varukorgen`, `summera varukorgen` |
| `delivery_sentences` | Next delivery | `när kommer min leverans`, `när är nästa leverans`, `när kommer mathem` |
| `slot_sentences` | Book cheapest slot | `boka billigaste leverans`, `välj billigaste leveranstid` |

How each branch behaves internally is worth knowing, because it explains the
failure modes users report:

- **Add** calls `add_item` with the captured `{item}`, passing `{quantity}` only
  when a number was spoken so a pantry entry's `default_quantity` can apply, and
  speaks back the quantity the service reports. It relays `needs_disambiguation`
  by speaking the `prompt`, but the built-in agent cannot carry a follow-up
  answer back, so an ambiguous word is a dead end locally. Pin it in the pantry
  instead.
- **Change quantity**, **check** and **remove** all read the cart first and match
  `{item}` as a **case-insensitive substring of the product's full name**. This
  is the biggest rough edge: the spoken word has to literally appear in Mathem's
  product name, so "sojamjölk" will not match a line named "Alpro Sojadryck
  Osötad". Pantry pins do not help here, because these branches never call the
  resolver. Change quantity and remove take the **last** matching line and
  silently pick one when a word matches several; check sums quantities across all
  matching lines and reports the first matching name.
- **Read cart** reports `unit_count` and `display_price`, goods only, no fees.
- **Next delivery** reads the sensor's `window` attribute, which is Swedish
  display text such as `imorgon, 06:00 - 11:00`, not a timestamp.
- **Book cheapest slot** calls `set_delivery_slot` with a hardcoded predicate of
  `open_from: "06:00"`, `open_to: "12:00"`, `days: 7`. It books the cheapest
  morning slot within a week, and because `open_to` bounds the opening time, a
  wide cheap window opening at 11:00 is eligible.

## Sentence syntax

Home Assistant's local sentence matcher:

| Construct | Meaning |
| --- | --- |
| `[optional words]` | Matches with or without the bracketed part. |
| `(one\|other)` | Mandatory choice between alternatives. |
| `{item}` | Wildcard capturing free text into `trigger.slots.item`. |
| `{1..99:quantity}` | Numeric range captured into `trigger.slots.quantity`. |

Keep `{item}` where it appears when translating. Note the deliberate difference
in ranges: adds use `{1..99:quantity}` because adding zero is meaningless, while
`set_quantity` uses `{0..99:quantity}` so "ändra tofu till 0" can empty a line.

When adding phrases, add them to the existing input list rather than editing a
default in place, and remember a wildcard cannot be adjacent to another
wildcard.

## Why a spoken command did not match

Almost always one of these three, in order of likelihood:

1. **The default assistant is an LLM agent.** Local sentence triggers only fire
   on the built-in agent. Enable "Prefer handling commands locally" in the
   assistant's settings so local sentences match first.
2. **It was a follow-up turn.** Local matching is skipped on follow-ups, so the
   whole command has to be one utterance. "Lägg till tofu" then "åtta" will not
   work; "lägg till 8 tofu i varukorgen" will.
3. **Speech-to-text produced a different word than the pantry knows.** This is
   what the `also` synonym list exists for. Check what the transcription
   actually was before assuming the sentence template is wrong.

## LLM tool blueprint

Exposes one tool to an LLM conversation agent. Create a script from the
blueprint, then expose it via Settings, Voice assistants, the assistant, Expose,
and make sure that assistant is an LLM agent with Home Assistant control enabled.

Its only input is `default_profile`.

The script's top-level `description` is handed to the model verbatim as the tool
description, and the `fields` descriptions become the parameter docs. That text
is the entire interface the model sees, so editing it changes behaviour more than
editing the sequence does. If the agent is calling the tool wrongly, fix the
description first.

Parameters: `action` (one of `search`, `add`, `set_quantity`, `remove`, `cart`),
`query`, `product_id`, `quantity`. `quantity` doubles as the standing default
when `action` is `set_alias`, and is omitted from `add` when the caller left it
out. The `add` branch chooses between
`product_id` and `query` based on whether `product_id` is greater than zero,
which is how a chosen disambiguation candidate gets added. The whole
`response_variable` is returned to the agent via `stop`, so the model sees the
raw service response including `needs_disambiguation` candidates.

Deliberate omissions: no delivery slot actions and no pantry management. If those
are wanted, extend the `choose` block and, critically, extend the tool
description to explain when to use them. Adding a branch without documenting it
means the model will never call it.

## Patterns worth reusing

**Match a cart line by name.** Read the cart, then match case-insensitively.
Prefer collecting all matches and asking when there are several, rather than the
blueprint's last-match-wins, which is a known rough edge:

```yaml
- action: mathem.get_cart
  response_variable: cart
- variables:
    needle: "{{ item | lower }}"
    matches: >-
      {{ cart.lines | selectattr('name', 'search', needle) | list }}
```

**Book by predicate, never by stored id.** Slot ids are ephemeral and adjacent
days reuse unrelated numbers, so an id stored yesterday may book something
unrelated today. Always express intent as a predicate.

**Recurring bookings need a cutoff check.** A slot selection is a hold, not an
order, and `sensor.mathem_selected_slot` exposes `hold_expires_at` for the 60
minute cart hold (only for slots booked through the integration, since Mathem
returns the expiry only in that response). An automation that books far ahead
should not assume the hold survives.

**Prefer native actions over templates in logic positions.** `choose` and `if`
with `state` conditions fail loudly at config load; a template in a logic
position fails silently. Keep templates to `data` fields, messages and
`variables`.

## Testing

Test without voice hardware from Developer Tools, Actions, using
`conversation.process`:

```yaml
action: conversation.process
data:
  text: "köp havremjölk på mathem"
  agent_id: conversation.home_assistant
```

Set `agent_id` explicitly to the built-in agent when testing local sentences,
otherwise the default assistant handles it and a local-sentence bug looks like an
LLM bug. Read-only phrases such as `summera varukorgen` are the safe ones to
start with, since add and remove phrases mutate the real cart.

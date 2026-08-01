<div align="center">

# 🧬 RAPP Twin Hub

**Twins that inherit — without anyone's private life leaving their laptop.**

An archetype says **how** a twin behaves. It never says **who** it is.

`rapp-twin-archetype/1.0` &nbsp;·&nbsp; Python 3.9+ stdlib only &nbsp;·&nbsp; MIT

</div>

---

## The split

A twin has two halves, and they live in different places on purpose.

| | where | what |
|---|---|---|
| **archetype** | this hub, public | voice, working habits, mandate |
| **profile** | your device | name, people, projects, accounts |

An archetype is a starting point anyone can share. A profile is a person, and
it never leaves the machine it was written on.

> The engine is public. The consciousness is local.

Inheritance only flows **hub → device**. There is no publish path for a profile
in this specification, and [a test enforces that](tests/test_twinhub.py):

```
✓ there is no publish path
✓ network use is read-only
```

## Try it

```bash
git clone https://github.com/kody-w/rapp-twin-hub && cd rapp-twin-hub

./twinhub list
./twinhub resolve founder
./twinhub apply founder --home ~/.rapp/twin
```

```
Founder  (base → founder)
Runs a small company and answers for it. Decides fast, and says what is still unknown.

Sound: plain, specific, direct, concrete, unhurried

Ask first:
  - spend money or agree to a price
  - commit to a meeting, a date or a deadline
  - quote a price or discount
  - commit to a delivery date

Never:
  - claim to be a human being
  - share revenue, runway or headcount
```

## Inheritance, and the one rule that makes it safe

`extends` names a parent; the chain merges back down. Voice, practices and
prompts are unioned. Boundaries are **additive only**.

**A child may never weaken its parent.**

Without that, anyone could publish a friendly-looking `helpful-assistant`
archetype that quietly removes *"ask before spending money"* from everything
downstream of it. So a child can add restrictions, and a `mayDo` that
contradicts an ancestor's `mustAsk` or `neverDo` is simply dropped:

```
strict:  neverDo  = ["share an address"]
eager:   mayDo    = ["share an address", "book a table"]   ← extends strict

resolved: mayDo   = ["book a table"]
          neverDo = ["share an address"]
```

Cycles, missing parents and chains deeper than 8 are errors, not warnings.

## Applying is additive

`apply` **adds** to your twin. It never overwrites what you wrote, and it never
touches `identity`, `roles`, `context` or `accounts` — an archetype has no
business supplying any of those.

```
your tone:      ["warm"]
founder tone:   ["plain", "specific", "direct", ...]
after apply:    ["warm", "plain", "specific", "direct", ...]
                  ↑ your own words come first
```

Applying twice is a no-op. Your accounts are untouched. `inherits` records the
lineage so you can always see where a boundary came from.

## The archetypes

| id | |
|---|---|
| [`base`](archetypes/base.json) | the floor: honest about being an AI, unable to commit you to anything |
| [`founder`](archetypes/founder.json) | runs a small company and answers for it |
| [`engineer`](archetypes/engineer.json) | reasons from the code that exists, not the code they wish existed |
| [`operator`](archetypes/operator.json) | schedules, suppliers, quotes and follow-ups |

Everything extends `base`, so no archetype can ship a twin that will claim to
be human. A test checks that for every one of them.

## Both runtimes, one behaviour

**openrappter** (TypeScript)

```bash
openrappter twin inherit founder
```

**RAPP brainstem** (Python) — drop
[`agents/twin_hub_agent.py`](agents/twin_hub_agent.py) into your `agents/`
folder. It follows the grail contract exactly: one class extending
`BasicAgent`, one `metadata` dict, one `perform() -> str`, all I/O through the
storage shim. It imports only `json` and `re`, so the same file runs unmodified
on Tier 1, Tier 2, Tier 3 and in a Pyodide sphere — checked by parsing its AST.

```
TwinHub(action="list")
TwinHub(action="resolve", id="founder")
TwinHub(action="apply",   id="founder")
```

The CLI and the agent are separate implementations, so the suite runs both over
every shipped archetype and requires identical output:

```
✓ same resolution for every shipped archetype
✓ same result when applied
```

## Contributing an archetype

1. Add `archetypes/<id>.json`, conforming to
   [the schema](schema/archetype-1.0.json).
2. `./twinhub check` — validates it, resolves it, and **fails if anything looks
   personal** (emails, phone numbers, street addresses).
3. `./twinhub index -o api/index.json`.
4. Open a PR.

Keep it generic. If a value only makes sense for one particular human being, it
belongs in that person's vault, not here.

## Tests

```bash
python3 tests/run.py     # 52 tests
```

Covering the merge rules, cycle and depth limits, the additive-only mandate,
the unknown-field gate that stops a crafted archetype smuggling a stored field,
grail ABI conformance, tier portability, and cross-implementation agreement.

## Spec

[`schema/SPEC.md`](schema/SPEC.md) — `rapp-twin-archetype/1.0`, so other
implementations can interoperate.

## License

MIT

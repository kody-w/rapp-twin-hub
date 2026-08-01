# rapp-twin-archetype/1.0

How a twin inherits, and why nothing personal can travel with it.

## 1. The split

A twin has two halves, and they live in different places on purpose.

| | where | what |
|---|---|---|
| **archetype** | this hub, public | *how* a twin behaves — voice, practices, mandate |
| **profile** | the owner's device | *who* it is — name, people, projects, accounts |

An archetype is a starting point that anyone can share. A profile is a person,
and it never leaves the machine it was written on.

> The engine is public. The consciousness is local.

Inheritance therefore only ever flows **hub → device**. There is no publish
path for a profile in this specification, and an implementation MUST NOT add
one.

## 2. An archetype

JSON, one file per archetype, conforming to
[`schema/archetype-1.0.json`](../schema/archetype-1.0.json):

```json
{
  "schema": "rapp-twin-archetype/1.0",
  "id": "founder",
  "name": "Founder",
  "summary": "Runs a small company and answers for it.",
  "extends": "base",
  "voice": { "tone": ["direct", "concrete"], "avoid": ["corporate filler"] },
  "boundaries": {
    "mustAsk": ["agree to a price", "commit to a date"],
    "neverDo": ["speak for an investor or a customer"]
  },
  "practices": ["Decide with the information available; say what is still unknown."],
  "prompts": ["What are you actually building right now?"]
}
```

Every field is generic by construction. If a value would only make sense for
one particular human being, it belongs in that person's vault, not here.

## 3. Inheritance

`extends` names a parent. Resolution walks the chain to its root and merges
back down.

**Merge rules**

- `voice.*`, `practices`, `prompts`, `tags` — union, parent order first,
  de-duplicated case-insensitively.
- `boundaries.mustAsk` and `boundaries.neverDo` — union, and **additive only**.
- `boundaries.mayDo` — union, but an entry is dropped if any ancestor lists a
  conflicting `mustAsk` or `neverDo`.
- Scalars (`name`, `summary`) — the child wins.

**A child may not weaken its parent.** That is the one rule that makes
inheritance safe: nobody can publish a `helpful-assistant` archetype that
quietly removes "ask before spending money" from everything downstream.

A cycle is an error, not a truncation. A missing parent is an error. Depth is
capped at 8 so a malicious chain cannot exhaust a resolver.

## 4. Applying an archetype to a profile

Inheritance **adds** to a profile and never overwrites what the owner wrote.

1. Union the archetype's `voice.*` into the profile's, owner entries first.
2. Union `boundaries.*` into the profile's.
3. Record the applied ids in `profile.inherits` for provenance.
4. Leave `identity`, `roles`, `context` and `accounts** untouched — an
   archetype has no business supplying any of them.

Applying the same archetype twice MUST be a no-op.

## 5. What may travel back

Nothing personal. An implementation MAY publish a **shape** — counts and field
names, no values — as defined by `rapp-twin-shape/1.0`:

```json
{
  "schema": "rapp-twin-shape/1.0",
  "present": { "roles": 1, "context": { "people": 2, "facts": 7 }, "accounts": 1 },
  "fingerprint": "78accf8dd1d85f16"
}
```

A shape answers "do two machines hold the same twin?" without either of them
learning what the twin says. The fingerprint MUST be derived from structure
only; deriving it from personal values would make it an oracle.

## 6. The index

The hub publishes `api/index.json` — every archetype with its id, name,
summary, tags and parent — so a client can browse without cloning. It is
generated from `archetypes/`, never edited by hand, and CI fails if it has
drifted.

## 7. Conformance

An implementation conforms if it:

- resolves `extends` with the merge rules in §3, rejecting cycles, missing
  parents and depth over 8;
- refuses to let a child weaken an ancestor's `mustAsk` or `neverDo`;
- applies archetypes additively, never overwriting owner content, and
  idempotently;
- has **no code path** that uploads, posts or commits a profile;
- validates any archetype it loads against the schema before applying it,
  rejecting unknown fields rather than passing them through.

That last clause matters: `additionalProperties: false` is what stops a
crafted archetype from smuggling a field an older client would store and a
newer one would publish.

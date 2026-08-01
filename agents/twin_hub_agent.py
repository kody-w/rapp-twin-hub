"""
TwinHub — inherit twin archetypes from a RAPP brainstem.

Drop this file into any brainstem's `agents/` directory. It follows the grail
agent contract exactly — one file, one class extending `BasicAgent`, one
`metadata` dict, one `perform(**kwargs) -> str` — and does all of its I/O
through the storage shim, so the same file runs unmodified on Tier 1, Tier 2,
Tier 3 and in a Pyodide sphere.

An archetype says HOW a twin behaves. It never says WHO it is. Personal content
lives in the owner's vault and there is no action here that publishes it — the
`actions` enum is the whole surface, and none of them send anything anywhere.

Actions: list, show, resolve, apply, mine

https://github.com/kody-w/rapp-twin-hub
"""

import json
import re

try:  # grail brainstem
    from agents.basic_agent import BasicAgent
except ImportError:  # openrappter's python package
    from openrappter.agents.basic_agent import BasicAgent

from utils.azure_file_storage import AzureFileStorageManager


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/twin-hub",
    "version": "1.0.0",
    "display_name": "Twin Hub",
    "description": "Inherit twin archetypes — how a twin behaves, never who it is.",
    "author": "Kody Wildfeuer",
    "ring": "ga",
    "capabilities": [],
    "tags": ["rapp", "twin", "archetype", "local-first"],
    "category": "identity",
    "quality_tier": "official",
    "requires_env": [],
}

SCHEMA = "rapp-twin-archetype/1.0"
PROFILE_PATH = "twin/profile.json"
ARCHETYPE_DIR = "twin/archetypes"
MAX_DEPTH = 8

ALLOWED_TOP = {
    "schema", "id", "name", "summary", "extends",
    "voice", "boundaries", "practices", "prompts", "tags", "author", "version",
}
ALLOWED_VOICE = {"tone", "avoid", "signatures"}
ALLOWED_BOUNDARIES = {"mayDo", "mustAsk", "neverDo"}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")

# Bundled so a brainstem with no network still has something to inherit from.
BUILTIN = {
    "base": {
        "schema": SCHEMA,
        "id": "base",
        "name": "Base",
        "summary": "The floor every twin stands on: honest about being an AI, and unable to commit you to anything.",
        "voice": {
            "tone": ["plain", "specific"],
            "avoid": ["hedging", "restating the question"],
        },
        "boundaries": {
            "mustAsk": [
                "spend money or agree to a price",
                "commit to a meeting, a date or a deadline",
                "send anything to someone outside the household or company",
                "publish anything publicly",
            ],
            "neverDo": [
                "share personal details, addresses, account handles or phone numbers",
                "speak for anyone other than the owner",
                "claim to be a human being",
                "invent a fact about the owner",
            ],
        },
        "practices": [
            "If you do not know something about the owner, say so and offer to ask them.",
        ],
        "prompts": ["What should this twin never do on your behalf, even if asked nicely?"],
    },
}


def _union(*lists):
    """Order-preserving, case-insensitive de-duplication."""
    out = []
    seen = set()
    for source in lists:
        for item in source or []:
            key = str(item).strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(item)
    return out


def _validate(data, source):
    """Reject rather than half-load; unknown fields are how things get smuggled."""
    if not isinstance(data, dict):
        raise ValueError("%s: not an object" % source)
    if data.get("schema") != SCHEMA:
        raise ValueError("%s: expected schema %s" % (source, SCHEMA))

    unknown = set(data) - ALLOWED_TOP
    if unknown:
        raise ValueError("%s: unknown field(s) %s" % (source, sorted(unknown)))

    identifier = data.get("id")
    if not isinstance(identifier, str) or not ID_PATTERN.match(identifier):
        raise ValueError("%s: invalid id %r" % (source, identifier))

    for key in ("name", "summary"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError("%s: %s is required" % (source, key))

    voice = data.get("voice") or {}
    if not isinstance(voice, dict) or (set(voice) - ALLOWED_VOICE):
        raise ValueError("%s: invalid voice" % source)

    boundaries = data.get("boundaries") or {}
    if not isinstance(boundaries, dict) or (set(boundaries) - ALLOWED_BOUNDARIES):
        raise ValueError("%s: invalid boundaries" % source)
    for required in ("mustAsk", "neverDo"):
        if required not in boundaries:
            raise ValueError("%s: boundaries.%s is required" % (source, required))

    return data


class TwinHubAgent(BasicAgent):
    def __init__(self):
        self.name = "TwinHub"
        self.metadata = {
            "name": self.name,
            "description": (
                "Inherit a twin archetype — a reusable description of HOW a twin behaves: its "
                "voice, its working habits, and the mandate it must stay inside. Archetypes are "
                "public and generic; they never contain anyone's personal details. Applying one "
                "adds to the owner's local twin without overwriting anything they wrote."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "show", "resolve", "apply", "mine"],
                        "description": (
                            "list: available archetypes. show: one, as written. resolve: one with "
                            "its whole lineage merged. apply: add it to the owner's twin. "
                            "mine: what the owner's twin has already inherited."
                        ),
                    },
                    "id": {"type": "string", "description": "Archetype id, e.g. base, founder, engineer."},
                    "dry_run": {"type": "boolean", "description": "Show what apply would change without writing."},
                    "user_guid": {"type": "string", "description": "Optional per-user memory scope."},
                },
                "required": ["action"],
            },
        }
        self.storage_manager = AzureFileStorageManager()
        super().__init__(name=self.name, metadata=self.metadata)

    # ── loading ───────────────────────────────────────────────────────────

    def _load(self, identifier):
        """Vault-installed archetypes win over the built-ins, so an operator can extend the set."""
        try:
            raw = self.storage_manager.read_file("%s/%s.json" % (ARCHETYPE_DIR, identifier))
        except Exception:
            raw = None

        if raw:
            return _validate(json.loads(raw), identifier)
        if identifier in BUILTIN:
            return _validate(BUILTIN[identifier], identifier)
        raise ValueError("no archetype %r" % identifier)

    def _catalog(self):
        entries = dict(BUILTIN)
        try:
            for name in self.storage_manager.list_files(ARCHETYPE_DIR) or []:
                if not name.endswith(".json"):
                    continue
                raw = self.storage_manager.read_file("%s/%s" % (ARCHETYPE_DIR, name))
                if raw:
                    parsed = _validate(json.loads(raw), name)
                    entries[parsed["id"]] = parsed
        except Exception:
            pass
        return entries

    # ── resolution ────────────────────────────────────────────────────────

    def _resolve(self, identifier, chain=()):
        if identifier in chain:
            raise ValueError("archetype cycle: %s" % " -> ".join(list(chain) + [identifier]))
        if len(chain) >= MAX_DEPTH:
            raise ValueError("archetype chain deeper than %d" % MAX_DEPTH)

        node = self._load(identifier)
        parent_id = node.get("extends")

        if not parent_id:
            merged = json.loads(json.dumps(node))
            merged.setdefault("voice", {})
            merged.setdefault("boundaries", {})
            merged["lineage"] = [identifier]
            return merged

        parent = self._resolve(parent_id, tuple(chain) + (identifier,))

        voice_parent = parent.get("voice") or {}
        voice_child = node.get("voice") or {}
        bounds_parent = parent.get("boundaries") or {}
        bounds_child = node.get("boundaries") or {}

        must_ask = _union(bounds_parent.get("mustAsk"), bounds_child.get("mustAsk"))
        never_do = _union(bounds_parent.get("neverDo"), bounds_child.get("neverDo"))

        # A child may add restrictions, never remove them — otherwise anyone
        # could publish an archetype that disarms everything downstream.
        restricted = set(p.strip().lower() for p in (must_ask + never_do))
        may_do = [
            entry
            for entry in _union(bounds_parent.get("mayDo"), bounds_child.get("mayDo"))
            if entry.strip().lower() not in restricted
        ]

        resolved = {
            "schema": SCHEMA,
            "id": node["id"],
            "name": node["name"],
            "summary": node["summary"],
            "extends": parent_id,
            "lineage": parent.get("lineage", []) + [node["id"]],
            "voice": {},
            "boundaries": {},
            "practices": _union(parent.get("practices"), node.get("practices")),
            "prompts": _union(parent.get("prompts"), node.get("prompts")),
            "tags": _union(parent.get("tags"), node.get("tags")),
        }
        for key in ("tone", "avoid", "signatures"):
            merged = _union(voice_parent.get(key), voice_child.get(key))
            if merged:
                resolved["voice"][key] = merged
        for key, value in (("mayDo", may_do), ("mustAsk", must_ask), ("neverDo", never_do)):
            if value:
                resolved["boundaries"][key] = value
        return resolved

    # ── the profile ───────────────────────────────────────────────────────

    def _read_profile(self):
        raw = self.storage_manager.read_file(PROFILE_PATH)
        if not raw:
            return None
        return json.loads(raw)

    def _apply(self, profile, resolved):
        """Additive only. Identity, roles, context and accounts are never touched."""
        updated = json.loads(json.dumps(profile))
        before = json.dumps(updated, sort_keys=True)

        voice = updated.setdefault("voice", {})
        for key in ("tone", "avoid", "signatures"):
            # Owner entries first — their own words outrank an inherited default.
            voice[key] = _union(voice.get(key), (resolved.get("voice") or {}).get(key))

        boundaries = updated.setdefault("boundaries", {})
        for key in ("mayDo", "mustAsk", "neverDo"):
            boundaries[key] = _union(boundaries.get(key), (resolved.get("boundaries") or {}).get(key))

        inherits = updated.setdefault("inherits", [])
        for ancestor in resolved.get("lineage", [resolved["id"]]):
            if ancestor not in inherits:
                inherits.append(ancestor)

        changed = json.dumps(updated, sort_keys=True) != before
        return updated, changed

    # ── dispatch ──────────────────────────────────────────────────────────

    def perform(self, **kwargs):
        action = kwargs.get("action") or "list"
        try:
            self.storage_manager.set_memory_context(kwargs.get("user_guid"))
        except Exception:
            pass

        try:
            return self._dispatch(action, kwargs)
        except Exception as exc:
            return json.dumps({"status": "error", "action": action, "message": str(exc)}, indent=2)

    def _dispatch(self, action, kwargs):
        if action == "list":
            entries = self._catalog()
            return json.dumps(
                {
                    "status": "ok",
                    "count": len(entries),
                    "archetypes": [
                        {
                            "id": a["id"],
                            "name": a["name"],
                            "summary": a["summary"],
                            "extends": a.get("extends"),
                        }
                        for a in sorted(entries.values(), key=lambda x: x["id"])
                    ],
                },
                indent=2,
            )

        if action == "show":
            identifier = kwargs.get("id")
            if not identifier:
                return self._fail(action, "an archetype id is required")
            return json.dumps({"status": "ok", "archetype": self._load(identifier)}, indent=2)

        if action == "resolve":
            identifier = kwargs.get("id")
            if not identifier:
                return self._fail(action, "an archetype id is required")
            return json.dumps({"status": "ok", "resolved": self._resolve(identifier)}, indent=2)

        if action == "mine":
            profile = self._read_profile()
            if profile is None:
                return self._fail(action, "no twin on this device yet")
            # Counts only — this is a summary, not a dump of the owner.
            return json.dumps(
                {
                    "status": "ok",
                    "inherits": profile.get("inherits", []),
                    "voice": {k: len(v or []) for k, v in (profile.get("voice") or {}).items()},
                    "boundaries": {k: len(v or []) for k, v in (profile.get("boundaries") or {}).items()},
                },
                indent=2,
            )

        if action == "apply":
            identifier = kwargs.get("id")
            if not identifier:
                return self._fail(action, "an archetype id is required")

            profile = self._read_profile()
            if profile is None:
                return self._fail(action, "no twin on this device yet — create one before inheriting")

            resolved = self._resolve(identifier)
            updated, changed = self._apply(profile, resolved)

            if not kwargs.get("dry_run"):
                self.storage_manager.write_file(
                    PROFILE_PATH, json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
                )

            return json.dumps(
                {
                    "status": "ok",
                    "applied": resolved["id"],
                    "lineage": resolved["lineage"],
                    "changed": changed,
                    "dry_run": bool(kwargs.get("dry_run")),
                    "inherits": updated.get("inherits", []),
                    "note": "Added to the local twin. Nothing left this device.",
                    "data_slush": {"archetype": resolved["id"], "lineage": resolved["lineage"]},
                },
                indent=2,
            )

        return self._fail(action, "unknown action %r" % action)

    def _fail(self, action, message):
        return json.dumps({"status": "error", "action": action, "message": message}, indent=2)

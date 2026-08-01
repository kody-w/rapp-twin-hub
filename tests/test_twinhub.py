#!/usr/bin/env python3
"""
Tests for twinhub.

The properties that matter most are the ones about what CANNOT happen:

  - a child archetype cannot weaken a parent's mandate
  - applying an archetype cannot overwrite what the owner wrote
  - nothing personal can be published as an archetype
  - there is no code path that sends a profile anywhere

Run:  python3 tests/test_twinhub.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TWINHUB = ROOT / "twinhub"

_loader = importlib.machinery.SourceFileLoader("twinhub", str(TWINHUB))
_spec = importlib.util.spec_from_loader("twinhub", _loader)
hub = importlib.util.module_from_spec(_spec)
_loader.exec_module(hub)

ARCHETYPES = ROOT / "archetypes"


def archetype(identifier: str, **overrides) -> dict:
    base = {
        "schema": hub.SCHEMA,
        "id": identifier,
        "name": identifier.title(),
        "summary": f"{identifier} archetype",
        "boundaries": {"mustAsk": [], "neverDo": []},
    }
    base.update(overrides)
    return base


def loader(*archetypes: dict):
    table = {a["id"]: a for a in archetypes}

    def load(identifier: str) -> dict:
        if identifier not in table:
            raise hub.HubError(f"no archetype {identifier!r}")
        return hub.validate(table[identifier], identifier)

    return load


# ---------------------------------------------------------------------------
# validation is a gate, not a formality
# ---------------------------------------------------------------------------


class TestValidation(unittest.TestCase):
    def test_accepts_a_well_formed_archetype(self) -> None:
        self.assertEqual(hub.validate(archetype("okay"), "test")["id"], "okay")

    def test_rejects_an_unknown_field(self) -> None:
        """
        This is the anti-smuggling rule: without it, a crafted archetype could
        carry a field an older client stores blindly and a newer one publishes.
        """
        with self.assertRaises(hub.HubError) as caught:
            hub.validate(archetype("sneaky", accounts={"email": "someone@example.com"}), "test")
        self.assertIn("unknown field", str(caught.exception))

    def test_rejects_a_wrong_schema(self) -> None:
        bad = archetype("okay")
        bad["schema"] = "something-else/9.9"
        with self.assertRaises(hub.HubError):
            hub.validate(bad, "test")

    def test_rejects_a_bad_id(self) -> None:
        for identifier in ["Uppercase", "has space", "-leading", "x", "a/b", ""]:
            with self.subTest(identifier=identifier), self.assertRaises(hub.HubError):
                hub.validate(archetype("okay") | {"id": identifier}, "test")

    def test_requires_the_mandate(self) -> None:
        missing = archetype("okay")
        missing["boundaries"] = {"mustAsk": []}
        with self.assertRaises(hub.HubError):
            hub.validate(missing, "test")

    def test_rejects_non_string_entries(self) -> None:
        bad = archetype("okay", voice={"tone": ["fine", {"nested": "object"}]})
        with self.assertRaises(hub.HubError):
            hub.validate(bad, "test")


# ---------------------------------------------------------------------------
# inheritance
# ---------------------------------------------------------------------------


class TestResolution(unittest.TestCase):
    def test_merges_a_chain(self) -> None:
        load = loader(
            archetype("root", voice={"tone": ["plain"]}, boundaries={"mustAsk": ["ask A"], "neverDo": ["never A"]}),
            archetype("child", extends="root", voice={"tone": ["dry"]}, boundaries={"mustAsk": ["ask B"], "neverDo": []}),
        )
        resolved = hub.resolve("child", load)

        self.assertEqual(resolved["lineage"], ["root", "child"])
        self.assertEqual(resolved["voice"]["tone"], ["plain", "dry"])
        self.assertEqual(resolved["boundaries"]["mustAsk"], ["ask A", "ask B"])

    def test_a_child_cannot_drop_a_parents_restriction(self) -> None:
        """The rule that makes inheriting a stranger's archetype safe."""
        load = loader(
            archetype("strict", boundaries={"mustAsk": ["ask before spending money"], "neverDo": ["never share an address"]}),
            archetype("lax", extends="strict", boundaries={"mustAsk": [], "neverDo": []}),
        )
        resolved = hub.resolve("lax", load)

        self.assertIn("ask before spending money", resolved["boundaries"]["mustAsk"])
        self.assertIn("never share an address", resolved["boundaries"]["neverDo"])

    def test_a_child_cannot_permit_what_a_parent_restricts(self) -> None:
        load = loader(
            archetype("strict", boundaries={"mustAsk": ["quote a price"], "neverDo": ["share an address"]}),
            archetype(
                "eager",
                extends="strict",
                boundaries={"mayDo": ["quote a price", "share an address", "book a table"], "mustAsk": [], "neverDo": []},
            ),
        )
        resolved = hub.resolve("eager", load)

        self.assertEqual(resolved["boundaries"]["mayDo"], ["book a table"])

    def test_deduplicates_case_insensitively(self) -> None:
        load = loader(
            archetype("root", voice={"tone": ["Direct"]}, boundaries={"mustAsk": ["Ask First"], "neverDo": []}),
            archetype("child", extends="root", voice={"tone": ["direct"]}, boundaries={"mustAsk": ["ask first"], "neverDo": []}),
        )
        resolved = hub.resolve("child", load)

        self.assertEqual(len(resolved["voice"]["tone"]), 1)
        self.assertEqual(len(resolved["boundaries"]["mustAsk"]), 1)

    def test_rejects_a_cycle(self) -> None:
        load = loader(archetype("alpha", extends="beta"), archetype("beta", extends="alpha"))
        with self.assertRaises(hub.HubError) as caught:
            hub.resolve("alpha", load)
        self.assertIn("cycle", str(caught.exception))

    def test_rejects_a_missing_parent(self) -> None:
        with self.assertRaises(hub.HubError):
            hub.resolve("orphan", loader(archetype("orphan", extends="ghost")))

    def test_caps_the_depth(self) -> None:
        """A long chain must fail loudly rather than exhaust the resolver."""
        chain = [archetype(f"link{i:02d}", extends=f"link{i + 1:02d}") for i in range(12)]
        chain.append(archetype("link12"))
        with self.assertRaises(hub.HubError) as caught:
            hub.resolve("link00", loader(*chain))
        self.assertIn("deeper than", str(caught.exception))


# ---------------------------------------------------------------------------
# applying to a real profile
# ---------------------------------------------------------------------------


class TestApply(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = {
            "version": 1,
            "id": "twin_x",
            "identity": {"name": "Alex Doe"},
            "roles": [{"title": "Founder", "org": "Acme"}],
            "voice": {"tone": ["warm"], "avoid": [], "signatures": []},
            "context": {"projects": [], "people": [{"name": "Jane"}], "tools": [], "facts": ["a fact"]},
            "boundaries": {"mayDo": [], "mustAsk": [], "neverDo": []},
            "accounts": {"email": "alex@example.com"},
        }
        self.resolved = hub.resolve(
            "child",
            loader(
                archetype("root", voice={"tone": ["plain"]}, boundaries={"mustAsk": ["ask A"], "neverDo": ["never A"]}),
                archetype("child", extends="root", voice={"tone": ["dry"]}, boundaries={"mustAsk": [], "neverDo": []}),
            ),
        )

    def test_never_touches_who_the_owner_is(self) -> None:
        updated, _ = hub.apply_to_profile(self.profile, self.resolved)

        self.assertEqual(updated["identity"], self.profile["identity"])
        self.assertEqual(updated["roles"], self.profile["roles"])
        self.assertEqual(updated["context"], self.profile["context"])
        self.assertEqual(updated["accounts"], self.profile["accounts"])

    def test_owner_words_come_first(self) -> None:
        updated, _ = hub.apply_to_profile(self.profile, self.resolved)
        self.assertEqual(updated["voice"]["tone"][0], "warm")

    def test_adds_the_mandate(self) -> None:
        updated, _ = hub.apply_to_profile(self.profile, self.resolved)
        self.assertIn("ask A", updated["boundaries"]["mustAsk"])
        self.assertIn("never A", updated["boundaries"]["neverDo"])

    def test_records_provenance(self) -> None:
        updated, summary = hub.apply_to_profile(self.profile, self.resolved)
        self.assertEqual(updated["inherits"], ["root", "child"])
        self.assertEqual(summary["lineage"], ["root", "child"])

    def test_is_idempotent(self) -> None:
        once, first = hub.apply_to_profile(self.profile, self.resolved)
        twice, second = hub.apply_to_profile(once, self.resolved)

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(json.dumps(once, sort_keys=True), json.dumps(twice, sort_keys=True))

    def test_does_not_mutate_the_input(self) -> None:
        before = json.dumps(self.profile, sort_keys=True)
        hub.apply_to_profile(self.profile, self.resolved)
        self.assertEqual(json.dumps(self.profile, sort_keys=True), before)


# ---------------------------------------------------------------------------
# the shipped archetypes
# ---------------------------------------------------------------------------


class TestShippedArchetypes(unittest.TestCase):
    def test_all_valid_and_resolvable(self) -> None:
        entries = hub.available(ARCHETYPES)
        self.assertGreaterEqual(len(entries), 4)
        for entry in entries:
            with self.subTest(archetype=entry["id"]):
                hub.resolve(entry["id"], lambda i: hub.load_local(i, ARCHETYPES))

    def test_filenames_match_ids(self) -> None:
        for path in ARCHETYPES.glob("*.json"):
            data = json.loads(path.read_text())
            self.assertEqual(data["id"], path.stem, f"{path.name} declares id {data['id']!r}")

    def test_nothing_personal_is_published(self) -> None:
        """CI's real job: an archetype is generic, or it is a mistake."""
        blob = "\n".join(p.read_text() for p in ARCHETYPES.glob("*.json"))
        for probe in ["@gmail.", "@example.com", "wildhaven", "kody wildfeuer"]:
            self.assertNotIn(probe, blob.lower(), f"{probe!r} looks personal")

    def test_check_command_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TWINHUB), "--dir", str(ARCHETYPES), "check", "--json"],
            capture_output=True, text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload["problems"])

    def test_every_archetype_inherits_the_base_mandate(self) -> None:
        for entry in hub.available(ARCHETYPES):
            if entry["id"] == "base":
                continue
            with self.subTest(archetype=entry["id"]):
                resolved = hub.resolve(entry["id"], lambda i: hub.load_local(i, ARCHETYPES))
                joined = " ".join(resolved["boundaries"]["neverDo"]).lower()
                self.assertIn("human being", joined, "must never claim to be human")

    def test_index_is_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TWINHUB), "--dir", str(ARCHETYPES), "index",
             "-o", str(ROOT / "api" / "index.json"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# the CLI, and the one-way boundary
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="twinhub-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TWINHUB), "--dir", str(ARCHETYPES), *args],
            capture_output=True, text=True,
        )

    def write_profile(self) -> Path:
        path = self.home / "profile.json"
        path.write_text(json.dumps({
            "version": 1, "id": "twin_cli",
            "identity": {"name": "Alex Doe"},
            "roles": [], "voice": {"tone": ["warm"]},
            "context": {"projects": [], "people": [], "tools": [], "facts": []},
            "boundaries": {"mayDo": [], "mustAsk": [], "neverDo": []},
            "accounts": {"email": "alex@example.com"},
        }))
        return path

    def test_list_and_resolve(self) -> None:
        self.assertEqual(self.run_cli("list").returncode, 0)
        self.assertEqual(self.run_cli("resolve", "founder").returncode, 0)

    def test_apply_writes_the_profile_0600(self) -> None:
        path = self.write_profile()
        result = self.run_cli("apply", "founder", "--home", str(self.home))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        profile = json.loads(path.read_text())
        self.assertEqual(profile["accounts"], {"email": "alex@example.com"})
        self.assertEqual(profile["inherits"], ["base", "founder"])

    def test_dry_run_changes_nothing(self) -> None:
        path = self.write_profile()
        before = path.read_text()
        self.run_cli("apply", "founder", "--home", str(self.home), "--dry-run")
        self.assertEqual(path.read_text(), before)

    def test_apply_without_a_twin_says_so(self) -> None:
        result = self.run_cli("apply", "founder", "--home", str(self.home / "nope"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("no twin", result.stderr)

    def test_there_is_no_publish_path(self) -> None:
        """
        The whole promise. If a command ever appears that uploads a profile,
        this test is the thing that should stop it reaching a release.
        """
        source = TWINHUB.read_text()
        for forbidden in ["urlopen(profile", "POST", "requests.post", "def cmd_publish", "def cmd_upload", "def cmd_push"]:
            self.assertNotIn(forbidden, source, f"{forbidden!r} suggests a profile can leave the device")

        help_text = subprocess.run(
            [sys.executable, str(TWINHUB), "--help"], capture_output=True, text=True
        ).stdout.lower()
        for verb in ["publish", "upload", "push", "share"]:
            self.assertNotIn(f" {verb} ", help_text, f"a {verb!r} command would break the one-way rule")

    def test_network_use_is_read_only(self) -> None:
        """The only outbound call fetches an archetype; it never sends a body."""
        source = TWINHUB.read_text()
        self.assertIn("def load_remote", source)
        self.assertNotIn("data=", source, "a request body would mean something is being sent")


if __name__ == "__main__":
    unittest.main(verbosity=2)

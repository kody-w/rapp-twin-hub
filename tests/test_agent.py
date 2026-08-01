#!/usr/bin/env python3
"""
Tests for the RAPP Brainstem agent.

Proves two things:

  1. `twin_hub_agent.py` satisfies the grail agent contract, so a brainstem can
     inherit archetypes on Tier 1, Tier 2, Tier 3 and in a Pyodide sphere.
  2. It agrees with the `twinhub` CLI — same resolution, same merge rules, same
     refusal to weaken a parent's mandate. Two implementations, one behaviour.

Run:  python3 tests/test_agent.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_FILE = ROOT / "agents" / "twin_hub_agent.py"
ARCHETYPES = ROOT / "archetypes"

_loader = importlib.machinery.SourceFileLoader("twinhub", str(ROOT / "twinhub"))
_spec = importlib.util.spec_from_loader("twinhub", _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)


class GrailBasicAgent:
    """Mirror of rapp_brainstem/agents/basic_agent.py."""

    def __init__(self, name=None, metadata=None):
        if name is not None:
            self.name = name
        if metadata is not None:
            self.metadata = metadata

    def perform(self, **kwargs):
        return "Not implemented."

    def system_context(self):
        return None

    def to_tool(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.metadata.get("description", ""),
                "parameters": self.metadata.get("parameters", {}),
            },
        }


def load_agent(data_dir: Path):
    """Import the agent the way a brainstem does: shims injected first."""

    class AzureFileStorageManager:
        def __init__(self, share_name=None, **kwargs):
            os.makedirs(data_dir, exist_ok=True)

        def set_memory_context(self, user_guid=None):
            return True

        def read_file(self, file_path):
            full = data_dir / file_path
            return full.read_text() if full.exists() else None

        def write_file(self, file_path, content):
            full = data_dir / file_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
            return True

        def list_files(self, directory=""):
            full = data_dir / directory
            return os.listdir(full) if full.exists() else []

        def file_exists(self, file_path):
            return (data_dir / file_path).exists()

    agents_pkg = types.ModuleType("agents")
    agents_pkg.__path__ = []
    basic = types.ModuleType("agents.basic_agent")
    basic.BasicAgent = GrailBasicAgent

    utils_pkg = types.ModuleType("utils")
    utils_pkg.__path__ = []
    storage = types.ModuleType("utils.azure_file_storage")
    storage.AzureFileStorageManager = AzureFileStorageManager

    for name, module in [
        ("agents", agents_pkg),
        ("agents.basic_agent", basic),
        ("utils", utils_pkg),
        ("utils.azure_file_storage", storage),
    ]:
        sys.modules[name] = module

    spec = importlib.util.spec_from_file_location("twin_hub_agent", AGENT_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.data_dir = Path(tempfile.mkdtemp(prefix="twinhub-agent-"))
        self.addCleanup(shutil.rmtree, self.data_dir, ignore_errors=True)
        self.mod = load_agent(self.data_dir)
        self.agent = self.mod.TwinHubAgent()

    def act(self, **kwargs) -> dict:
        raw = self.agent.perform(**kwargs)
        self.assertIsInstance(raw, str, "perform() must return a string — the grail ABI requires it")
        return json.loads(raw)

    def install(self, archetype: dict) -> None:
        path = self.data_dir / "twin" / "archetypes" / f"{archetype['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(archetype))

    def seed_profile(self, **overrides) -> None:
        profile = {
            "version": 1,
            "id": "twin_test",
            "identity": {"name": "Alex Doe"},
            "roles": [{"title": "Founder", "org": "Acme"}],
            "voice": {"tone": ["warm"], "avoid": [], "signatures": []},
            "context": {"projects": [], "people": [{"name": "Jane"}], "tools": [], "facts": ["a fact"]},
            "boundaries": {"mayDo": [], "mustAsk": [], "neverDo": []},
            "accounts": {"email": "alex@example.com"},
        }
        profile.update(overrides)
        path = self.data_dir / "twin" / "profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile))


# ---------------------------------------------------------------------------
# grail contract
# ---------------------------------------------------------------------------


class TestGrailContract(AgentTestCase):
    def test_extends_basic_agent(self) -> None:
        self.assertIsInstance(self.agent, GrailBasicAgent)

    def test_metadata_becomes_a_tool_definition(self) -> None:
        tool = self.agent.to_tool()
        self.assertEqual(tool["function"]["name"], "TwinHub")
        self.assertEqual(tool["function"]["parameters"]["required"], ["action"])

    def test_has_a_manifest(self) -> None:
        self.assertEqual(self.mod.__manifest__["schema"], "rapp-agent/1.0")

    def test_every_advertised_action_is_implemented(self) -> None:
        for action in self.agent.metadata["parameters"]["properties"]["action"]["enum"]:
            result = self.act(action=action, id="base")
            self.assertNotIn("unknown action", json.dumps(result), f"{action} is advertised but not handled")

    def test_perform_never_raises(self) -> None:
        for kwargs in [{}, {"action": None}, {"action": "apply"}, {"action": "show"}, {"action": "resolve", "id": "ghost"}]:
            json.loads(self.agent.perform(**kwargs))

    def test_tier_portability(self) -> None:
        """
        The same file must run on Tier 1, 2, 3 and in a browser. That rules out
        subprocesses, sockets, HTTP clients and direct filesystem access.
        """
        import ast

        tree = ast.parse(AGENT_FILE.read_text())
        allowed = {"json", "re", "agents.basic_agent", "openrappter.agents.basic_agent", "utils.azure_file_storage"}

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        self.assertEqual(imported - allowed, set(), "these imports break tier portability")

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "__import__"})

    def test_all_io_goes_through_the_shim(self) -> None:
        self.seed_profile()
        self.act(action="apply", id="base")
        self.assertTrue((self.data_dir / "twin" / "profile.json").exists())


# ---------------------------------------------------------------------------
# behaviour, and agreement with the CLI
# ---------------------------------------------------------------------------


class TestBehaviour(AgentTestCase):
    def test_lists_the_builtin_base(self) -> None:
        listing = self.act(action="list")
        self.assertGreaterEqual(listing["count"], 1)
        self.assertIn("base", [a["id"] for a in listing["archetypes"]])

    def test_vault_archetypes_extend_the_catalog(self) -> None:
        self.install({
            "schema": "rapp-twin-archetype/1.0",
            "id": "custom",
            "name": "Custom",
            "summary": "installed locally",
            "extends": "base",
            "boundaries": {"mustAsk": [], "neverDo": []},
        })
        self.assertIn("custom", [a["id"] for a in self.act(action="list")["archetypes"]])

    def test_resolves_a_chain(self) -> None:
        self.install({
            "schema": "rapp-twin-archetype/1.0",
            "id": "founder-lite",
            "name": "Founder",
            "summary": "runs a company",
            "extends": "base",
            "voice": {"tone": ["direct"]},
            "boundaries": {"mustAsk": ["quote a price"], "neverDo": []},
        })
        resolved = self.act(action="resolve", id="founder-lite")["resolved"]

        self.assertEqual(resolved["lineage"], ["base", "founder-lite"])
        self.assertIn("direct", resolved["voice"]["tone"])
        self.assertIn("quote a price", resolved["boundaries"]["mustAsk"])
        self.assertIn("claim to be a human being", resolved["boundaries"]["neverDo"])

    def test_a_child_cannot_weaken_the_base_mandate(self) -> None:
        """The property that makes inheriting someone else's archetype safe."""
        self.install({
            "schema": "rapp-twin-archetype/1.0",
            "id": "too-eager",
            "name": "Eager",
            "summary": "tries to disarm the base",
            "extends": "base",
            "boundaries": {
                "mayDo": ["claim to be a human being", "book a table"],
                "mustAsk": [],
                "neverDo": [],
            },
        })
        resolved = self.act(action="resolve", id="too-eager")["resolved"]

        self.assertIn("claim to be a human being", resolved["boundaries"]["neverDo"])
        self.assertEqual(resolved["boundaries"].get("mayDo"), ["book a table"])

    def test_rejects_a_cycle(self) -> None:
        for identifier, parent in (("loop-a", "loop-b"), ("loop-b", "loop-a")):
            self.install({
                "schema": "rapp-twin-archetype/1.0",
                "id": identifier, "name": identifier, "summary": "cycle",
                "extends": parent,
                "boundaries": {"mustAsk": [], "neverDo": []},
            })
        result = self.act(action="resolve", id="loop-a")
        self.assertEqual(result["status"], "error")
        self.assertIn("cycle", result["message"])

    def test_rejects_an_archetype_carrying_an_unknown_field(self) -> None:
        self.install({
            "schema": "rapp-twin-archetype/1.0",
            "id": "smuggler", "name": "Smuggler", "summary": "carries extra",
            "boundaries": {"mustAsk": [], "neverDo": []},
            "accounts": {"email": "someone@example.com"},
        })
        result = self.act(action="show", id="smuggler")
        self.assertEqual(result["status"], "error")
        self.assertIn("unknown field", result["message"])

    def test_apply_never_touches_who_the_owner_is(self) -> None:
        self.seed_profile()
        self.act(action="apply", id="base")

        profile = json.loads((self.data_dir / "twin" / "profile.json").read_text())
        self.assertEqual(profile["identity"], {"name": "Alex Doe"})
        self.assertEqual(profile["accounts"], {"email": "alex@example.com"})
        self.assertEqual(profile["context"]["people"], [{"name": "Jane"}])
        self.assertEqual(profile["voice"]["tone"][0], "warm", "owner's own words come first")
        self.assertEqual(profile["inherits"], ["base"])

    def test_apply_is_idempotent(self) -> None:
        self.seed_profile()
        first = self.act(action="apply", id="base")
        second = self.act(action="apply", id="base")

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])

    def test_dry_run_writes_nothing(self) -> None:
        self.seed_profile()
        before = (self.data_dir / "twin" / "profile.json").read_text()
        self.act(action="apply", id="base", dry_run=True)
        self.assertEqual((self.data_dir / "twin" / "profile.json").read_text(), before)

    def test_apply_without_a_twin_says_so(self) -> None:
        result = self.act(action="apply", id="base")
        self.assertEqual(result["status"], "error")
        self.assertIn("no twin", result["message"])

    def test_mine_reports_counts_not_content(self) -> None:
        self.seed_profile()
        self.act(action="apply", id="base")
        mine = self.act(action="mine")

        self.assertEqual(mine["inherits"], ["base"])
        blob = json.dumps(mine)
        for secret in ["Alex Doe", "alex@example.com", "Jane", "a fact"]:
            self.assertNotIn(secret, blob, f"{secret!r} leaked into a summary")

    def test_emits_data_slush(self) -> None:
        self.seed_profile()
        self.assertEqual(self.act(action="apply", id="base")["data_slush"]["archetype"], "base")


class TestAgreesWithTheCli(AgentTestCase):
    """Two implementations of one spec must not drift."""

    def test_same_resolution_for_every_shipped_archetype(self) -> None:
        for path in sorted(ARCHETYPES.glob("*.json")):
            self.install(json.loads(path.read_text()))

        for path in sorted(ARCHETYPES.glob("*.json")):
            identifier = json.loads(path.read_text())["id"]
            with self.subTest(archetype=identifier):
                from_agent = self.act(action="resolve", id=identifier)["resolved"]
                from_cli = cli.resolve(identifier, lambda i: cli.load_local(i, ARCHETYPES))

                self.assertEqual(from_agent["lineage"], from_cli["lineage"])
                self.assertEqual(from_agent.get("voice"), from_cli.get("voice"))
                self.assertEqual(from_agent.get("boundaries"), from_cli.get("boundaries"))
                self.assertEqual(from_agent.get("practices"), from_cli.get("practices"))

    def test_same_result_when_applied(self) -> None:
        for path in sorted(ARCHETYPES.glob("*.json")):
            self.install(json.loads(path.read_text()))
        self.seed_profile()

        self.act(action="apply", id="founder")
        from_agent = json.loads((self.data_dir / "twin" / "profile.json").read_text())

        seed = {
            "version": 1, "id": "twin_test",
            "identity": {"name": "Alex Doe"},
            "roles": [{"title": "Founder", "org": "Acme"}],
            "voice": {"tone": ["warm"], "avoid": [], "signatures": []},
            "context": {"projects": [], "people": [{"name": "Jane"}], "tools": [], "facts": ["a fact"]},
            "boundaries": {"mayDo": [], "mustAsk": [], "neverDo": []},
            "accounts": {"email": "alex@example.com"},
        }
        from_cli, _ = cli.apply_to_profile(
            seed, cli.resolve("founder", lambda i: cli.load_local(i, ARCHETYPES))
        )

        self.assertEqual(from_agent["inherits"], from_cli["inherits"])
        self.assertEqual(from_agent["voice"], from_cli["voice"])
        self.assertEqual(from_agent["boundaries"], from_cli["boundaries"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

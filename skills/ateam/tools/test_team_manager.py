#!/usr/bin/env python3
"""Tests for team_manager.py."""

import json
import os
import shutil
import tempfile
import unittest

# Import module under test
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "team_manager",
    os.path.join(os.path.dirname(__file__), "team_manager.py"),
)
tm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tm)


class TestCreate(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig = tm.STATE_DIR
        tm.STATE_DIR = self.tmpdir

    def tearDown(self):
        tm.STATE_DIR = self._orig
        shutil.rmtree(self.tmpdir)

    def test_creates_team_json(self):
        result = tm.create("test-team")
        self.assertTrue(result["ok"])
        path = os.path.join(self.tmpdir, "test-team", "team.json")
        self.assertTrue(os.path.isfile(path))
        data = json.load(open(path))
        self.assertEqual(data["name"], "test-team")
        self.assertEqual(data["members"], [])

    def test_creates_with_description(self):
        result = tm.create("test-team", description="My team")
        path = os.path.join(self.tmpdir, "test-team", "team.json")
        data = json.load(open(path))
        self.assertEqual(data["description"], "My team")

    def test_duplicate_team_errors(self):
        tm.create("test-team")
        result = tm.create("test-team")
        self.assertIn("error", result)


class TestDelete(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig = tm.STATE_DIR
        tm.STATE_DIR = self.tmpdir

    def tearDown(self):
        tm.STATE_DIR = self._orig
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deletes_team_directory(self):
        tm.create("test-team")
        result = tm.delete("test-team")
        self.assertTrue(result["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir, "test-team")))

    def test_delete_nonexistent_errors(self):
        result = tm.delete("no-such-team")
        self.assertIn("error", result)


class TestAddMember(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig = tm.STATE_DIR
        tm.STATE_DIR = self.tmpdir
        tm.create("test-team")

    def tearDown(self):
        tm.STATE_DIR = self._orig
        shutil.rmtree(self.tmpdir)

    def test_adds_terminal_member(self):
        result = tm.add_member(
            "test-team", "backend-dev", llm="codex", protocol="terminal",
            surface="surface:42", backend="cmux",
        )
        self.assertTrue(result["ok"])
        data = tm._load("test-team")
        self.assertEqual(len(data["members"]), 1)
        m = data["members"][0]
        self.assertEqual(m["name"], "backend-dev")
        self.assertEqual(m["protocol"], "terminal")
        self.assertEqual(m["surfaceRef"], "surface:42")
        self.assertEqual(m["status"], "idle")
        self.assertEqual(m["messageCount"], 0)

    def test_adds_native_member(self):
        result = tm.add_member(
            "test-team", "infra-dev", llm="claude", protocol="native",
            native_team="test-team-native",
        )
        self.assertTrue(result["ok"])
        data = tm._load("test-team")
        m = data["members"][0]
        self.assertEqual(m["protocol"], "native")
        self.assertEqual(m["nativeTeamName"], "test-team-native")

    def test_duplicate_member_errors(self):
        tm.add_member("test-team", "dev1", llm="codex", protocol="terminal")
        result = tm.add_member("test-team", "dev1", llm="gemini", protocol="terminal")
        self.assertIn("error", result)

    def test_nonexistent_team_errors(self):
        result = tm.add_member("no-team", "dev1", llm="codex", protocol="terminal")
        self.assertIn("error", result)


class TestList(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig = tm.STATE_DIR
        tm.STATE_DIR = self.tmpdir

    def tearDown(self):
        tm.STATE_DIR = self._orig
        shutil.rmtree(self.tmpdir)

    def test_list_all_teams(self):
        tm.create("alpha")
        tm.create("beta")
        result = tm.list_teams()
        self.assertEqual(result["teams"], ["alpha", "beta"])

    def test_list_empty(self):
        result = tm.list_teams()
        self.assertEqual(result["teams"], [])

    def test_list_specific_team(self):
        tm.create("alpha")
        tm.add_member("alpha", "dev1", llm="codex", protocol="terminal")
        result = tm.list_teams(team="alpha")
        self.assertEqual(result["name"], "alpha")
        self.assertEqual(len(result["members"]), 1)

    def test_list_nonexistent_team_errors(self):
        result = tm.list_teams(team="no-team")
        self.assertIn("error", result)


class TestUpdateStatus(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig = tm.STATE_DIR
        tm.STATE_DIR = self.tmpdir
        tm.create("test-team")
        tm.add_member("test-team", "dev1", llm="codex", protocol="terminal")

    def tearDown(self):
        tm.STATE_DIR = self._orig
        shutil.rmtree(self.tmpdir)

    def test_updates_status(self):
        result = tm.update_status("test-team", "dev1", "working")
        self.assertTrue(result["ok"])
        data = tm._load("test-team")
        self.assertEqual(data["members"][0]["status"], "working")

    def test_nonexistent_member_errors(self):
        result = tm.update_status("test-team", "no-dev", "working")
        self.assertIn("error", result)

    def test_nonexistent_team_errors(self):
        result = tm.update_status("no-team", "dev1", "working")
        self.assertIn("error", result)


class TestLogMessage(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig = tm.STATE_DIR
        tm.STATE_DIR = self.tmpdir
        tm.create("test-team")
        tm.add_member("test-team", "dev1", llm="codex", protocol="terminal")

    def tearDown(self):
        tm.STATE_DIR = self._orig
        shutil.rmtree(self.tmpdir)

    def test_appends_to_log_file(self):
        result = tm.log_message("test-team", sender="orchestrator", to="dev1",
                                sentinel="TEAM_MSG_1", protocol="terminal")
        self.assertTrue(result["ok"])
        log_path = os.path.join(self.tmpdir, "test-team", "messages.log")
        self.assertTrue(os.path.isfile(log_path))
        with open(log_path) as f:
            entry = json.loads(f.readline())
        self.assertEqual(entry["from"], "orchestrator")
        self.assertEqual(entry["to"], "dev1")
        self.assertEqual(entry["sentinelId"], "TEAM_MSG_1")
        self.assertEqual(entry["protocol"], "terminal")

    def test_increments_message_count(self):
        tm.log_message("test-team", sender="orchestrator", to="dev1",
                        sentinel="TEAM_MSG_1", protocol="terminal")
        data = tm._load("test-team")
        self.assertEqual(data["members"][0]["messageCount"], 1)

    def test_multiple_logs_append(self):
        tm.log_message("test-team", sender="orchestrator", to="dev1",
                        sentinel="TEAM_MSG_1", protocol="terminal")
        tm.log_message("test-team", sender="orchestrator", to="dev1",
                        sentinel="TEAM_MSG_2", protocol="terminal")
        log_path = os.path.join(self.tmpdir, "test-team", "messages.log")
        with open(log_path) as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)
        data = tm._load("test-team")
        self.assertEqual(data["members"][0]["messageCount"], 2)

    def test_null_sentinel_for_native(self):
        tm.add_member("test-team", "claude-dev", llm="claude", protocol="native")
        result = tm.log_message("test-team", sender="orchestrator", to="claude-dev",
                                sentinel=None, protocol="native")
        self.assertTrue(result["ok"])
        log_path = os.path.join(self.tmpdir, "test-team", "messages.log")
        with open(log_path) as f:
            entry = json.loads(f.readline())
        self.assertIsNone(entry["sentinelId"])

    def test_nonexistent_team_errors(self):
        result = tm.log_message("no-team", sender="orchestrator", to="dev1",
                                sentinel="TEAM_MSG_1", protocol="terminal")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()

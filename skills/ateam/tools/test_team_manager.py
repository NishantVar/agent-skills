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


if __name__ == "__main__":
    unittest.main()

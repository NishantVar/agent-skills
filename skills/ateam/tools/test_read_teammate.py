#!/usr/bin/env python3
"""Tests for read_teammate.py."""

import json
import os
import unittest

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "read_teammate",
    os.path.join(os.path.dirname(__file__), "read_teammate.py"),
)
rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt)


class TestStripAnsi(unittest.TestCase):

    def test_strips_color_codes(self):
        text = "\x1b[31mred text\x1b[0m"
        self.assertEqual(rt.strip_ansi(text), "red text")

    def test_strips_cursor_codes(self):
        text = "\x1b[2Jhello\x1b[H"
        self.assertEqual(rt.strip_ansi(text), "hello")

    def test_preserves_plain_text(self):
        text = "no escape codes here"
        self.assertEqual(rt.strip_ansi(text), "no escape codes here")

    def test_strips_multiple_codes(self):
        text = "\x1b[1m\x1b[32mbold green\x1b[0m normal"
        self.assertEqual(rt.strip_ansi(text), "bold green normal")


class TestInferBackend(unittest.TestCase):

    def test_cmux_surface_ref(self):
        self.assertEqual(rt.infer_backend("surface:42"), "cmux")

    def test_tmux_pane_ref(self):
        self.assertEqual(rt.infer_backend("%7"), "tmux")

    def test_unknown_defaults_cmux(self):
        self.assertEqual(rt.infer_backend("something"), "cmux")


class TestParseOutput(unittest.TestCase):

    def test_finds_response(self):
        text = """Some output here
TEAM_RESPONSE_START TEAM_MSG_1
I implemented the users API with GET and POST endpoints.
Changed files: api/users.py, tests/test_users.py
TEAM_RESPONSE_END TEAM_MSG_1
$"""
        result = rt.parse_output(
            text, "TEAM_RESPONSE_START", "TEAM_RESPONSE_END", "TEAM_MSG_1",
        )
        self.assertEqual(result["status"], "response_found")
        self.assertEqual(result["sentinelId"], "TEAM_MSG_1")
        self.assertIn("users API", result["content"])

    def test_finds_blocked(self):
        text = """Working on it...
TEAM_BLOCKED_START TEAM_MSG_2
I need access to the database credentials.
TEAM_BLOCKED_END TEAM_MSG_2
"""
        result = rt.parse_output(
            text, "TEAM_RESPONSE_START", "TEAM_RESPONSE_END", "TEAM_MSG_2",
            blocked_start="TEAM_BLOCKED_START", blocked_end="TEAM_BLOCKED_END",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("database credentials", result["content"])

    def test_finds_idle(self):
        text = """All done.
TEAM_IDLE TEAM_MSG_3
$"""
        result = rt.parse_output(
            text, "TEAM_RESPONSE_START", "TEAM_RESPONSE_END", "TEAM_MSG_3",
            idle_marker="TEAM_IDLE",
        )
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["sentinelId"], "TEAM_MSG_3")

    def test_no_sentinel_fallback(self):
        text = "Just some random output\nwith multiple lines\n"
        result = rt.parse_output(
            text, "TEAM_RESPONSE_START", "TEAM_RESPONSE_END", "TEAM_MSG_1",
        )
        self.assertEqual(result["status"], "no_sentinel")
        self.assertIn("random output", result["lastLines"])

    def test_strips_ansi_before_parsing(self):
        text = "\x1b[32mTEAM_RESPONSE_START\x1b[0m TEAM_MSG_1\nDone.\n\x1b[32mTEAM_RESPONSE_END\x1b[0m TEAM_MSG_1\n"
        result = rt.parse_output(
            text, "TEAM_RESPONSE_START", "TEAM_RESPONSE_END", "TEAM_MSG_1",
        )
        self.assertEqual(result["status"], "response_found")
        self.assertEqual(result["content"], "Done.")

    def test_response_takes_priority_over_blocked(self):
        text = """TEAM_BLOCKED_START TEAM_MSG_1
need help
TEAM_BLOCKED_END TEAM_MSG_1
TEAM_RESPONSE_START TEAM_MSG_1
All fixed now.
TEAM_RESPONSE_END TEAM_MSG_1
"""
        result = rt.parse_output(
            text, "TEAM_RESPONSE_START", "TEAM_RESPONSE_END", "TEAM_MSG_1",
            blocked_start="TEAM_BLOCKED_START", blocked_end="TEAM_BLOCKED_END",
        )
        self.assertEqual(result["status"], "response_found")

    def test_wrong_sentinel_id_not_matched(self):
        text = """TEAM_RESPONSE_START TEAM_MSG_1
Old response
TEAM_RESPONSE_END TEAM_MSG_1
"""
        result = rt.parse_output(
            text, "TEAM_RESPONSE_START", "TEAM_RESPONSE_END", "TEAM_MSG_2",
        )
        self.assertEqual(result["status"], "no_sentinel")

    def test_custom_markers(self):
        text = """JUDGY_REPORT_START
- [HIGH] sql injection -- api.py:42
JUDGY_REPORT_END
"""
        result = rt.parse_output(
            text, "JUDGY_REPORT_START", "JUDGY_REPORT_END", sentinel_id=None,
        )
        self.assertEqual(result["status"], "response_found")
        self.assertIn("sql injection", result["content"])


from unittest.mock import patch


class TestPollRead(unittest.TestCase):

    def _make_kwargs(self):
        return dict(
            surface="surface:1", backend="cmux",
            start_marker="TEAM_RESPONSE_START",
            end_marker="TEAM_RESPONSE_END",
            sentinel_id="TEAM_MSG_1",
            interval=0.01,  # fast for tests
            max_attempts=3,
        )

    @patch.object(rt, "read_screen")
    def test_finds_response_on_first_attempt(self, mock_read):
        mock_read.return_value = "TEAM_RESPONSE_START TEAM_MSG_1\nDone.\nTEAM_RESPONSE_END TEAM_MSG_1\n"
        result = rt.poll_read(**self._make_kwargs())
        self.assertEqual(result["status"], "response_found")
        self.assertEqual(mock_read.call_count, 1)

    @patch.object(rt, "read_screen")
    def test_finds_response_on_later_attempt(self, mock_read):
        mock_read.side_effect = [
            "Still working...\n",
            "Still working...\n",
            "TEAM_RESPONSE_START TEAM_MSG_1\nDone.\nTEAM_RESPONSE_END TEAM_MSG_1\n",
        ]
        result = rt.poll_read(**self._make_kwargs())
        self.assertEqual(result["status"], "response_found")
        self.assertEqual(mock_read.call_count, 3)

    @patch.object(rt, "read_screen")
    def test_timeout_after_max_attempts(self, mock_read):
        mock_read.return_value = "Still working...\n"
        result = rt.poll_read(**self._make_kwargs())
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["attempts"], 3)

    @patch.object(rt, "read_screen")
    def test_stops_on_blocked(self, mock_read):
        mock_read.return_value = "TEAM_BLOCKED_START TEAM_MSG_1\nNeed creds\nTEAM_BLOCKED_END TEAM_MSG_1\n"
        kwargs = self._make_kwargs()
        kwargs["blocked_start"] = "TEAM_BLOCKED_START"
        kwargs["blocked_end"] = "TEAM_BLOCKED_END"
        result = rt.poll_read(**kwargs)
        self.assertEqual(result["status"], "blocked")

    @patch.object(rt, "read_screen")
    def test_stops_on_error(self, mock_read):
        mock_read.return_value = None
        result = rt.poll_read(**self._make_kwargs())
        self.assertEqual(result["status"], "error")
        self.assertEqual(mock_read.call_count, 1)


if __name__ == "__main__":
    unittest.main()

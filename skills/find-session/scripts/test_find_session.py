#!/usr/bin/env python3
"""Tests for find-session.py using temporary session fixtures."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import StringIO

# Import the module under test
import importlib.util
spec = importlib.util.spec_from_file_location(
    "find_session",
    os.path.expanduser("~/.claude/scripts/find-session.py"),
)
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)


class SessionFixture:
    """Helper to create temporary session JSONL files for testing."""

    def __init__(self, tmpdir):
        self.tmpdir = tmpdir
        self.projects_dir = os.path.join(tmpdir, "projects")
        os.makedirs(self.projects_dir, exist_ok=True)

    def create_session(self, session_id, cwd, timestamp, first_message,
                       custom_title=None, extra_content=None, is_meta=False,
                       content_as_list=False, project="test-project"):
        """Create a session JSONL file with the given data."""
        project_dir = os.path.join(self.projects_dir, project)
        os.makedirs(project_dir, exist_ok=True)
        filepath = os.path.join(project_dir, f"{session_id}.jsonl")

        lines = []

        # First line: progress entry with metadata
        lines.append(json.dumps({
            "type": "progress",
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": timestamp,
            "version": "2.1.78",
        }))

        # User message
        if content_as_list:
            content = [{"type": "text", "text": first_message}]
        else:
            content = first_message

        user_entry = {
            "type": "user",
            "message": {"role": "user", "content": content},
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": timestamp,
        }
        if is_meta:
            user_entry["isMeta"] = True
        lines.append(json.dumps(user_entry))

        # Assistant response
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Sure, I'll help with that."}
            ]},
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": timestamp,
        }))

        # Extra content lines (for grep testing)
        if extra_content:
            for text in extra_content:
                lines.append(json.dumps({
                    "type": "user",
                    "message": {"role": "user", "content": text},
                    "sessionId": session_id,
                    "cwd": cwd,
                    "timestamp": timestamp,
                }))

        # Custom title (appended at end, like /rename does)
        if custom_title:
            lines.append(json.dumps({
                "type": "custom-title",
                "customTitle": custom_title,
            }))

        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")

        return filepath


class TestParseUserMessage(unittest.TestCase):

    def test_plain_string_content(self):
        entry = {"message": {"content": "help me fix this bug"}}
        self.assertEqual(fs.parse_user_message(entry), "help me fix this bug")

    def test_string_truncated_to_80(self):
        entry = {"message": {"content": "x" * 200}}
        self.assertEqual(len(fs.parse_user_message(entry)), 80)

    def test_filters_command_message_string(self):
        entry = {"message": {"content": "<command-message>statusline</command-message>"}}
        self.assertIsNone(fs.parse_user_message(entry))

    def test_filters_teammate_message_string(self):
        entry = {"message": {"content": "<teammate-message>hello</teammate-message>"}}
        self.assertIsNone(fs.parse_user_message(entry))

    def test_list_content_extracts_text(self):
        entry = {"message": {"content": [
            {"type": "text", "text": "deploy the app"}
        ]}}
        self.assertEqual(fs.parse_user_message(entry), "deploy the app")

    def test_list_content_skips_command_finds_next(self):
        entry = {"message": {"content": [
            {"type": "text", "text": "<command-name>/foo</command-name>"},
            {"type": "text", "text": "the real message"},
        ]}}
        self.assertEqual(fs.parse_user_message(entry), "the real message")

    def test_list_content_all_commands_returns_none(self):
        entry = {"message": {"content": [
            {"type": "text", "text": "<command-message>bar</command-message>"},
        ]}}
        self.assertIsNone(fs.parse_user_message(entry))

    def test_empty_content(self):
        entry = {"message": {"content": ""}}
        self.assertEqual(fs.parse_user_message(entry), "")

    def test_no_message_key(self):
        entry = {}
        # No message key -> msg={}, content="" -> returns ""[:80] = ""
        self.assertEqual(fs.parse_user_message(entry), "")


class TestReadHead(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fixture = SessionFixture(self.tmpdir)

    def test_extracts_metadata(self):
        path = self.fixture.create_session(
            "abc-123", "/home/user/proj", "2026-03-15T10:00:00Z",
            "fix the login bug"
        )
        sid, cwd, ts, msg = fs.read_head(path)
        self.assertEqual(sid, "abc-123")
        self.assertEqual(cwd, "/home/user/proj")
        self.assertEqual(ts, "2026-03-15T10:00:00Z")
        self.assertEqual(msg, "fix the login bug")

    def test_skips_meta_messages(self):
        path = self.fixture.create_session(
            "meta-1", "/home/user", "2026-03-15T10:00:00Z",
            "auto message", is_meta=True
        )
        sid, cwd, ts, msg = fs.read_head(path)
        self.assertEqual(sid, "meta-1")
        self.assertIsNone(msg)  # meta message should be skipped

    def test_handles_list_content(self):
        path = self.fixture.create_session(
            "list-1", "/home/user", "2026-03-15T10:00:00Z",
            "refactor the API", content_as_list=True
        )
        sid, cwd, ts, msg = fs.read_head(path)
        self.assertEqual(msg, "refactor the API")

    def test_nonexistent_file(self):
        sid, cwd, ts, msg = fs.read_head("/nonexistent/path.jsonl")
        self.assertIsNone(sid)

    def test_malformed_json(self):
        path = os.path.join(self.tmpdir, "bad.jsonl")
        with open(path, "w") as f:
            f.write("not json\n{bad json too\n")
        sid, cwd, ts, msg = fs.read_head(path)
        self.assertIsNone(sid)


class TestReadTailForTitle(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fixture = SessionFixture(self.tmpdir)

    def test_finds_custom_title(self):
        path = self.fixture.create_session(
            "titled-1", "/home/user", "2026-03-15T10:00:00Z",
            "some work", custom_title="my-cool-project"
        )
        self.assertEqual(fs.read_tail_for_title(path), "my-cool-project")

    def test_no_title_returns_none(self):
        path = self.fixture.create_session(
            "notitled-1", "/home/user", "2026-03-15T10:00:00Z",
            "some work"
        )
        self.assertIsNone(fs.read_tail_for_title(path))

    def test_multiple_renames_returns_last(self):
        """If renamed multiple times, should return the last title."""
        path = self.fixture.create_session(
            "multi-rename", "/home/user", "2026-03-15T10:00:00Z",
            "some work", custom_title="first-name"
        )
        # Append another rename
        with open(path, "a") as f:
            f.write(json.dumps({"type": "custom-title", "customTitle": "second-name"}) + "\n")
        self.assertEqual(fs.read_tail_for_title(path), "second-name")


class TestFormatTimestamp(unittest.TestCase):

    def test_iso_string(self):
        self.assertEqual(fs.format_timestamp("2026-03-15T14:32:00Z"), "2026-03-15 14:32")

    def test_epoch_ms(self):
        # 2026-03-15 14:32:00 UTC in ms
        result = fs.format_timestamp(1773854520000)
        self.assertRegex(result, r"2026-03-1\d \d\d:\d\d")  # timezone-dependent

    def test_none(self):
        self.assertEqual(fs.format_timestamp(None), "unknown")

    def test_garbage(self):
        self.assertEqual(fs.format_timestamp("not-a-date"), "unknown")


class TestCollectSessions(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fixture = SessionFixture(self.tmpdir)

    def test_collects_all_sessions(self):
        self.fixture.create_session("s1", "/proj1", "2026-03-15T10:00:00Z", "task one")
        self.fixture.create_session("s2", "/proj2", "2026-03-16T10:00:00Z", "task two")

        with patch.object(fs, "PROJECTS_DIR", Path(self.fixture.projects_dir)):
            sessions, seen, count = fs.collect_sessions()
        self.assertEqual(len(sessions), 2)
        self.assertEqual(count, 0)

    def test_sorted_newest_first(self):
        self.fixture.create_session("old", "/proj", "2026-03-10T10:00:00Z", "old task")
        self.fixture.create_session("new", "/proj", "2026-03-20T10:00:00Z", "new task")

        with patch.object(fs, "PROJECTS_DIR", Path(self.fixture.projects_dir)):
            sessions, _, _ = fs.collect_sessions()
        self.assertEqual(sessions[0]["session_id"], "new")
        self.assertEqual(sessions[1]["session_id"], "old")

    def test_early_match_on_exact_title(self):
        self.fixture.create_session(
            "match-1", "/proj", "2026-03-15T10:00:00Z",
            "some work", custom_title="switch-cmux"
        )

        with patch.object(fs, "PROJECTS_DIR", Path(self.fixture.projects_dir)):
            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                sessions, seen, count = fs.collect_sessions("switch-cmux")

        self.assertEqual(count, 1)
        self.assertIn("match-1", seen)
        self.assertIn("switch-cmux", mock_out.getvalue())

    def test_skips_subagent_directories(self):
        """Glob pattern */*.jsonl should not match nested subdirs."""
        # Create a normal session
        self.fixture.create_session("normal", "/proj", "2026-03-15T10:00:00Z", "normal task")
        # Create a subagent session in a nested dir
        subdir = os.path.join(self.fixture.projects_dir, "test-project", "subagents")
        os.makedirs(subdir, exist_ok=True)
        with open(os.path.join(subdir, "sub-agent.jsonl"), "w") as f:
            f.write(json.dumps({"type": "progress", "sessionId": "sub-1", "cwd": "/proj", "timestamp": "2026-03-15T10:00:00Z"}) + "\n")

        with patch.object(fs, "PROJECTS_DIR", Path(self.fixture.projects_dir)):
            sessions, _, _ = fs.collect_sessions()
        ids = [s["session_id"] for s in sessions]
        self.assertIn("normal", ids)
        self.assertNotIn("sub-1", ids)


class TestStrategyTokenTitle(unittest.TestCase):

    def _make_sessions(self):
        return [
            {"session_id": "s1", "custom_title": "switch-cmux", "cwd": "/p", "timestamp": "2026-03-15T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s1.jsonl"},
            {"session_id": "s2", "custom_title": "cmux-config-update", "cwd": "/p", "timestamp": "2026-03-14T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s2.jsonl"},
            {"session_id": "s3", "custom_title": "fix-login-bug", "cwd": "/p", "timestamp": "2026-03-13T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s3.jsonl"},
            {"session_id": "s4", "custom_title": None, "cwd": "/p", "timestamp": "2026-03-12T10:00:00Z", "first_message": "some task", "jsonl_path": "/tmp/s4.jsonl"},
        ]

    def test_token_reordering(self):
        """'cmux switch' should match 'switch-cmux' since both tokens are substrings."""
        sessions = self._make_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            found = fs.strategy_token_title(["cmux", "switch"], sessions, seen)
        self.assertEqual(found, 1)
        self.assertIn("s1", seen)
        self.assertIn("switch-cmux", mock_out.getvalue())

    def test_single_token_matches_multiple(self):
        """'cmux' should match both switch-cmux and cmux-config-update."""
        sessions = self._make_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["cmux"], sessions, seen)
        self.assertEqual(found, 2)

    def test_no_match(self):
        sessions = self._make_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["nonexistent"], sessions, seen)
        self.assertEqual(found, 0)

    def test_skips_already_seen(self):
        sessions = self._make_sessions()
        seen = {"s1"}  # already found by strategy 1
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["cmux"], sessions, seen)
        self.assertEqual(found, 1)  # only s2, not s1

    def test_skips_sessions_without_title(self):
        sessions = self._make_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["some"], sessions, seen)
        self.assertEqual(found, 0)  # s4 has no custom_title

    def test_case_insensitive_title(self):
        """Titles are matched case-insensitively (tokens are pre-lowercased by main)."""
        sessions = self._make_sessions()
        # Add a session with uppercase title
        sessions.append({"session_id": "s5", "custom_title": "CMUX-UPPERCASE", "cwd": "/p",
                         "timestamp": "2026-03-11T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s5.jsonl"})
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["cmux"], sessions, seen)
        self.assertEqual(found, 3)  # s1, s2, s5


class TestGrepFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_finds_term_in_file(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        with open(path, "w") as f:
            f.write('{"type":"user","message":"fix the authentication bug"}\n')
        self.assertTrue(fs.grep_file(path, "authentication"))

    def test_case_insensitive(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        with open(path, "w") as f:
            f.write('{"type":"user","message":"Fix the Authentication bug"}\n')
        self.assertTrue(fs.grep_file(path, "authentication"))

    def test_excludes_file_history_snapshot(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        with open(path, "w") as f:
            f.write('{"type":"file-history-snapshot","data":"contains secretword here"}\n')
        self.assertFalse(fs.grep_file(path, "secretword"))

    def test_mixed_snapshot_and_real(self):
        """Term in both snapshot and real line — should still match."""
        path = os.path.join(self.tmpdir, "test.jsonl")
        with open(path, "w") as f:
            f.write('{"type":"file-history-snapshot","data":"keyword here"}\n')
            f.write('{"type":"user","message":"keyword also here"}\n')
        self.assertTrue(fs.grep_file(path, "keyword"))

    def test_no_match(self):
        path = os.path.join(self.tmpdir, "test.jsonl")
        with open(path, "w") as f:
            f.write('{"type":"user","message":"nothing relevant"}\n')
        self.assertFalse(fs.grep_file(path, "zzzznothere"))

    def test_nonexistent_file(self):
        self.assertFalse(fs.grep_file("/nonexistent/file.jsonl", "test"))


class TestStrategyGrepAll(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fixture = SessionFixture(self.tmpdir)

    def test_all_words_must_match(self):
        path = self.fixture.create_session(
            "s1", "/proj", "2026-03-15T10:00:00Z", "initial message",
            extra_content=["deploy the authentication service", "configure nginx proxy"]
        )
        sessions = [{"session_id": "s1", "cwd": "/proj", "timestamp": "2026-03-15T10:00:00Z",
                      "custom_title": None, "first_message": "initial", "jsonl_path": path}]
        seen = set()

        with patch("sys.stdout", new_callable=StringIO):
            # Both words present
            found = fs.strategy_grep_all(["authentication", "nginx"], sessions, seen)
        self.assertEqual(found, 1)

    def test_partial_match_no_result(self):
        path = self.fixture.create_session(
            "s1", "/proj", "2026-03-15T10:00:00Z", "initial message",
            extra_content=["deploy the authentication service"]
        )
        sessions = [{"session_id": "s1", "cwd": "/proj", "timestamp": "2026-03-15T10:00:00Z",
                      "custom_title": None, "first_message": "initial", "jsonl_path": path}]
        seen = set()

        with patch("sys.stdout", new_callable=StringIO):
            # "kubernetes" not in file
            found = fs.strategy_grep_all(["authentication", "kubernetes"], sessions, seen)
        self.assertEqual(found, 0)


class TestStrategyGrepAny(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fixture = SessionFixture(self.tmpdir)

    def test_any_word_matches(self):
        path = self.fixture.create_session(
            "s1", "/proj", "2026-03-15T10:00:00Z", "initial message",
            extra_content=["deploy the authentication service"]
        )
        sessions = [{"session_id": "s1", "cwd": "/proj", "timestamp": "2026-03-15T10:00:00Z",
                      "custom_title": None, "first_message": "initial", "jsonl_path": path}]
        seen = set()

        with patch("sys.stdout", new_callable=StringIO):
            # "kubernetes" not in file but "authentication" is
            found = fs.strategy_grep_any(["authentication", "kubernetes"], sessions, seen)
        self.assertEqual(found, 1)

    def test_no_words_match(self):
        path = self.fixture.create_session(
            "s1", "/proj", "2026-03-15T10:00:00Z", "initial message",
        )
        sessions = [{"session_id": "s1", "cwd": "/proj", "timestamp": "2026-03-15T10:00:00Z",
                      "custom_title": None, "first_message": "initial", "jsonl_path": path}]
        seen = set()

        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_grep_any(["kubernetes", "terraform"], sessions, seen)
        self.assertEqual(found, 0)


class TestDeduplication(unittest.TestCase):
    """Test that sessions found in earlier strategies don't repeat in later ones."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fixture = SessionFixture(self.tmpdir)

    def test_strategy2_skips_strategy1_matches(self):
        sessions = [
            {"session_id": "s1", "custom_title": "deploy-app", "cwd": "/p",
             "timestamp": "2026-03-15T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s1.jsonl"},
        ]
        seen = {"s1"}  # pretend strategy 1 already found it
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["deploy"], sessions, seen)
        self.assertEqual(found, 0)

    def test_strategy3_skips_earlier_matches(self):
        path = self.fixture.create_session(
            "s1", "/proj", "2026-03-15T10:00:00Z", "deploy the app",
        )
        sessions = [{"session_id": "s1", "cwd": "/proj", "timestamp": "2026-03-15T10:00:00Z",
                      "custom_title": None, "first_message": "deploy the app", "jsonl_path": path}]
        seen = {"s1"}
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_grep_all(["deploy"], sessions, seen)
        self.assertEqual(found, 0)


class TestStopWords(unittest.TestCase):

    def test_stop_words_filtered(self):
        """Searching 'the bug in my code' should filter to ['bug', 'code']."""
        query = "the bug in my code"
        tokens = [t.lower() for t in query.split() if t.lower() not in fs.STOP_WORDS]
        self.assertEqual(tokens, ["bug", "code"])

    def test_all_stop_words(self):
        query = "the is a an"
        tokens = [t.lower() for t in query.split() if t.lower() not in fs.STOP_WORDS]
        self.assertEqual(tokens, [])


class TestFuzzyUserSearches(unittest.TestCase):
    """Simulate realistic user searches with token reordering, partial matches, etc."""

    def _make_titled_sessions(self):
        return [
            {"session_id": "s1", "custom_title": "switch-cmux", "cwd": "/home/user/cmux", "timestamp": "2026-03-15T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s1.jsonl"},
            {"session_id": "s2", "custom_title": "cmux-terminal-refactor", "cwd": "/home/user/cmux", "timestamp": "2026-03-14T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s2.jsonl"},
            {"session_id": "s3", "custom_title": "fix-auth-middleware", "cwd": "/home/user/api", "timestamp": "2026-03-13T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s3.jsonl"},
            {"session_id": "s4", "custom_title": "auth-token-rotation", "cwd": "/home/user/api", "timestamp": "2026-03-12T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s4.jsonl"},
            {"session_id": "s5", "custom_title": "deploy-staging-v2", "cwd": "/home/user/infra", "timestamp": "2026-03-11T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s5.jsonl"},
            {"session_id": "s6", "custom_title": "debug-websocket-drops", "cwd": "/home/user/api", "timestamp": "2026-03-10T10:00:00Z", "first_message": None, "jsonl_path": "/tmp/s6.jsonl"},
        ]

    def test_reversed_word_order(self):
        """'cmux switch' should find 'switch-cmux'."""
        sessions = self._make_titled_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["cmux", "switch"], sessions, seen)
        self.assertEqual(found, 1)
        self.assertIn("s1", seen)

    def test_partial_word(self):
        """'auth' matches 'fix-auth-middleware' and 'auth-token-rotation'."""
        sessions = self._make_titled_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["auth"], sessions, seen)
        self.assertEqual(found, 2)  # s3 and s4

    def test_stop_words_ignored_in_search(self):
        """'the auth in my api' should search for ['auth', 'api'] after stop word removal."""
        query = "the auth in my api"
        tokens = [t.lower() for t in query.split() if t.lower() not in fs.STOP_WORDS]
        self.assertEqual(tokens, ["auth", "api"])

    def test_multi_token_narrowing(self):
        """'auth token' should match 'auth-token-rotation' but not 'fix-auth-middleware'."""
        sessions = self._make_titled_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["auth", "token"], sessions, seen)
        self.assertEqual(found, 1)
        self.assertIn("s4", seen)

    def test_substring_within_compound_word(self):
        """'socket' should match 'debug-websocket-drops'."""
        sessions = self._make_titled_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["socket"], sessions, seen)
        self.assertEqual(found, 1)
        self.assertIn("s6", seen)

    def test_staging_deploy(self):
        """'staging deploy' should match 'deploy-staging-v2'."""
        sessions = self._make_titled_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["staging", "deploy"], sessions, seen)
        self.assertEqual(found, 1)
        self.assertIn("s5", seen)

    def test_no_match_for_unrelated(self):
        """'database migration' should match nothing."""
        sessions = self._make_titled_sessions()
        seen = set()
        with patch("sys.stdout", new_callable=StringIO):
            found = fs.strategy_token_title(["database", "migration"], sessions, seen)
        self.assertEqual(found, 0)


class TestPrintSession(unittest.TestCase):

    def test_output_format(self):
        session = {
            "session_id": "abc-def-123",
            "cwd": "/home/user/project",
            "timestamp": "2026-03-15T14:32:00Z",
            "custom_title": "my-cool-project",
            "first_message": None,
        }
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            fs.print_session(session)
        output = mock_out.getvalue()
        self.assertIn('Session: "my-cool-project"', output)
        self.assertIn("Dir:     /home/user/project", output)
        self.assertIn("Date:    2026-03-15", output)
        self.assertIn("Resume:  cd /home/user/project && claude -r abc-def-123", output)

    def test_fallback_to_first_message(self):
        session = {
            "session_id": "abc-123",
            "cwd": "/proj",
            "timestamp": "2026-03-15T14:32:00Z",
            "custom_title": None,
            "first_message": "help me fix the login page",
        }
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            fs.print_session(session)
        self.assertIn('Session: "help me fix the login page"', mock_out.getvalue())

    def test_untitled_fallback(self):
        session = {
            "session_id": "abc-123",
            "cwd": "/proj",
            "timestamp": None,
            "custom_title": None,
            "first_message": None,
        }
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            fs.print_session(session)
        self.assertIn('Session: "(untitled)"', mock_out.getvalue())
        self.assertIn("Date:    unknown", mock_out.getvalue())


if __name__ == "__main__":
    unittest.main()

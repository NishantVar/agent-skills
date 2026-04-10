#!/usr/bin/env python3
"""Find Claude Code sessions by searching titles and content progressively."""

import sys
import os
import json
import glob
import subprocess
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"

STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "of", "in", "to", "for",
    "with", "on", "at", "by", "from", "as", "into", "about", "it", "its",
    "this", "that", "these", "those", "my", "our", "your", "and", "or",
    "but", "not", "no", "so",
})


def parse_user_message(entry):
    """Extract text from a user message entry, handling string and list content."""
    msg = entry.get("message", {})
    content = msg.get("content", "")
    if isinstance(content, str):
        if content.startswith("<command-") or content.startswith("<teammate-message"):
            return None
        return content[:80]
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text.startswith("<command-") or text.startswith("<teammate-message"):
                    continue
                return text[:80]
    return None


def read_head(filepath, max_lines=20):
    """Read first max_lines of a JSONL file. Returns session_id, cwd, timestamp, first_message."""
    session_id = None
    cwd = None
    timestamp = None
    first_message = None

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if session_id is None and "sessionId" in entry and "cwd" in entry:
                    session_id = entry["sessionId"]
                    cwd = entry["cwd"]
                    timestamp = entry.get("timestamp")

                if first_message is None and entry.get("type") == "user":
                    if entry.get("isMeta"):
                        continue
                    msg_text = parse_user_message(entry)
                    if msg_text:
                        first_message = msg_text
    except (OSError, PermissionError):
        pass

    return session_id, cwd, timestamp, first_message


def read_tail_for_title(filepath, tail_bytes=65536):
    """Read last tail_bytes of file, scan for custom-title entries. Returns last customTitle or None."""
    custom_title = None
    try:
        file_size = os.path.getsize(filepath)
        read_start = max(0, file_size - tail_bytes)

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            if read_start > 0:
                f.seek(read_start)
                f.readline()  # discard partial first line

            for line in f:
                line = line.strip()
                if not line:
                    continue
                if '"custom-title"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "custom-title":
                        custom_title = entry.get("customTitle")
                except json.JSONDecodeError:
                    continue
    except (OSError, PermissionError):
        pass

    return custom_title


def format_timestamp(ts):
    """Convert timestamp string or epoch ms to readable date."""
    if ts is None:
        return "unknown"
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        pass
    return "unknown"


def print_session(session):
    """Print a single session result with resume command."""
    title = session["custom_title"] or session["first_message"] or "(untitled)"
    cwd = session["cwd"]
    date = format_timestamp(session["timestamp"])
    sid = session["session_id"]

    print(f'  Session: "{title}"')
    print(f"    Dir:     {cwd}")
    print(f"    Date:    {date}")
    print(f"    Resume:  cd {cwd} && claude -r {sid}")
    print()


def collect_sessions(query=None):
    """Scan all project JSONL files and build session records.
    If query is provided, prints exact title matches immediately during collection.
    Returns (sessions, seen_set, early_match_count).
    """
    sessions = []
    seen = set()
    early_found = 0
    query_lower = query.lower() if query else None
    pattern = str(PROJECTS_DIR / "*" / "*.jsonl")

    for filepath in glob.glob(pattern):
        session_id, cwd, timestamp, first_message = read_head(filepath)
        if session_id is None:
            continue

        custom_title = read_tail_for_title(filepath)

        session = {
            "session_id": session_id,
            "cwd": cwd or "unknown",
            "timestamp": timestamp,
            "custom_title": custom_title,
            "first_message": first_message,
            "jsonl_path": filepath,
        }
        sessions.append(session)

        # Strategy 1 inline: print exact title matches as we find them
        if query_lower and custom_title and query_lower in custom_title.lower():
            print_session(session)
            seen.add(session_id)
            early_found += 1

    # Sort newest first
    sessions.sort(key=lambda s: s.get("timestamp") or "", reverse=True)
    return sessions, seen, early_found


def strategy_token_title(tokens, sessions, seen):
    """Strategy 2: Each token must appear as substring in customTitle (case-insensitive)."""
    print("[2/4] Searching session titles (token match)...")
    found = 0

    for session in sessions:
        title = session.get("custom_title")
        if not title:
            continue
        if session["session_id"] in seen:
            continue
        title_lower = title.lower()
        if all(token in title_lower for token in tokens):
            print_session(session)
            seen.add(session["session_id"])
            found += 1

    return found


def grep_file(filepath, term):
    """Check if term appears in file (excluding file-history-snapshot lines). Returns bool."""
    try:
        result = subprocess.run(
            ["grep", "-i", "-n", term, filepath],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return False
        for match_line in result.stdout.splitlines():
            if '"type":"file-history-snapshot"' not in match_line and \
               '"type": "file-history-snapshot"' not in match_line:
                return True
        return False
    except (subprocess.TimeoutExpired, OSError):
        return False


def strategy_grep_all(tokens, sessions, seen):
    """Strategy 3: ALL tokens must appear in the session file content."""
    print("[3/4] Searching session content (all words)...")
    found = 0

    for session in sessions:
        if session["session_id"] in seen:
            continue
        filepath = session["jsonl_path"]
        if all(grep_file(filepath, token) for token in tokens):
            print_session(session)
            seen.add(session["session_id"])
            found += 1

    return found


def strategy_grep_any(tokens, sessions, seen):
    """Strategy 4: ANY token appearing in the session file content is a match."""
    print("[4/4] Searching session content (any word)...")
    found = 0

    for session in sessions:
        if session["session_id"] in seen:
            continue
        filepath = session["jsonl_path"]
        if any(grep_file(filepath, token) for token in tokens):
            print_session(session)
            seen.add(session["session_id"])
            found += 1

    return found


def main():
    if len(sys.argv) < 2:
        print("Usage: find-session.py <search terms...>")
        print("Example: find-session.py cmux switch")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    tokens = [t.lower() for t in query.split() if t.lower() not in STOP_WORDS]

    if not tokens:
        print("All search terms are stop words. Please provide more specific terms.")
        sys.exit(1)

    # Collect sessions (prints strategy 1 matches during collection)
    print("[1/4] Searching session titles (exact match)...")
    sessions, seen, early_found = collect_sessions(query)
    if not sessions:
        print("No sessions found in ~/.claude/projects/")
        sys.exit(0)

    total_found = early_found

    # Strategy 2: Token title match
    total_found += strategy_token_title(tokens, sessions, seen)

    # Strategy 3: Grep all words
    total_found += strategy_grep_all(tokens, sessions, seen)

    # Strategy 4: Grep individual words
    total_found += strategy_grep_any(tokens, sessions, seen)

    if total_found == 0:
        print(f'\nNo sessions found matching "{query}"')


if __name__ == "__main__":
    main()

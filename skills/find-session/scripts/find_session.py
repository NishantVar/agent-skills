#!/usr/bin/env python3
"""Search for Claude Code sessions by title or content across all projects."""

import json
import os
import glob
import sys


def fmt_time(ts):
    if not ts:
        return ""
    try:
        return ts[:10]  # YYYY-MM-DD
    except Exception:
        return ""


def truncate(text, length=120):
    if not text:
        return "(empty session)"
    if len(text) <= length:
        return text
    return text[:length] + "..."


def get_jsonl_files():
    claude_dir = os.path.expanduser("~/.claude/projects")
    return [f for f in glob.glob(f"{claude_dir}/*/*.jsonl") if "/subagents/" not in f]


def collect_titled_sessions():
    """Fast scan: only extract title, cwd, and timestamps."""
    sessions = {}

    for jsonl_file in get_jsonl_files():
        session_id = os.path.basename(jsonl_file).replace(".jsonl", "")
        title = None
        cwd = None
        last_timestamp = None

        with open(jsonl_file, errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if cwd is None and rec.get("cwd"):
                        cwd = rec["cwd"]
                    if rec.get("timestamp"):
                        last_timestamp = rec["timestamp"]
                    if rec.get("type") == "custom-title" and rec.get("customTitle"):
                        title = rec["customTitle"]
                except Exception:
                    pass

        if title:
            sessions[session_id] = {
                "title": title,
                "cwd": cwd or "(unknown)",
                "last_timestamp": last_timestamp,
            }

    return sessions


# Prefixes that indicate system-injected content, not human-typed text
_INJECTED_PREFIXES = ("<", "Base directory for this skill", "[Request interrupted")

def is_human_text(text):
    """Return True if text looks like something the user actually typed."""
    return not text.startswith(_INJECTED_PREFIXES)


def extract_user_texts(line):
    """Extract human-typed text from a user message JSONL line.
    Skips system-injected content (tags, skill invocations, etc.).
    Handles both normal text blocks and character-per-block streaming format."""
    try:
        rec = json.loads(line)
    except Exception:
        return []
    if rec.get("type") != "user":
        return []
    msg = rec.get("message", {})
    if msg.get("role") != "user":
        return []

    texts = []
    str_chars = []  # buffer for consecutive raw string blocks (keystroke streaming)

    for block in msg.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            # Flush any buffered string chars first
            if str_chars:
                joined = "".join(str_chars).strip()
                if joined and is_human_text(joined):
                    texts.append(joined)
                str_chars = []
            text = block["text"].strip()
            if text and is_human_text(text):
                texts.append(text)
        elif isinstance(block, str):
            str_chars.append(block)

    # Flush remaining string chars
    if str_chars:
        joined = "".join(str_chars).strip()
        if joined and is_human_text(joined):
            texts.append(joined)

    return texts


def scan_files_parsed(search, files):
    """Scan JSONL files for search term in actual user-typed text only.
    Skips system-injected content. Returns list of matching file paths."""
    matching = []
    for f in files:
        with open(f, errors="replace") as fh:
            found = False
            for line in fh:
                # Quick pre-filter: skip lines that can't be user messages
                if '"type":"user"' not in line:
                    continue
                for text in extract_user_texts(line):
                    if search in text.lower():
                        found = True
                        break
                if found:
                    break
            if found:
                matching.append(f)
    return matching


_STOP_WORDS = {
    "a", "an", "the", "is", "it", "in", "on", "to", "of", "for", "and", "or",
    "this", "that", "with", "from", "into", "was", "were", "be", "been", "are",
    "do", "does", "did", "has", "have", "had", "not", "but", "if", "so", "at",
    "by", "my", "me", "i", "we", "you", "can", "how", "what", "when", "where",
}


def progressive_search(search, files):
    """Progressive content search through user-typed text.

    Search order:
      1. Exact phrase
      2. All meaningful words present (stop words removed)
      3. Any meaningful word present

    Returns (matching_files, strategy_description).
    """
    words = search.split()
    # Filter out stop words for multi-word searches, but keep at least one word
    meaningful = [w for w in words if w not in _STOP_WORDS]
    if not meaningful:
        meaningful = words  # all stop words — use them all

    # 1. Exact phrase
    matches = scan_files_parsed(search, files)
    if matches:
        return matches, "exact match"

    if len(meaningful) < 2:
        # Single meaningful word — already tried as exact match above
        # Try it as a standalone word search if it wasn't the full phrase
        if meaningful[0] != search:
            matches = scan_files_parsed(meaningful[0], files)
            if matches:
                return matches, f"keyword: {meaningful[0]}"
        return [], None

    # 2. All meaningful words present in the same session
    per_word = [set(scan_files_parsed(w, files)) for w in meaningful]
    intersection = per_word[0]
    for s in per_word[1:]:
        intersection &= s
    if intersection:
        return sorted(intersection), f"all keywords: {', '.join(meaningful)}"

    # 3. Any meaningful word present
    union = set()
    for s in per_word:
        union |= s
    if union:
        return sorted(union), f"any keyword: {', '.join(meaningful)}"

    return [], None


def extract_session_metadata(jsonl_file):
    """Parse a single JSONL file to extract display metadata."""
    session_id = os.path.basename(jsonl_file).replace(".jsonl", "")
    title = None
    cwd = None
    best_preview = None
    last_timestamp = None

    with open(jsonl_file, errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if cwd is None and rec.get("cwd"):
                    cwd = rec["cwd"]
                if rec.get("timestamp"):
                    last_timestamp = rec["timestamp"]
                if rec.get("type") == "custom-title" and rec.get("customTitle"):
                    title = rec["customTitle"]
                if rec.get("type") == "user" and rec.get("message", {}).get("role") == "user":
                    for text in extract_user_texts(line):
                        # Pick the first substantial message (5+ chars) as preview
                        if best_preview is None and len(text) >= 5:
                            best_preview = text
            except Exception:
                pass

    return session_id, {
        "title": title,
        "cwd": cwd or "(unknown)",
        "first_user_msg": best_preview,
        "last_timestamp": last_timestamp,
    }


def list_named_sessions():
    sessions = collect_titled_sessions()
    if not sessions:
        print("No named sessions found.")
        return

    for sid, info in sorted(sessions.items(), key=lambda x: x[1].get("last_timestamp") or "", reverse=True):
        print(f"  Title:   {info['title']}")
        print(f"  Project: {info['cwd']}")
        date = fmt_time(info["last_timestamp"])
        if date:
            print(f"  Date:    {date}")
        print(f"  Command: cd {info['cwd']} && claude --resume \"{info['title']}\"")
        print()

    print(f"{len(sessions)} named session(s) found.")


def print_content_results(results, strategy):
    shown = results[:15]
    for sid, info in shown:
        label = info["title"] or truncate(info["first_user_msg"], 80)
        print(f"  Session: {label}")
        if info["first_user_msg"]:
            print(f"  Preview: {truncate(info['first_user_msg'])}")
        print(f"  Project: {info['cwd']}")
        date = fmt_time(info["last_timestamp"])
        if date:
            print(f"  Date:    {date}")
        print(f"  Command: cd {info['cwd']} && claude --resume {sid}")
        print()
    if len(results) > 15:
        print(f"  ... and {len(results) - 15} more. Try a more specific search.\n")
    print(f"{len(results)} session(s) found ({strategy}).")


def search_sessions(search):
    # Step 1: fast title-only scan
    titled = collect_titled_sessions()
    title_matches = [(sid, info) for sid, info in titled.items() if search in info["title"].lower()]
    title_matches.sort(key=lambda x: x[1].get("last_timestamp") or "", reverse=True)

    if title_matches:
        for sid, info in title_matches:
            print(f"  Title:   {info['title']}")
            print(f"  Project: {info['cwd']}")
            date = fmt_time(info["last_timestamp"])
            if date:
                print(f"  Date:    {date}")
            print(f"  Command: cd {info['cwd']} && claude --resume \"{info['title']}\"")
            print()
        print(f"{len(title_matches)} session(s) found by title.")
        return

    # Step 2: no title match — progressive content search
    print(f"No title match for '{search}'. Searching session content...\n")
    files = get_jsonl_files()
    matching_files, strategy = progressive_search(search, files)

    if not matching_files:
        print(f"No sessions found matching '{search}'.")
        return

    # Extract metadata only for matching files
    results = [extract_session_metadata(f) for f in matching_files]
    results.sort(key=lambda x: x[1].get("last_timestamp") or "", reverse=True)
    print_content_results(results, strategy)


def main():
    search = sys.argv[1].strip().lower() if len(sys.argv) > 1 and sys.argv[1].strip() else ""

    if not search:
        list_named_sessions()
    else:
        search_sessions(search)


if __name__ == "__main__":
    main()

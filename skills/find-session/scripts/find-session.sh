#!/bin/bash
# find-session.sh — Search for Claude Code sessions by title or content
# Usage: find-session.sh [search_term]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/find_session.py" "$@"

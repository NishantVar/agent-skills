#!/usr/bin/env python3
"""Move a project folder and update all path-dependent metadata for Claude Code, Codex CLI, and Gemini CLI."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Move a project and update tool metadata.")
    parser.add_argument("--source", required=True, help="Current project path")
    parser.add_argument("--dest", required=True, help="Target project path")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying anything")
    parser.add_argument("--skip-move", action="store_true", help="Skip moving the folder, only fix references")
    return parser.parse_args()


def escape_path(p: str) -> str:
    """Convert /Users/foo/my-project to -Users-foo-my-project."""
    return p.replace("/", "-")


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def read_json(path: Path):
    with open(path, "r") as f:
        return json.load(f)


def write_json(path: Path, data, dry_run: bool):
    if not dry_run:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")


def main():
    args = parse_args()
    source = str(Path(args.source).resolve())
    dest = str(Path(args.dest).resolve())
    dry_run = args.dry_run
    skip_move = args.skip_move

    # Behave like `mv`: if dest is an existing directory, move source INTO it.
    # If dest doesn't exist, treat it as a rename (dest parent must exist).
    if not skip_move:
        if Path(dest).is_dir():
            dest = str(Path(dest) / Path(source).name)
    else:
        # With --skip-move, check if user meant "moved into existing dir"
        if not Path(dest).exists() and Path(dest).parent.is_dir():
            candidate = Path(args.dest).resolve() / Path(source).name
            if candidate.exists():
                dest = str(candidate)

    result = {
        "source": source,
        "dest": dest,
        "dry_run": dry_run,
        "folder_moved": False,
        "changes": [],
        "errors": [],
    }

    # --- Validation ---
    if not skip_move:
        if not Path(source).exists():
            result["errors"].append(f"Source does not exist: {source}")
            print(json.dumps(result, indent=2))
            sys.exit(1)
        if Path(dest).exists():
            result["errors"].append(f"Destination already exists: {dest}")
            print(json.dumps(result, indent=2))
            sys.exit(1)
        if not Path(dest).parent.exists():
            result["errors"].append(f"Destination parent does not exist: {Path(dest).parent}")
            print(json.dumps(result, indent=2))
            sys.exit(1)
    else:
        if not Path(dest).exists():
            result["errors"].append(f"Destination does not exist (expected with --skip-move): {dest}")
            print(json.dumps(result, indent=2))
            sys.exit(1)

    # --- Move the folder ---
    if not skip_move:
        if dry_run:
            result["changes"].append({"tool": "filesystem", "action": "would move folder", "from": source, "to": dest})
        else:
            try:
                shutil.move(source, dest)
                result["folder_moved"] = True
                result["changes"].append({"tool": "filesystem", "action": "moved folder", "from": source, "to": dest})
            except Exception as e:
                result["errors"].append(f"Failed to move folder: {e}")
                print(json.dumps(result, indent=2))
                sys.exit(1)
    else:
        result["changes"].append({"tool": "filesystem", "action": "skipped move (--skip-move)", "from": source, "to": dest})

    home = Path.home()

    # --- Claude Code ---
    claude_dir = home / ".claude"
    if claude_dir.exists():
        # a. Rename project directories (match exact and suffixed, e.g. -learning)
        old_escaped = escape_path(source)
        new_escaped = escape_path(dest)
        projects_dir = claude_dir / "projects"
        renamed_proj_dirs = []
        if projects_dir.exists():
            for proj_dir in sorted(projects_dir.iterdir()):
                if not proj_dir.is_dir():
                    continue
                if proj_dir.name == old_escaped or proj_dir.name.startswith(old_escaped + "-"):
                    suffix = proj_dir.name[len(old_escaped):]
                    new_proj_dir = projects_dir / (new_escaped + suffix)
                    try:
                        if dry_run:
                            result["changes"].append({"tool": "claude-code", "action": "would rename project dir", "from": str(proj_dir), "to": str(new_proj_dir)})
                            renamed_proj_dirs.append(proj_dir)
                        else:
                            proj_dir.rename(new_proj_dir)
                            result["changes"].append({"tool": "claude-code", "action": "renamed project dir", "from": str(proj_dir), "to": str(new_proj_dir)})
                            renamed_proj_dirs.append(new_proj_dir)
                    except Exception as e:
                        result["errors"].append(f"Claude Code: failed to rename project dir: {e}")

        # b. Update path references inside project dir files (session JSONLs, subagents, tool-results)
        for proj_dir in renamed_proj_dirs:
            try:
                file_count = 0
                for f in proj_dir.rglob("*"):
                    if not f.is_file():
                        continue
                    try:
                        content = f.read_text(errors="replace")
                        if source in content:
                            if not dry_run:
                                f.write_text(content.replace(source, dest))
                            file_count += 1
                    except Exception:
                        pass
                if file_count > 0:
                    action = "would update" if dry_run else "updated"
                    result["changes"].append({"tool": "claude-code", "action": f"{action} path refs in {file_count} file(s)", "dir": str(proj_dir)})
            except Exception as e:
                result["errors"].append(f"Claude Code: error updating project files in {proj_dir}: {e}")

        # c. Update session metadata
        sessions_dir = claude_dir / "sessions"
        if sessions_dir.exists():
            for sf in sessions_dir.glob("*.json"):
                try:
                    data = read_json(sf)
                    if data.get("cwd") == source:
                        if dry_run:
                            result["changes"].append({"tool": "claude-code", "action": "would update session cwd", "file": str(sf)})
                        else:
                            data["cwd"] = dest
                            write_json(sf, data, dry_run=False)
                            result["changes"].append({"tool": "claude-code", "action": "updated session cwd", "file": str(sf)})
                except Exception as e:
                    result["errors"].append(f"Claude Code: error updating session {sf.name}: {e}")

        # d. Update team configs
        teams_dir = claude_dir / "teams"
        if teams_dir.exists():
            for config_file in teams_dir.glob("*/config.json"):
                try:
                    data = read_json(config_file)
                    changed = False
                    members = data.get("members", [])
                    for member in members:
                        if member.get("cwd") == source:
                            member["cwd"] = dest
                            changed = True
                    if changed:
                        if dry_run:
                            result["changes"].append({"tool": "claude-code", "action": "would update team config", "file": str(config_file)})
                        else:
                            write_json(config_file, data, dry_run=False)
                            result["changes"].append({"tool": "claude-code", "action": "updated team config", "file": str(config_file)})
                except Exception as e:
                    result["errors"].append(f"Claude Code: error updating team config {config_file}: {e}")

    # --- Codex CLI ---
    codex_dir = home / ".codex"
    if codex_dir.exists():
        # a. Update config.toml
        config_toml = codex_dir / "config.toml"
        if config_toml.exists():
            try:
                content = config_toml.read_text()
                if source in content:
                    if dry_run:
                        result["changes"].append({"tool": "codex", "action": "would update config.toml project key"})
                    else:
                        new_content = content.replace(source, dest)
                        config_toml.write_text(new_content)
                        result["changes"].append({"tool": "codex", "action": "updated config.toml project key"})
            except Exception as e:
                result["errors"].append(f"Codex: error updating config.toml: {e}")

        # b. Update skill symlinks
        skills_dir = codex_dir / "skills"
        if skills_dir.exists():
            for link in skills_dir.iterdir():
                if link.is_symlink():
                    try:
                        target = str(link.resolve())
                        if target.startswith(source):
                            new_target = dest + target[len(source):]
                            if dry_run:
                                result["changes"].append({"tool": "codex", "action": "would update skill symlink", "link": str(link), "old_target": target, "new_target": new_target})
                            else:
                                os.unlink(link)
                                os.symlink(new_target, link)
                                result["changes"].append({"tool": "codex", "action": "updated skill symlink", "link": str(link), "new_target": new_target})
                    except Exception as e:
                        result["errors"].append(f"Codex: error updating symlink {link}: {e}")

        # c. Update state_5.sqlite threads table
        state_db = codex_dir / "state_5.sqlite"
        if state_db.exists():
            try:
                conn = sqlite3.connect(str(state_db))
                cur = conn.cursor()
                if dry_run:
                    cur.execute("SELECT COUNT(*) FROM threads WHERE cwd = ?", (source,))
                    count = cur.fetchone()[0]
                    if count > 0:
                        result["changes"].append({"tool": "codex", "action": f"would update {count} thread(s) cwd in state_5.sqlite"})
                else:
                    cur.execute("UPDATE threads SET cwd = ? WHERE cwd = ?", (dest, source))
                    if cur.rowcount > 0:
                        conn.commit()
                        result["changes"].append({"tool": "codex", "action": f"updated {cur.rowcount} thread(s) cwd in state_5.sqlite"})
                conn.close()
            except Exception as e:
                result["errors"].append(f"Codex: error updating state_5.sqlite: {e}")

        # d. Update session_meta.cwd in session JSONL files
        codex_sessions_dir = codex_dir / "sessions"
        if codex_sessions_dir.exists():
            for jsonl_file in codex_sessions_dir.rglob("*.jsonl"):
                try:
                    lines = jsonl_file.read_text().splitlines(keepends=True)
                    if not lines:
                        continue
                    first_line = json.loads(lines[0])
                    if (first_line.get("type") == "session_meta"
                            and first_line.get("payload", {}).get("cwd") == source):
                        if dry_run:
                            result["changes"].append({"tool": "codex", "action": "would update session_meta cwd", "file": str(jsonl_file)})
                        else:
                            first_line["payload"]["cwd"] = dest
                            lines[0] = json.dumps(first_line) + "\n"
                            jsonl_file.write_text("".join(lines))
                            result["changes"].append({"tool": "codex", "action": "updated session_meta cwd", "file": str(jsonl_file)})
                except Exception as e:
                    result["errors"].append(f"Codex: error updating session JSONL {jsonl_file}: {e}")

    # --- Gemini CLI ---
    gemini_dir = home / ".gemini"
    if gemini_dir.exists():
        # a. Update projects.json
        projects_json = gemini_dir / "projects.json"
        if projects_json.exists():
            try:
                data = read_json(projects_json)
                projects = data.get("projects", {})
                if source in projects:
                    if dry_run:
                        result["changes"].append({"tool": "gemini", "action": "would update projects.json key", "old_key": source, "new_key": dest})
                    else:
                        projects[dest] = projects.pop(source)
                        data["projects"] = projects
                        write_json(projects_json, data, dry_run=False)
                        result["changes"].append({"tool": "gemini", "action": "updated projects.json key", "old_key": source, "new_key": dest})
            except Exception as e:
                result["errors"].append(f"Gemini: error updating projects.json: {e}")

        # b. Update trustedFolders.json
        trusted_json = gemini_dir / "trustedFolders.json"
        if trusted_json.exists():
            try:
                data = read_json(trusted_json)
                if source in data:
                    if dry_run:
                        result["changes"].append({"tool": "gemini", "action": "would update trustedFolders.json key", "old_key": source, "new_key": dest})
                    else:
                        data[dest] = data.pop(source)
                        write_json(trusted_json, data, dry_run=False)
                        result["changes"].append({"tool": "gemini", "action": "updated trustedFolders.json key", "old_key": source, "new_key": dest})
            except Exception as e:
                result["errors"].append(f"Gemini: error updating trustedFolders.json: {e}")

        # c. Update .project_root files in history/ and tmp/
        for subdir_name in ("history", "tmp"):
            subdir = gemini_dir / subdir_name
            if subdir.exists():
                for proj_root_file in subdir.glob("*/.project_root"):
                    try:
                        content = proj_root_file.read_text().strip()
                        if content == source:
                            if dry_run:
                                result["changes"].append({"tool": "gemini", "action": f"would update .project_root in {subdir_name}/", "file": str(proj_root_file)})
                            else:
                                proj_root_file.write_text(dest)
                                result["changes"].append({"tool": "gemini", "action": f"updated .project_root in {subdir_name}/", "file": str(proj_root_file)})
                    except Exception as e:
                        result["errors"].append(f"Gemini: error updating {proj_root_file}: {e}")

        # d. Handle hashed directories in tmp/
        tmp_dir = gemini_dir / "tmp"
        if tmp_dir.exists():
            old_hash = sha256_hex(source)
            new_hash = sha256_hex(dest)
            old_hash_dir = tmp_dir / old_hash
            new_hash_dir = tmp_dir / new_hash
            if old_hash_dir.exists():
                try:
                    if dry_run:
                        result["changes"].append({"tool": "gemini", "action": "would rename hashed tmp dir", "from": str(old_hash_dir), "to": str(new_hash_dir)})
                    else:
                        old_hash_dir.rename(new_hash_dir)
                        result["changes"].append({"tool": "gemini", "action": "renamed hashed tmp dir", "from": str(old_hash_dir), "to": str(new_hash_dir)})
                except Exception as e:
                    result["errors"].append(f"Gemini: error renaming hashed tmp dir: {e}")

                # Update projectHash in session JSON files inside the (now renamed) dir
                target_dir = new_hash_dir if not dry_run else old_hash_dir
                for json_file in target_dir.glob("*.json"):
                    try:
                        data = read_json(json_file)
                        if data.get("projectHash") == old_hash:
                            if dry_run:
                                result["changes"].append({"tool": "gemini", "action": "would update projectHash in session file", "file": str(json_file)})
                            else:
                                data["projectHash"] = new_hash
                                write_json(json_file, data, dry_run=False)
                                result["changes"].append({"tool": "gemini", "action": "updated projectHash in session file", "file": str(json_file)})
                    except Exception as e:
                        result["errors"].append(f"Gemini: error updating session file {json_file}: {e}")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Team state management for ateam skill."""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

STATE_DIR = os.path.expanduser("~/.claude/multi-teams")


def _team_dir(name):
    return os.path.join(STATE_DIR, name)


def _team_path(name):
    return os.path.join(_team_dir(name), "team.json")


def _log_path(name):
    return os.path.join(_team_dir(name), "messages.log")


def _load(name):
    with open(_team_path(name)) as f:
        return json.load(f)


def _save(name, data):
    with open(_team_path(name), "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def create(name, description=None):
    if os.path.isfile(_team_path(name)):
        return {"error": f"Team '{name}' already exists"}
    os.makedirs(_team_dir(name), exist_ok=True)
    data = {
        "name": name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "members": [],
    }
    if description:
        data["description"] = description
    _save(name, data)
    return {"ok": True, "team": name, "path": _team_path(name)}


def delete(name):
    team_dir = _team_dir(name)
    if not os.path.isdir(team_dir):
        return {"error": f"Team '{name}' not found"}
    shutil.rmtree(team_dir)
    return {"ok": True, "deleted": name}


def _cmd_create(args):
    return create(args.name, description=args.description)


def _cmd_delete(args):
    return delete(args.team)


def main():
    parser = argparse.ArgumentParser(description="ateam state manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--description", default=None)
    p_create.set_defaults(func=_cmd_create)

    p_delete = sub.add_parser("delete")
    p_delete.add_argument("--team", required=True)
    p_delete.set_defaults(func=_cmd_delete)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()

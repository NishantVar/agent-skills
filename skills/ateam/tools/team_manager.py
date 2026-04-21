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


def add_member(team, name, llm, protocol, surface=None, backend=None,
               native_team=None, cwd=None):
    try:
        data = _load(team)
    except FileNotFoundError:
        return {"error": f"Team '{team}' not found"}

    for m in data["members"]:
        if m["name"] == name:
            return {"error": f"Member '{name}' already exists in team '{team}'"}

    member = {
        "name": name,
        "llmType": llm,
        "protocol": protocol,
        "status": "idle",
        "messageCount": 0,
    }
    if protocol == "terminal":
        if surface:
            member["surfaceRef"] = surface
        if backend:
            member["backend"] = backend
    if protocol == "native" and native_team:
        member["nativeTeamName"] = native_team
    if cwd:
        member["cwd"] = cwd

    data["members"].append(member)
    _save(team, data)
    return {"ok": True, "member": name, "team": team}


def list_teams(team=None):
    if team:
        try:
            return _load(team)
        except FileNotFoundError:
            return {"error": f"Team '{team}' not found"}
    teams = []
    if os.path.isdir(STATE_DIR):
        for name in sorted(os.listdir(STATE_DIR)):
            if os.path.isfile(os.path.join(STATE_DIR, name, "team.json")):
                teams.append(name)
    return {"teams": teams}


def update_status(team, name, status):
    try:
        data = _load(team)
    except FileNotFoundError:
        return {"error": f"Team '{team}' not found"}

    for m in data["members"]:
        if m["name"] == name:
            m["status"] = status
            _save(team, data)
            return {"ok": True, "member": name, "status": status}

    return {"error": f"Member '{name}' not found in team '{team}'"}


def log_message(team, sender, to, sentinel=None, protocol="terminal"):
    team_dir = _team_dir(team)
    if not os.path.isdir(team_dir):
        return {"error": f"Team '{team}' not found"}

    entry = {
        "from": sender,
        "to": to,
        "sentinelId": sentinel,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "protocol": protocol,
    }

    with open(_log_path(team), "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Increment messageCount for target member
    data = _load(team)
    for m in data["members"]:
        if m["name"] == to:
            m["messageCount"] = m.get("messageCount", 0) + 1
            break
    _save(team, data)

    return {"ok": True, "logged": entry}


def _cmd_create(args):
    return create(args.name, description=args.description)


def _cmd_delete(args):
    return delete(args.team)


def _cmd_add_member(args):
    return add_member(
        args.team, args.name, llm=args.llm, protocol=args.protocol,
        surface=args.surface, backend=args.backend,
        native_team=args.native_team, cwd=args.cwd,
    )


def _cmd_list(args):
    return list_teams(team=args.team)


def _cmd_update_status(args):
    return update_status(args.team, args.name, args.status)


def _cmd_log_message(args):
    return log_message(args.team, sender=args.sender, to=args.to,
                       sentinel=args.sentinel, protocol=args.protocol)


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

    p_add = sub.add_parser("add-member")
    p_add.add_argument("--team", required=True)
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--llm", required=True, choices=["codex", "gemini", "claude"])
    p_add.add_argument("--protocol", required=True, choices=["terminal", "native"])
    p_add.add_argument("--surface", default=None)
    p_add.add_argument("--backend", default=None)
    p_add.add_argument("--native-team", default=None)
    p_add.add_argument("--cwd", default=None)
    p_add.set_defaults(func=_cmd_add_member)

    p_list = sub.add_parser("list")
    p_list.add_argument("--team", default=None)
    p_list.set_defaults(func=_cmd_list)

    p_status = sub.add_parser("update-status")
    p_status.add_argument("--team", required=True)
    p_status.add_argument("--name", required=True)
    p_status.add_argument("--status", required=True,
                          choices=["idle", "working", "blocked", "unresponsive"])
    p_status.set_defaults(func=_cmd_update_status)

    p_log = sub.add_parser("log-message")
    p_log.add_argument("--team", required=True)
    p_log.add_argument("--from", dest="sender", required=True)
    p_log.add_argument("--to", required=True)
    p_log.add_argument("--sentinel", default=None)
    p_log.add_argument("--protocol", required=True, choices=["terminal", "native"])
    p_log.set_defaults(func=_cmd_log_message)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result.get("error") else 0)


if __name__ == "__main__":
    main()

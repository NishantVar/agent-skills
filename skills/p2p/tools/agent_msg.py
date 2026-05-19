#!/usr/bin/env python3
"""P2P messaging between cmux agents.

Routing: per-surface manifest at ~/.cmux/agents/by-surface/<surface>.json.
Transport: cmux set-buffer + paste-buffer (handles large payloads).
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REGISTRY = Path.home() / ".cmux" / "agents" / "by-surface"
BOOTSTRAP_TAG = "[p2p-bootstrap]"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def my_surface():
    r = run(["cmux", "identify", "--json"])
    if r.returncode != 0:
        sys.exit("error: cmux identify failed (not running inside cmux?)")
    data = json.loads(r.stdout)
    caller = data.get("caller") or data.get("focused") or {}
    surf = caller.get("surface_ref")
    if not surf:
        sys.exit("error: could not resolve own surface_ref from cmux identify")
    return surf


def manifest_path(surface_ref):
    safe = surface_ref.replace(":", "_")
    return REGISTRY / f"{safe}.json"


def live_surfaces():
    r = run(["cmux", "--json", "tree", "--all"])
    if r.returncode != 0:
        return set()
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return set()
    refs = set()
    for w in data.get("windows", []):
        for ws in w.get("workspaces", []):
            for pane in ws.get("panes", []):
                for s in pane.get("surfaces", []):
                    if s.get("ref"):
                        refs.add(s["ref"])
    return refs


def surface_titles():
    """Map surface_ref -> title for all live surfaces."""
    r = run(["cmux", "--json", "tree", "--all"])
    if r.returncode != 0:
        return {}
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}
    out = {}
    for w in data.get("windows", []):
        for ws in w.get("workspaces", []):
            for pane in ws.get("panes", []):
                for s in pane.get("surfaces", []):
                    if s.get("ref"):
                        out[s["ref"]] = s.get("title") or ""
    return out


def load_manifests(sweep=True):
    """Return list of manifest dicts. Sweeps stale manifests (surface gone)."""
    if not REGISTRY.exists():
        return []
    live = live_surfaces() if sweep else None
    out = []
    for f in REGISTRY.glob("*.json"):
        try:
            m = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            f.unlink(missing_ok=True)
            continue
        if sweep and m.get("surface_ref") not in live:
            f.unlink(missing_ok=True)
            continue
        out.append(m)
    return out


def send_buffer(surface_ref, text):
    """Send text to a surface via set-buffer + paste-buffer + Enter."""
    r = run(["cmux", "set-buffer", "--name", "agent_msg", "--", text])
    if r.returncode != 0:
        sys.exit(f"error: cmux set-buffer failed: {r.stderr.strip()}")
    r = run(["cmux", "paste-buffer", "--name", "agent_msg",
             "--surface", surface_ref])
    if r.returncode != 0:
        sys.exit(f"error: cmux paste-buffer failed: {r.stderr.strip()}")
    # Give the target terminal a moment to ingest the paste before Enter,
    # otherwise the keypress can race the paste and the message sits unsent.
    time.sleep(0.3)
    r = run(["cmux", "send-key", "--surface", surface_ref, "enter"])
    if r.returncode != 0:
        sys.exit(f"error: cmux send-key enter failed: {r.stderr.strip()}")


def read_message_arg(args):
    if args.message_file:
        return Path(args.message_file).read_text()
    if args.message is not None:
        return args.message
    return ""


# ---------- subcommands ----------

def cmd_whoami(args):
    p = manifest_path(my_surface())
    if not p.exists():
        sys.exit(4)
    sys.stdout.write(p.read_text())


def cmd_register(args):
    surf = my_surface()
    REGISTRY.mkdir(parents=True, exist_ok=True)
    name = args.name.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        sys.exit(f"error: name must be lowercase snake_case, got: {name!r}")
    # Collision check across other live agents
    for m in load_manifests():
        if m.get("name") == name and m.get("surface_ref") != surf:
            sys.exit(f"error: name '{name}' is already taken by "
                     f"{m.get('surface_ref')}")
    data = {
        "name": name,
        "surface_ref": surf,
        "started_at": int(time.time()),
    }
    manifest_path(surf).write_text(json.dumps(data, indent=2))
    run(["cmux", "rename-tab", "--surface", surf, name])
    sys.stdout.write(json.dumps(data, indent=2))


def cmd_list_peers(args):
    surf = my_surface()
    peers = [m for m in load_manifests() if m.get("surface_ref") != surf]
    sys.stdout.write(json.dumps(peers, indent=2))


def cmd_resolve(args):
    matches = [m for m in load_manifests() if m.get("name") == args.peer]
    if len(matches) > 1:
        sys.exit(f"error: multiple agents claim name '{args.peer}': "
                 f"{[m['surface_ref'] for m in matches]}")
    if matches:
        sys.stdout.write(matches[0]["surface_ref"])
        return
    if args.fallback_tab:
        for ref, title in surface_titles().items():
            if title == args.peer:
                sys.stdout.write(ref)
                return
    sys.exit(f"error: peer '{args.peer}' not found in registry"
             + (" or tab titles" if args.fallback_tab else ""))


def cmd_send(args):
    me_path = manifest_path(my_surface())
    if not me_path.exists():
        sys.exit("error: this agent is not registered; run `register` first")
    me = json.loads(me_path.read_text())
    matches = [m for m in load_manifests() if m.get("name") == args.peer]
    if not matches:
        sys.exit(f"error: peer '{args.peer}' not in registry "
                 "(use `bootstrap` to connect first)")
    if len(matches) > 1:
        sys.exit(f"error: multiple agents claim name '{args.peer}'")
    body = read_message_arg(args)
    if not body.strip():
        sys.exit("error: empty message")
    tagged = f"[from: {me['name']}] {body}"
    send_buffer(matches[0]["surface_ref"], tagged)


def cmd_bootstrap(args):
    me_path = manifest_path(my_surface())
    if not me_path.exists():
        sys.exit("error: this agent is not registered; run `register` first")
    me = json.loads(me_path.read_text())
    msg = read_message_arg(args)
    body = (
        f"{BOOTSTRAP_TAG} You have an incoming peer-messaging connection.\n"
        f"peer_name={me['name']}\n"
        f"peer_surface={me['surface_ref']}\n"
        f"Please load the p2p skill, register yourself with a "
        f"stable short name (use your cmux tab title as a suggestion if you "
        f"do not already have one), and reply when ready."
    )
    if msg.strip():
        body += f"\n\nFirst message from {me['name']}: {msg}"
    send_buffer(args.peer_surface, body)


def cmd_bootstrap_payload(args):
    """Print bootstrap text for fork-terminal --delayed-input-file (spawn case)."""
    me_path = manifest_path(my_surface())
    if not me_path.exists():
        sys.exit("error: this agent is not registered; run `register` first")
    me = json.loads(me_path.read_text())
    msg = read_message_arg(args)
    suggested = args.target_name or ""
    suggest_line = (
        f"suggested_name={suggested}\n" if suggested else ""
    )
    body = (
        f"{BOOTSTRAP_TAG} You were spawned by peer-messaging.\n"
        f"peer_name={me['name']}\n"
        f"peer_surface={me['surface_ref']}\n"
        f"{suggest_line}"
        f"Pick a short snake_case name for yourself (or accept the "
        f"suggested_name if provided), load the p2p skill, "
        f"register, and reply."
    )
    if msg.strip():
        body += f"\n\nFirst message from {me['name']}: {msg}"
    sys.stdout.write(body)


def cmd_parse_incoming(args):
    """Scan own scrollback for the most recent bootstrap and print peer info."""
    surf = my_surface()
    r = run(["cmux", "read-screen", "--surface", surf, "--lines", "300"])
    if r.returncode != 0:
        sys.exit(f"error: cmux read-screen failed: {r.stderr.strip()}")
    lines = r.stdout.splitlines()
    idx = None
    for i in range(len(lines) - 1, -1, -1):
        if BOOTSTRAP_TAG in lines[i]:
            idx = i
            break
    if idx is None:
        sys.exit(5)
    block = lines[idx:idx + 20]
    out: dict[str, str] = {}
    for ln in block:
        if "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        k = k.strip()
        v = v.strip()
        if k in ("peer_name", "peer_surface", "suggested_name"):
            out[k] = v
    if not out.get("peer_name") or not out.get("peer_surface"):
        sys.exit("error: bootstrap block found but missing peer_name / "
                 "peer_surface")
    sys.stdout.write(json.dumps(out, indent=2))


# ---------- main ----------

def main():
    p = argparse.ArgumentParser(prog="agent_msg")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami").set_defaults(func=cmd_whoami)

    s = sub.add_parser("register")
    s.add_argument("--name", required=True)
    s.set_defaults(func=cmd_register)

    sub.add_parser("list-peers").set_defaults(func=cmd_list_peers)

    s = sub.add_parser("resolve")
    s.add_argument("--peer", required=True)
    s.add_argument("--fallback-tab", action="store_true")
    s.set_defaults(func=cmd_resolve)

    s = sub.add_parser("send")
    s.add_argument("--peer", required=True)
    s.add_argument("--message")
    s.add_argument("--message-file")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("bootstrap")
    s.add_argument("--peer-surface", required=True)
    s.add_argument("--message")
    s.add_argument("--message-file")
    s.set_defaults(func=cmd_bootstrap)

    s = sub.add_parser("bootstrap-payload")
    s.add_argument("--target-name")
    s.add_argument("--message")
    s.add_argument("--message-file")
    s.set_defaults(func=cmd_bootstrap_payload)

    sub.add_parser("parse-incoming").set_defaults(func=cmd_parse_incoming)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

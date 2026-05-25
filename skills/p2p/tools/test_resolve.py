#!/usr/bin/env python3
"""Test surface resolution in the p2p skill.

Agent-agnostic: run from inside any agent runtime (Claude Code, Codex,
Gemini, etc.) via its shell tool. Verifies my_surface() correctly resolves
the agent's own cmux surface across all four code paths and does NOT
silently fall back to the user-focused surface.

Imports the production module at `p2plib.surface` (the new package the
refactor introduced). Run after any change to `my_surface()`,
`_ancestor_ttys()`, or `_surface_from_tty_walk()` in p2plib/surface.py.

Usage:  python3 ~/.claude/skills/p2p/tools/test_resolve.py
Exit:   0 on success, 1 on any failure.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# p2plib lives one directory up from tools/. Add the skill root so
# `import p2plib.surface` resolves whether this file is run in-tree
# (this repo) or via the installed copy at ~/.claude/skills/p2p/.
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))
from p2plib import surface as surface_mod  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    if not condition:
        failures.append(name)


def run_resolve(env_overrides: dict | None = None, monkey: str = "") -> tuple[str, str, int]:
    """Invoke my_surface() in a clean subprocess. Returns (stdout, stderr, rc)."""
    code = (
        f"import sys\n"
        f"sys.path.insert(0, {str(SKILL_ROOT)!r})\n"
        f"from p2plib import surface as s\n"
        f"{monkey}\n"
        f"print(s.my_surface())\n"
    )
    env = os.environ.copy()
    for k, v in (env_overrides or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    r = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    return r.stdout.strip(), r.stderr.strip(), r.returncode


print("Testing surface resolution in p2plib.surface.my_surface()\n")

# Ground truth: where this agent actually is, via ppid -> tty -> cmux tree.
truth = surface_mod._surface_from_tty_walk()
print(f"Ground truth (tty walk): {truth!r}\n")
check("tty walk recovers a surface_ref",
      bool(truth and truth.startswith("surface:")))
if not truth:
    print("\nCannot continue without ground truth. Is this agent inside a cmux pane?")
    sys.exit(1)

# Path 1: env intact, cmux identify should succeed.
print("\nPath 1: normal env")
out, err, rc = run_resolve()
check("returns a surface_ref", out.startswith("surface:"), out)
check("matches tty-walk truth", out == truth, f"got {out!r}, want {truth!r}")

# Path 2: $CMUX_SURFACE_ID stripped, tty walk must recover.
print("\nPath 2: $CMUX_SURFACE_ID stripped")
out, err, rc = run_resolve(env_overrides={"CMUX_SURFACE_ID": None})
check("still resolves a surface_ref", out.startswith("surface:"), out)
check("matches tty-walk truth", out == truth, f"got {out!r}, want {truth!r}")

# Path 3: explicit override.
print("\nPath 3: AGENT_MSG_SURFACE_ID override")
out, err, rc = run_resolve(
    env_overrides={"AGENT_MSG_SURFACE_ID": "surface:test_override_999"}
)
check("override is returned verbatim",
      out == "surface:test_override_999", out)

# Path 4: everything stripped + tty walk neutered. Contract: returns
# None silently (the cli.py caller wraps None into errors.not_in_cmux()).
# Critically must NOT fall back to focused/anything-else and return a
# surface_ref.
print("\nPath 4: env stripped + tty walk neutered (expect None)")
out, err, rc = run_resolve(
    env_overrides={"CMUX_SURFACE_ID": None, "AGENT_MSG_SURFACE_ID": None},
    monkey="s._surface_from_tty_walk = lambda *a, **kw: None",
)
check("exits 0 (silent-None contract)", rc == 0,
      f"rc={rc} stderr={err!r}")
check("returns None (no surface_ref)", out == "None",
      f"got {out!r}")
check("does not silently return a surface_ref",
      not out.startswith("surface:"))

# Anti-regression: with env stripped, must NOT return data['focused'].
# Only meaningful when focused != our actual pane.
print("\nAnti-regression: stripped env must not return focused.surface_ref")
r = subprocess.run(["cmux", "identify", "--json"], capture_output=True, text=True)
focused = None
if r.returncode == 0:
    try:
        focused = (json.loads(r.stdout).get("focused") or {}).get("surface_ref")
    except json.JSONDecodeError:
        pass
if focused and focused != truth:
    out2, _, _ = run_resolve(env_overrides={"CMUX_SURFACE_ID": None})
    check("stripped-env resolution is our pane, not the focused pane",
          out2 == truth and out2 != focused,
          f"focused={focused!r} resolved={out2!r} truth={truth!r}")
else:
    print(f"  [SKIP] focused == truth, cannot distinguish "
          f"(focused={focused!r}, truth={truth!r}). "
          f"Focus a different pane and re-run for a stronger test.")

print()
if failures:
    print(f"FAILED ({len(failures)} check(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All checks passed.")

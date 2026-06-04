#!/usr/bin/env python3
"""cmux-watchdog summarizer — turn journaled pane output into Obsidian worklog
bullets by calling a generic OpenAI-compatible chat-completions API (DeepSeek-V4
by default).

This is the component that HOLDS the LLM call, by design. watchdog.py stays
network-free and model-free (it only captures / detects / journals / digests via
local file I/O and cmux); summarize.py is the separate sibling that reads the
digests watchdog.py produced and asks an LLM to summarize them. Splitting it this
way means summarization no longer needs an interactive agent attached — a
scheduler (launchd) can run `summarize.py run` on its own.

Two commands:
  run      one summary pass: shell out to watchdog.py digest, send each surface's
           unread digest to the LLM, append the bullets to today's worklog.
  install  render (and optionally load) a launchd LaunchAgent that runs `run`
           every --interval seconds — durable autonomous summarization with no
           agent attached, surviving reboot / logout / agent crash.

Config resolution (real env wins; then KEY=VALUE files in order, so launchd's
minimal environment still finds keys/paths — first file wins among files):
  1. ~/.cmux-watchdog/summarizer.env   (skill-specific override)
  2. ~/genesis/.env                    (shared secrets file)
  LLM_API_KEY    (or DEEPSEEK_API_KEY)        required for `run`
  LLM_API_BASE   default https://api.deepseek.com
  LLM_MODEL      default deepseek-v4-flash
  OBSIDIAN       vault root; worklog written to $OBSIDIAN/worklog/<date>.md

The API is plain OpenAI-compatible Chat Completions over stdlib HTTP — no SDK
dependency — so any compatible provider works by changing LLM_API_BASE/LLM_MODEL.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_LABEL = "com.cmux-watchdog.summarizer"

_WS_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

SUMMARY_SYSTEM_PROMPT = (
    "You summarize a single terminal pane's captured output into a worklog entry. "
    "Return concise markdown bullets grouped under these headings, and OMIT any "
    "heading you have nothing to report for:\n"
    "- Done: what was accomplished\n"
    "- Issues: problems encountered\n"
    "- Stuck/Blocked: where work stalled and on what\n"
    "- Errors: concrete errors or failures hit\n"
    "- Notes: anything else salient for later analysis\n"
    "Use multiple bullets per heading when warranted. Summarize ONLY what the "
    "provided log shows — never invent. Output only the bullets, no preamble."
)


# --- config ----------------------------------------------------------------

def _state_root() -> Path:
    """Root for journal/digest/cursor/log state. Mirrors watchdog.py so both
    components agree; CMUX_WATCHDOG_HOME overrides the default (tests use it)."""
    override = os.environ.get("CMUX_WATCHDOG_HOME")
    return Path(override) if override else Path.home() / ".cmux-watchdog"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load_cursors() -> dict:
    """Per-journal-file read cursors written by watchdog.py digest. This IS the
    'last summarized point' — a file with bytes past its cursor is unsummarized."""
    try:
        return json.loads((_state_root() / "cursors.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def pending_dates(today: str, *, cursors: dict | None = None,
                  journal_root: Path | None = None) -> list[str]:
    """Sorted journal dates (<= today) that still have unread bytes past their
    cursor — i.e. content captured but not yet summarized."""
    journal_root = journal_root or (_state_root() / "journal")
    cursors = _load_cursors() if cursors is None else cursors
    if not journal_root.is_dir():
        return []
    out: list[str] = []
    for d in sorted(journal_root.iterdir()):
        if not d.is_dir() or not _DATE_RE.match(d.name) or d.name > today:
            continue
        for jf in d.glob("*.log"):
            if jf.stat().st_size > cursors.get(str(jf), 0):
                out.append(d.name)
                break
    return out


# --- summary state (durable retry across LLM/append failures) --------------
# digest advances the journal cursor as soon as it writes a digest FILE — before
# any LLM call or worklog append. So the cursor alone can't be the summary commit
# point: a failed LLM/append would leave the bytes un-summarized yet un-retried.
# The durable unit is therefore the digest file, and this manifest records which
# digest files have actually reached the worklog. A digest file is marked
# summarized ONLY after its bullets are appended; until then every later run
# retries it. (Identity is persisted here so retried "orphan" files don't need
# their — lossy — filename slugs re-parsed.)

def _summary_state_path() -> Path:
    return _state_root() / "summary_state.json"


def _load_summary_state() -> dict:
    try:
        return json.loads(_summary_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_summary_state(state: dict) -> None:
    path = _summary_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)


def unsummarized_dates(state: dict | None = None) -> list[str]:
    """Dates that still have digest files recorded but not yet summarized — i.e.
    prior runs whose LLM/append failed. Catch-up must revisit these even when the
    journal cursor shows no new bytes for the day."""
    state = _load_summary_state() if state is None else state
    return sorted({m["date"] for m in state.values() if not m.get("summarized")})


@contextlib.contextmanager
def _summarizer_lock():
    """Advisory exclusive lock so only one summary run mutates the digest cursor
    and summary state at a time — the launchd job, a manual `summarize.py run`,
    and an attached consumer could otherwise overlap and split/race the cursor.
    Non-blocking: yields False when another run already holds it."""
    path = _state_root() / "summarizer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        fh.close()


def _parse_env_file(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Ignores blanks, # comments, and a leading
    'export '. Surrounding single/double quotes on the value are stripped."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            out[key] = val
    return out


def _default_env_files() -> list[Path]:
    """Env files consulted (in precedence order, first wins among files):
      1. ~/.cmux-watchdog/summarizer.env  — skill-specific override
      2. ~/genesis/.env                   — shared secrets file
    Process env still wins over both. The launchd job has no shell env, so one of
    these MUST carry LLM_API_KEY/DEEPSEEK_API_KEY (and OBSIDIAN)."""
    return [_state_root() / "summarizer.env", Path.home() / "genesis" / ".env"]


def load_config(env: dict | None = None, env_files: list[Path] | None = None) -> dict:
    """Merge process env over the env files (env wins; among files, earlier wins).
    Returns the resolved api_key / api_base / model / obsidian; missing key/obsidian
    surface as None so callers can give a precise error. env_files is injectable so
    tests never read the real shared secrets file."""
    env = dict(os.environ if env is None else env)
    if env_files is None:
        env_files = _default_env_files()
    file_vals: list[dict[str, str]] = []
    for p in env_files:
        try:
            file_vals.append(_parse_env_file(p.read_text(encoding="utf-8")))
        except FileNotFoundError:
            continue

    def pick(*keys: str) -> str | None:
        for k in keys:
            if env.get(k):
                return env[k]
        for vals in file_vals:          # files in precedence order
            for k in keys:
                if vals.get(k):
                    return vals[k]
        return None

    obsidian = pick("OBSIDIAN")
    if obsidian:
        # env-file values like "~/obsidian" or "$HOME/obsidian" are literal strings;
        # expand them so Path() doesn't create a literal "~" directory.
        obsidian = os.path.expanduser(os.path.expandvars(obsidian))
    return {
        "api_key": pick("LLM_API_KEY", "DEEPSEEK_API_KEY"),
        "api_base": (pick("LLM_API_BASE") or DEFAULT_API_BASE).rstrip("/"),
        "model": pick("LLM_MODEL") or DEFAULT_MODEL,
        "obsidian": obsidian,
    }


# --- LLM call (OpenAI-compatible chat completions) -------------------------

def build_payload(digest_text: str, model: str, *, ws_title: str, title: str) -> dict:
    """Build the chat-completions request body. Pure — no network."""
    user = (f"Pane: {title} (workspace: {ws_title}).\n"
            f"Captured output to summarize:\n\n{digest_text}")
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }


def extract_content(api_response: dict) -> str:
    """Pull the assistant text out of an OpenAI-shaped response. Pure."""
    return api_response["choices"][0]["message"]["content"].strip()


def _http_post(url: str, headers: dict, body: bytes) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_llm(payload: dict, config: dict, transport=None) -> str:
    """POST to {api_base}/chat/completions and return the assistant content.
    `transport(url, headers, body_bytes) -> dict` is injectable so tests run
    without network; defaults to a real stdlib HTTP POST."""
    transport = transport or _http_post
    url = f"{config['api_base']}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }
    body = json.dumps(payload).encode("utf-8")
    return extract_content(transport(url, headers, body))


# --- digest + worklog ------------------------------------------------------

def _skill_dir() -> Path:
    return Path(__file__).resolve().parent


def run_digest(scope: str | None, date: str | None, skill_dir: Path | None = None) -> list[dict]:
    """Shell out to the sibling watchdog.py digest (same skill, allowed) and
    return its surfaces[]. digest is pure local file I/O — no cmux, no network —
    so this is deterministic given the journal state."""
    skill_dir = skill_dir or _skill_dir()
    cmd = [sys.executable, str(skill_dir / "watchdog.py"), "digest"]
    if scope:
        cmd += ["--workspace", scope]
    if date:
        cmd += ["--date", date]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    parsed = json.loads(out)
    return parsed.get("surfaces", [])


def format_worklog(results: list[dict], hhmm: str) -> str:
    """Group per-surface bullets under one '## HH:MM — <workspace>' heading per
    workspace. Pure — the exact text is asserted in tests."""
    by_ws: dict[str, list[dict]] = {}
    for r in results:
        by_ws.setdefault(r["workspace_title"], []).append(r)
    sections: list[str] = []
    for ws_title, items in by_ws.items():
        lines = [f"## {hhmm} — {ws_title}", ""]
        for it in items:
            lines.append(f"**{it['title']}** ({it['surface_ref']})")
            lines.append(it["bullets"].strip())
            lines.append("")
        sections.append("\n".join(lines).rstrip())
    return "\n\n".join(sections) + "\n"


def append_worklog(text: str, obsidian: str, date: str) -> Path:
    """Append a section to $OBSIDIAN/worklog/<date>.md, creating it if absent."""
    path = Path(obsidian) / "worklog" / f"{date}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "\n" if path.exists() and path.stat().st_size > 0 else ""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(prefix + text)
    return path


def run_pass(scope: str | None, date: str, config: dict, *, transport=None,
             skill_dir: Path | None = None) -> dict:
    """One full summary pass for a date, crash/failure-safe:
      1. digest flushes new journal bytes into digest FILES (cursor advances).
      2. register each new digest file in the summary-state manifest.
      3. LLM-summarize every UN-summarized digest file for this date (new files
         AND orphans from prior runs whose LLM/append failed) — per-file errors
         are caught so one bad surface can't sink the batch.
      4. append the successful bullets, then mark ONLY those files summarized.
         If the append raises, nothing is marked, so the whole batch retries next
         run. `transport` is injected by tests to avoid network."""
    surfaces = run_digest(scope, date, skill_dir)
    state = _load_summary_state()
    for s in surfaces:
        if s.get("unread_line_count", 0) <= 0:
            continue
        state.setdefault(s["digest_file"], {
            "workspace_title": s["workspace_title"],
            "title": s["title"],
            "surface_ref": s["surface_ref"],
            "date": date,
            "summarized": False,
        })
    _save_summary_state(state)  # record work durably BEFORE summarizing

    todo = [(p, m) for p, m in state.items()
            if m["date"] == date and not m.get("summarized")]
    results: list[dict] = []
    done_paths: list[str] = []
    failed: list[dict] = []
    for path, meta in todo:
        try:
            digest_text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            # digest file vanished (manual cleanup) — content is unrecoverable;
            # mark done so it isn't retried forever.
            meta["summarized"] = True
            continue
        try:
            bullets = call_llm(
                build_payload(digest_text, config["model"],
                              ws_title=meta["workspace_title"], title=meta["title"]),
                config, transport)
        except Exception as e:  # network / non-200 / malformed response
            failed.append({"digest_file": path, "error": str(e)[:200]})
            continue  # leave un-summarized for the next run to retry
        results.append({**{k: meta[k] for k in
                           ("workspace_title", "title", "surface_ref")}, "bullets": bullets})
        done_paths.append(path)

    worklog_path = None
    if results:
        section = format_worklog(results, datetime.now().strftime("%H:%M"))
        # append first; only commit the manifest if it succeeded (else full retry).
        try:
            worklog_path = str(append_worklog(section, config["obsidian"], date))
        except OSError as e:
            _save_summary_state(state)  # nothing marked summarized -> full retry
            return {"ok": False, "date": date, "surfaces_summarized": 0,
                    "error": f"worklog append failed: {e}",
                    "failed": failed, "worklog": None}
        for p in done_paths:
            state[p]["summarized"] = True
    _save_summary_state(state)
    return {
        "ok": True,
        "date": date,
        "surfaces_summarized": len(results),
        "failed": failed,
        "worklog": worklog_path,
    }


def run_catchup(scope: str | None, today: str, config: dict, *, max_days: int = 1,
                catch_up: bool = False, transport=None,
                skill_dir: Path | None = None) -> dict:
    """Summarize every unsummarized day since the last summarized point, not just
    today — so an overnight (or longer) gap is caught up on the next run.

    Bounded autonomy: only dates within `max_days` of today are summarized
    automatically (max_days=1 -> today + yesterday, the normal overnight case).
    Older backlog is NOT processed on its own — it's returned in `deferred` with a
    `resume_cmd`, so a human/agent can confirm before churning through >1 day of
    history. Passing catch_up=True (what an agent runs after the user approves)
    lifts the cap and processes everything pending."""
    # union of dates with new journal bytes AND dates with un-summarized digest
    # files from prior failed runs (the latter have no new bytes but must retry).
    pending = sorted(set(pending_dates(today)) | set(unsummarized_dates()))
    cutoff = (date.fromisoformat(today) - timedelta(days=max_days)).isoformat()
    if catch_up:
        eligible, deferred = pending, []
    else:
        eligible = [d for d in pending if d >= cutoff]
        deferred = [d for d in pending if d < cutoff]

    summarized = []
    total = 0
    failed: list[dict] = []
    for d in eligible:
        rep = run_pass(scope, d, config, transport=transport, skill_dir=skill_dir)
        total += rep["surfaces_summarized"]
        failed.extend(rep.get("failed", []))
        summarized.append({"date": d, "surfaces_summarized": rep["surfaces_summarized"],
                           "worklog": rep["worklog"]})

    resume_cmd = None
    note = None
    if deferred:
        ws = scope or "all"
        resume_cmd = " ".join(shlex.quote(a) for a in (
            "python3", str(Path(__file__).resolve()), "run", "--catch-up",
            "--workspace", ws))
        note = (f"{len(deferred)} day(s) of backlog older than {cutoff} were NOT "
                "summarized automatically (>1 day). Confirm with the user, then run "
                "resume_cmd to process them.")
    return {
        "ok": True,
        "today": today,
        "summarized": summarized,
        "total_surfaces": total,
        "failed": failed,
        "deferred": deferred,
        "resume_cmd": resume_cmd,
        "note": note,
    }


# --- launchd install -------------------------------------------------------

def render_plist(*, label: str, python: str, script: str, scope: str,
                 interval: int, out_log: str, err_log: str,
                 run_at_load: bool) -> str:
    """Render a LaunchAgent plist that runs `summarize.py run` every interval
    seconds. Built via plistlib so paths/scope containing &, <, or spaces are
    XML-escaped correctly. Pure — asserted in tests."""
    doc = {
        "Label": label,
        "ProgramArguments": [python, script, "run", "--workspace", scope],
        "StartInterval": int(interval),
        "RunAtLoad": bool(run_at_load),
        "ProcessType": "Background",
        "StandardOutPath": out_log,
        "StandardErrorPath": err_log,
    }
    return plistlib.dumps(doc).decode("utf-8")


def _plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


# --- commands --------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    config = load_config()
    if not config["api_key"]:
        print(json.dumps({"ok": False, "error": "no LLM_API_KEY / DEEPSEEK_API_KEY "
                          "in env or summarizer.env"}))
        return 1
    if not config["obsidian"]:
        print(json.dumps({"ok": False, "error": "no OBSIDIAN in env or summarizer.env"}))
        return 1
    with _summarizer_lock() as got:
        if not got:
            print(json.dumps({"ok": True, "skipped": "already_running"}))
            return 0
        if args.date:
            # explicit single-date escape hatch: no catch-up, no cap.
            report = run_pass(args.workspace, args.date, config)
        else:
            report = run_catchup(args.workspace, _today(), config,
                                 max_days=int(args.max_days), catch_up=args.catch_up)
        print(json.dumps(report))
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    label = args.label
    uid = os.getuid()
    # A durable launchd job has NO caller context (no CMUX_SURFACE_ID), so it
    # can't resolve a workspace UUID -> ref and would silently degrade to 'all',
    # broadening scope. Reject it up front while the caller can still pick a ref.
    if _WS_UUID_RE.match(args.workspace or ""):
        print(json.dumps({"ok": False,
                          "error": f"--workspace {args.workspace!r} is a workspace UUID; the "
                          "launchd job has no caller context to resolve it (it would degrade to "
                          "'all'). Pass a workspace:N ref, a workspace title, or 'all'."}))
        return 1
    logs = _state_root() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out_log = str(logs / "summarizer.out")
    err_log = str(logs / "summarizer.err")
    plist = render_plist(
        label=label, python=sys.executable, script=str(Path(__file__).resolve()),
        scope=args.workspace, interval=int(args.interval),
        out_log=out_log, err_log=err_log, run_at_load=args.run_at_load)
    path = _plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8")

    load_cmd = f"launchctl bootstrap gui/{uid} {path}"
    stop_cmd = f"launchctl bootout gui/{uid}/{label}"
    status_cmd = f"launchctl print gui/{uid}/{label}"
    loaded = False
    env_hint = (f"Put LLM_API_KEY (or DEEPSEEK_API_KEY) and OBSIDIAN in "
                f"{_state_root() / 'summarizer.env'} or ~/genesis/.env — launchd "
                "does not inherit your shell env.")
    if args.load:
        # idempotent: bootout an existing instance first (ignore failure), then
        # bootstrap the freshly-written plist.
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                       capture_output=True, text=True)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)],
                           capture_output=True, text=True)
        loaded = r.returncode == 0
        if not loaded:
            # Don't claim success: single-ownership depends on the job actually
            # being loaded. Surface the failure so the caller can fix it.
            print(json.dumps({
                "ok": False, "error": "launchctl bootstrap failed",
                "stderr": (r.stderr or "").strip()[:500], "returncode": r.returncode,
                "plist": str(path), "load_cmd": load_cmd, "status_cmd": status_cmd,
            }))
            return 1
    print(json.dumps({
        "ok": True,
        "plist": str(path),
        "loaded": loaded,
        "interval": int(args.interval),
        "load_cmd": load_cmd,
        "stop_cmd": stop_cmd,
        "status_cmd": status_cmd,  # `launchctl print ...` exits 0 iff loaded
        "note": env_hint,
    }))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="summarize", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("run", help="one summary pass: digest -> LLM -> worklog")
    rp.add_argument("--workspace", default=None,
                    help="workspace ref/title, or 'all'. Default: caller workspace.")
    rp.add_argument("--date", default=None,
                    help="YYYY-MM-DD: summarize exactly this day (no catch-up, no cap).")
    rp.add_argument("--max-days", type=int, default=1,
                    help="autonomous catch-up window in days back from today (default 1: "
                         "today + yesterday). Older backlog is deferred, not auto-run.")
    rp.add_argument("--catch-up", action="store_true",
                    help="lift the max-days cap and summarize ALL pending days "
                         "(run this after the user approves a >1-day backlog).")
    rp.set_defaults(func=cmd_run)

    ip = sub.add_parser("install", help="render + (optionally) load a launchd LaunchAgent")
    ip.add_argument("--interval", type=float, default=3600.0,
                    help="seconds between summary passes (StartInterval)")
    ip.add_argument("--workspace", default="all",
                    help="workspace scope baked into the job. Default: all.")
    ip.add_argument("--label", default=DEFAULT_LABEL, help="LaunchAgent label")
    ip.add_argument("--load", action="store_true",
                    help="also launchctl bootstrap the job now")
    ip.add_argument("--run-at-load", action="store_true",
                    help="also run once immediately when loaded")
    ip.set_defaults(func=cmd_install)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

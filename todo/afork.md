# afork — todo

_Last refreshed: 2026-07-28_

## Launch contract + legacy Claude name bridge (BUILT, branch `launch-contracts-01`, 2026-07-28)

Issue 01 of the `agent-model-effort-policy` PRD. Two contracts, both afork-side:

- **Generic legacy Claude naming bridge.** Exact-name lookup still runs first. Only when it
  misses does a *claude* agent name ending in `-agent` fall back to its suffixless stem. The
  handoff returns the canonical suffixless `agent` plus a `deprecation_warning`. It is a rule,
  not a per-role map — an exact `*-agent` port still wins, and codex gets no inverse alias.
  `resolve_agent_definition` now returns 4 fields (path, text, name, warning).
  Tests: `tests/test_legacy_bridge.py` (needs an isolated `$HOME` — port lookup searches the
  home base too, so the developer's own `~/.claude/agents` would otherwise satisfy the misses
  these tests depend on).
- **Launch contract sidecar.** *Every* launch — plain or custom — now gets a private workdir
  holding a 0600 `launch-contract.json`: attempt id, runtime, agent, model, effort, the
  exec-failure marker, and the adapter-owned regexes for a rejected model / runtime launch
  error. This is the runtime-knowledge boundary: tfork holds no runtime table and only matches
  what afork wrote. `Launch` is now a 4-field namedtuple (command, workdir, launch_contract,
  attempt_id) and the handoff carries `launch_contract` + `attempt_id`.
  The generated launcher uses `shopt -s execfail` and execs the intended runtime EXACTLY ONCE;
  the marker line after the exec is reachable only when that real exec failed. Plain mode has
  no launcher, so its `exec_marker` is `null` — the honest value, since nothing could print it.
  Tests: `tests/test_launch_contract.py`.

### Open follow-ups

- **The bridge is temporary.** Remove it after one release/upgrade cycle, per the accepted
  slice. Nothing currently enforces that deadline.
- **`aforklib/outcome.py` is byte-duplicated into `tforklib/`.** The two skills install as
  independent symlinked directories, so neither can import the other. A test in *both* suites
  asserts byte identity. If the skills ever gain a shared install root, collapse the duplicate.

## agentlens observability (BUILT, branch `agentlens-observe`, 2026-07-15)

Opt-in `--observe` / `--obs-tag k=v` wrap the built launch command with agentlens
(`lens run`), the observability tool at `~/genesis/observability`. Plain agents get
`env AGENTLENS_TAGS=… lens run -- <runtime argv>` (still one flat shlex-joined line);
custom agents get `export AGENTLENS_TAGS=…` + `exec lens run -- …` in the generated
launcher. Attribution rides the *env var* rather than agentlens's own `--tag` flags
because env wins on collision there — that is what keeps a whole nested spawn tree
attributed to the outer orchestrator's run (see the agentlens flux-integration doc).

**Fail-open, deliberately.** `--observe` with no `lens` on PATH does NOT fail: the
command is built unwrapped and the handoff carries `observed: false` + `obs_warning`.
Observability is not a security posture, so a missing observer must never block a
launch — the opposite of afork's fail-*closed* rule for unenforceable permission
postures. Those two rules coexist on purpose; don't "unify" them.

Handoff gains `observed` / `obs_tags` / `obs_warning` **only** when `--observe` was
passed, so existing consumers see a byte-identical object without it.

Open follow-ups:
- No `lens`-installed integration test — the suite pins `shutil.which` in both
  directions so it passes with or without agentlens on the machine. A real
  `lens run` smoke test would need agentlens installed in CI.
- Tag values are rejected if they contain a comma (AGENTLENS_TAGS is comma-separated
  and one would silently split a tag). If agentlens ever gains escaping, relax this.

## Home-dir agent resolution (BUILT, uncommitted, 2026-06-11)

Bare agent names now resolve in two locations, repo-local first then home:
`<cwd>/.<runtime>/agents/<name>` → `~/.<runtime>/agents/<name>`. This matches
Claude Code's own project-over-user agent precedence, so `afork claude reviewer`
picks up a globally-defined `~/.claude/agents/reviewer.md` even when the target
repo has no local one; a repo-local definition still shadows the global. Changed
`resolve.py` (`_agents_bases` + two-base search loop) and `errors.py`
(`err_port_not_found` now reports both searched paths). Dropped the post-`.resolve()`
`is_relative_to` containment check — the bare-name separator guard already makes
traversal impossible, and following legitimate symlinked home agents (common —
home agents are often symlinks into other repos) was wrongly rejected as an
escape. Skill prose (`agent`/`cwd` params, binary_contract, --cwd flow step)
updated in `.glyph` + `.md` lockstep. 3 new resolve tests; 48 pytest pass.

_Last refreshed: 2026-06-08 (entries below)_

`afork` is the agent-aware fork launcher: resolve an agent definition → map declared
permissions to a runtime-enforced launch command → fail closed → hand a `ready_to_fork`
JSON to the **tfork** skill (afork never forks). Designed with codex_lead (p2p); see the
design brief in that thread.

## v2 — unified front-door (BUILT + reviewed, uncommitted, 2026-06-08)

_Status: implemented, code-reviewed (codex_reviewer, 2 rounds, signed off), verified
(34 pytest pass, codex sandbox proof 5/5, glyph validates). Changes live in the
working tree, not yet committed._

Lead overrides on the sub-agent build: (1) non-string codex `sandbox_mode` →
`port_unparsable` (non-overridable), not `unenforceable` — a broken file must not be
bypassable with --allow-unenforced; (2) plain-agent handoff `note` no longer claims a
persona was injected; (3) pi binary → bare `pi` after the user removed the `pip install`
alias.

Review fixes (codex_reviewer): (a) persona-injection shape now driven by the adapter's
declared `style` (`config_cat`/`flag_cat`/`flag_path`) in launch.py — no more
`flag.startswith("--")` sniffing; pi's path style passes the payload path, not `$(cat)`;
(b) proof now checks workspace-write's restrictive half (outside-workspace write blocked,
with a $HOME-writability preflight/SKIP); (c) new test executes the generated launcher
with hostile persona + model/effort against a stub runtime, asserting nothing injects.


Design locked: `$OBSIDIAN/plans/afork-v2-design-2026-06-08.md`. afork becomes the front
door for **plain** agents too, not just definition-backed ones. Key changes:

- **CLI:** `afork <runtime> [agent] [--permission P] [--model M] [--effort E] …`.
  `runtime` is positional-1 (required); `agent` is optional (omit → plain agent).
  `--runtime` flag removed.
- **Agnostic params:** skill exposes `permission` / `model` / `effort` concepts; the
  adapter maps them to per-runtime flags (codex `-c …` vs claude `--model`/`--effort`).
- **Default posture `none` (yolo):** maps to `--dangerously-bypass-approvals-and-sandbox`
  (codex) / `--dangerously-skip-permissions` (claude). Needs no enforcement → never
  fails closed. Restricted postures (read-only/workspace-write) keep the fail-closed gate.
- **Two axes:** persona (prompt/developer-level, fine) vs permission (must be enforced).
- **Posture precedence:** flag → definition's declared sandbox → default none.
- **No-sandbox codex definition** now defaults to none (was `missing_sandbox_mode`).
- **claude now launchable** for `none` (its `can_launch=False` was only about read-only).
  Persona injected via `--append-system-prompt "$(cat payload)"` (temp-launcher trick).
- **Runtimes:** codex, claude, pi, antigravity. Restricted modes for claude/pi/antigravity
  deferred (fail closed) this round.
  - **pi** (researched by `pi_setup`, live-tested v0.78.1): INVERTED — yolo by default,
    NO bypass flag, so `none` = no flag. Read-only = `--tools read,grep,find,ls` (harness;
    no bash tool = no write-leak; deferred). Binary = bare `pi` (user removed the old
    `pip install` alias 2026-06-08). model `--model`/`--provider`; effort
    `--thinking`; persona `--append-system-prompt <file>` (takes a path). **No agents-dir**
    → pi is plain-only this round (custom-agent request errors).
  - **antigravity**: installed (`~/.antigravity/...`) but flags not researched yet → stub
    `runtime_unsupported` for now; research is the immediate follow-up (fork an agent like
    pi_setup, or read its `--help`).
- Plain-agent defaults: codex effort `xhigh`; claude model `opus` effort `high`; pi/ag TBD.

## Shipped (v1 MVP)

- Codex adapter: parse `.codex/agents/<name>.toml`, enforce `sandbox_mode` via the codex
  `--sandbox` flag, inject `developer_instructions` at developer level via a 0600 temp
  payload + generated `launch.sh` (`-c developer_instructions="$(cat …)"`), so no multiline
  content crosses the agent→tfork shell boundary.
- Fail-closed gate: declared restriction the adapter can't enforce → `unenforceable` refusal
  unless `--allow-unenforced`.
- Claude adapter: stub, fails closed (no verified enforced read-only mechanism yet).
- Ports resolve relative to `--cwd` (the target repo), not the skill repo.
- Proof: `tests/proof_codex_readonly.sh` — deterministic, no-LLM write probe via
  `codex sandbox`, showing read-only blocks writes and workspace-write allows them.
- Unit tests: `tests/` (resolve, codex adapter, fail-closed gate, CLI). `python3 -m pytest`.

## Open / follow-ups

- **Claude adapter enforcement research.** Determine whether Claude Code has a *runtime-
  enforced* read-only mode (permission-mode, settings.json `permissions.deny`, sandbox).
  Until proven, claude stays fail-closed. (codex_lead Q3: deferred out of v1 deliberately.)
- **Antigravity / Pi adapters.** Placeholder `runtime_unsupported` only. Wire real launch +
  permission mapping once their models are known.
- **Codex instruction-injection fallback.** Canonical path is `-c developer_instructions=…`
  (proven: codex renders it as a developer message; `-c` parses value as TOML, falls back to
  raw string literal per `codex --help`). If codex ever drops `developer_instructions`,
  fall back to a temp profile (`-p $CODEX_HOME/<name>.config.toml`) or `--permissions-profile`.
- **`codex exec` one-shot mode.** v1 targets long-lived interactive `codex` panes. A
  non-interactive `exec` target could be a later `--mode exec` option.
- **Retire/thin aliases.** Per the brief, legacy fork aliases should become thin wrappers
  around `afork` so none bypass the port config + permission mapping. Not yet done.
- **Glyph red-flags emission.** The `### Red Flags` section is hand-mirrored into SKILL.md
  (same as tfork) because the compile pipeline doesn't emit it yet.

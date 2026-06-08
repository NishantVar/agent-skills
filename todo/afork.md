# afork — todo

_Last refreshed: 2026-06-08_

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

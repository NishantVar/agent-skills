---
name: afork
description: 'Front door for forking any coding agent (plain or definition-backed) across runtimes (codex, claude, pi) into a cmux pane: build a launch command and hand it to tfork. Agnostic to runtime flags; fails closed only when a declared restriction can''t be runtime-enforced. Never forks.'
---

## Parameters

- **runtime**:
  The coding-agent runtime, REQUIRED, positional-1: `codex`, `claude`, or `pi` (all launch plain + permission none); `antigravity` is unsupported this round.
  Required.
- **agent**:
  Optional agent definition to launch: either a bare name resolved under <cwd>/.<runtime>/agents/ then ~/.<runtime>/agents/ — repo-local wins, home is the fallback (e.g. `reviewer` -> .codex/agents/reviewer.toml or ~/.codex/agents/reviewer.toml; `systems-designer-agent` -> .claude/agents/systems-designer-agent.md; `afork claude reviewer` picks up ~/.claude/agents/reviewer.md when the repo has no local one) — or an explicit definition path (e.g. `/repo/.codex/agents/reviewer.toml`). Path form loads that file directly and uses its filename stem as the agent name; --cwd still controls only where the agent runs. Omit for a plain agent (default params). pi has no agents dir — a custom agent there errors. Pass the name the user gave you: a legacy Claude name ending in `-agent` that no longer resolves is bridged automatically to its suffixless port, and the handoff reports the canonical name plus a deprecation warning.
  Default: none.
- **model**:
  Agnostic model; falls back to the definition's declaration, else the runtime default (claude `opus`; codex/pi none). Accepts a combined spec with a trailing effort token — `fable max` splits into model `fable` + effort `max` (an explicit --effort wins). A model name right after the runtime (e.g. `claude opus`, `claude fable max`) is this parameter, not an agent definition.
  Default: none.
- **effort**:
  Agnostic reasoning effort; falls back to the definition's declaration, else the runtime default (codex `xhigh`; claude `high`).
  Default: none.
- **title**:
  cmux tab title for the forked pane, for p2p routing. Defaults to the agent name, else the runtime. Pass snake_case (e.g. reviewer_agent).
  Default: none.
- **cwd**:
  The target repo where the agent runs. Bare-name agent ports resolve relative to this (NOT the skill repo) first, then fall back to ~/.<runtime>/agents/. Explicit definition paths ignore this for resolution. Defaults to the caller's cwd.
  Default: none.
- **placement**: Where the new pane opens: right, left, top, or bottom. Forwarded to tfork. Default: none.
- **allow_unenforced**:
  Explicitly proceed when a declared restriction cannot be runtime-enforced. Off by default — afork fails closed. Pass only on explicit user instruction to accept an unenforced launch.
  Default: none.
- **observe**:
  Wrap the launch command with agentlens (`lens run`) so the forked agent's prompts and token usage are captured. Off by default. Fail-open: if the `lens` binary is not on PATH the command is still built, just unwrapped, and the handoff carries an obs_warning.
  Default: none.
- **obs_tag**:
  Attribution tag for the observed session, repeatable: `--obs-tag agent=reviewer --obs-tag run=42`. Requires --observe (tags without it are a bad_arguments error); --observe with no tags is fine — capture without attribution. Keys are free-form; the flux convention is agent / run / stage / project.
  Default: none.

## Context

- **binary-contract**

  afork.py is deterministic and self-contained, and is agnostic to runtime flag names — a per-runtime adapter owns the mapping. It picks the runtime adapter, decides plain (no agent) vs custom (definition-backed) mode, resolves a bare agent name under --cwd then ~/.<runtime>/agents/ (repo-local first) or an explicit definition path directly, bridges legacy Claude names generically (exact-name lookup always runs first; only when it misses does a Claude name ending in `-agent` fall back to its suffixless stem, so an exact `*-agent` port still wins and codex gets no inverse alias — the bridge is a rule, not a per-role map, and it is removed after one release/upgrade cycle), resolves the permission posture from the definition's declared sandbox (else default none) — the skill never passes a posture; the port file is the only source — checks the adapter can runtime-enforce a restricted posture (else fails closed), resolves model/effort (arg > definition > runtime default; a combined --model spec like `fable max` splits into model + trailing effort token, an explicit --effort winning), and builds the launch command. In explicit-path mode, --cwd controls only where the agent runs; the handoff agent/title default uses the definition filename stem. Plain agents get a flat shell-quoted argv (no temp launcher). Custom agents with a persona get a 0600 payload + generated executable launcher path so multiline persona never crosses the agent->tfork shell boundary; the launcher enforces the posture via flags and injects the persona at system/developer level, and it attempts the intended runtime exactly ONCE — it never retries and never falls back to a second runtime, so the contract-bound failure marker it prints is reachable only when that one real exec failed. Every launch, plain or custom, also gets a 0600 launch-contract sidecar in afork's private workdir recording the attempt id, runtime, agent, model, effort, that marker, and the adapter-owned patterns for a rejected model or a runtime launch error. This is where all runtime knowledge stays: tfork holds none and only matches what afork wrote down. With --observe it also wraps the launch with agentlens — plain agents become `env AGENTLENS_TAGS=… lens run -- <runtime argv>` (the env prefix omitted when there are no tags), and custom launchers export AGENTLENS_TAGS and `exec lens run -- …`. That wrap is fail-open: if the `lens` binary is not on PATH the command is built UNWRAPPED and the handoff explains it, because a missing observer must never block a launch. It always prints exactly one JSON object. On success: a `ready_to_fork` handoff carrying command, handoff_skill ("tfork"), runtime, agent (null when plain), posture, enforced (bool; `none` is always enforced — nothing to enforce), title, cwd, type ("agent"), placement, workdir (afork's private directory for this attempt), launch_contract (the sidecar path to hand tfork as --launch-contract), attempt_id, and an agent_instruction telling you exactly how to call tfork. When the legacy Claude naming bridge fired it also carries deprecation_warning, and `agent` is the CANONICAL suffixless name — record and forward that one, not what was typed. Only when --observe was passed it also carries observed (bool — true only when the command was really wrapped), obs_tags (the requested attribution dict, or null when none were given), and, on the fail-open path, obs_warning (one line explaining the launch is unobserved). On failure: ok false and a code: `port_not_found` (missing bare-name or explicit-path definition), `unenforceable` (fail-closed refusal — a declared restriction the adapter can't enforce), `custom_unsupported` (custom agent requested for a runtime with no agents dir, e.g. pi), `runtime_unsupported` (no adapter, e.g. antigravity), `bad_arguments`, or `port_unparsable`. Each failure carries human_message and agent_instruction.

- **launch-outcome-contract**

  Every launch afork prepares is ultimately reported by tfork as a versioned `launch_outcome` object, and afork's 0600 launch-contract sidecar is the only thing that makes its runtime-specific values reachable at all. Its fields are exactly: version, state, reason_code, evidence_code, start_sentinel_seen, end_sentinel_seen, exit_status, foreground.

  `state` is one of: `started` | `prework_failure` | `unknown`.
  `reason_code` is null unless state is prework_failure, where it is one of: `runtime_unavailable` | `model_unavailable` | `launch_failed`.
  `evidence_code` is one of: `agent_started`, `runtime_exec_failed`, `model_rejected`, `runtime_launch_error`, `pane_creation_failed`, `command_delivery_absent`, `unrecognized_exit`, `missing_start_sentinel`, `observation_timeout`, `shell_foreground`, `missing_foreground`, `delivery_ambiguous`, `contradictory_evidence`.

  afork owns the runtime-specific half of that vocabulary, and tfork holds none of it. `runtime_exec_failed` is reachable only when the generated launcher's one real exec failed and printed the marker afork recorded in the sidecar; `model_rejected` and `runtime_launch_error` are reachable only when adapter-owned patterns from that same sidecar match the pane. Drop --launch-contract and none of the three can ever be produced — every ambiguous launch reports `unknown` instead, which is NOT a failure and licenses no retry or fallback. That is why the handoff's launch_contract path must be forwarded to tfork verbatim on every fork, not only when something looks wrong.

## Constraints

- **Must:** A declared permission restriction (read-only / workspace-write) that the runtime adapter cannot prove it enforces is a refusal, not a best effort. afork refuses to launch a restricted posture it cannot enforce unless the user explicitly passes --allow-unenforced. The default posture `none` (yolo) has nothing to enforce and never fails closed. The binary owns this decision — never second-guess an `unenforceable` handoff into a launch.
- **Must avoid:** treating a prompt-level or persona 'please be read-only' as if it enforced the restriction. Only runtime mechanisms (e.g. the codex --sandbox flag) count as enforcement; prose does not. Persona injection is a role, not a security boundary.
- **Require:** afork prepares the command but never forks. On a ready_to_fork handoff, load the tfork skill and fork the handoff's `command` verbatim after the -- separator, passing the carried --title, --cwd, --type agent, --placement, and --launch-contract. afork.py must not invoke tfork itself — the calling agent bridges the two skills.
- **Require:** Infer only the front-door parameters and pass them through. Never parse agent definitions, map postures to runtime flags, build launch commands, or decide enforceability in the skill — the binary's adapter owns all of it. Do not hand-build runtime invocations or edit the command afork returns.

## Steps

1. Extract the parameters from the user's request — {runtime}, {agent}, {model}, {effort}, {title}, {cwd}, {placement} — and forward them as-is. Do not invent values; use the defaults when the user did not name one. {runtime} is required; omit {agent} for a plain agent.
2. Begin the invocation as: python3 <skill-dir>/afork.py {runtime}. Run the binary explicitly with python3, and resolve <skill-dir> to the absolute path of the directory this SKILL.md was loaded from — afork.py sits in that same directory. On macOS, `/usr/bin/python3` may be Python 3.9 and fail with `ModuleNotFoundError: No module named 'tomllib'`; if that happens, rerun the same command with `python3.11` (or another Python >=3.11) rather than treating afork as broken.
3. Decide whether the user named a specific agent definition applies and, if so:
   a. Append {agent} as the second positional argument, right after {runtime}.
4. Decide whether the user named a model applies and, if so:
   a. Insert --model {model} into the invocation.
5. Decide whether the user named an effort level applies and, if so:
   a. Insert --effort {effort} into the invocation.
6. Decide whether the user named a title applies and, if so:
   a. Insert --title {title} into the invocation.
7. Decide whether the user named a target repo or working directory applies and, if so:
   a. Insert --cwd {cwd} into the invocation. Bare-name ports resolve relative to this directory then fall back to ~/.<runtime>/agents/; explicit definition paths do not.
8. Decide whether the user named a placement applies and, if so:
   a. Insert --placement {placement} into the invocation.
9. Decide whether the user has explicitly accepted an unenforced launch for a runtime that cannot enforce the declared posture applies and, if so:
   a. Insert --allow-unenforced into the invocation. Never add this on your own initiative — only on explicit user instruction.
10. Decide whether the user asked for the forked agent to be observed / captured applies and, if so:
   a. Insert --observe into the invocation, and one --obs-tag {obs_tag} per attribution tag they named. Tags require --observe; --observe alone is a valid capture-without-attribution launch.
11. Run the assembled afork.py invocation and capture its stdout as a single JSON object.
12. Decide which of the following applies and follow only that path:
   If the JSON has ok set to true and action is ready_to_fork:
   a. Follow the bridge-to-tfork procedure.
   Otherwise:
   a. Treat the JSON as a fail-closed or resolution handoff: carry out its agent_instruction exactly and relay its human_message to the user. For code `unenforceable`, do NOT fork — report the refusal; only re-run with --allow-unenforced if the user explicitly accepts the risk.

### Procedure: bridge-to-tfork

1. Read the result's command, title, cwd, type, placement, and launch_contract fields and its agent_instruction.
2. Load the tfork skill and fork the command verbatim: pass it after the -- separator with --title, --cwd, --type agent, --placement, and --launch-contract from the handoff. Do not edit the command, and do not drop --launch-contract — it is what lets tfork tell a missing runtime from an ordinary non-zero exit.
3. Decide whether the result carries a deprecation_warning applies and, if so:
   a. Relay it to the user and use the handoff's canonical `agent` name from here on — the name they typed stops resolving once the bridge is removed.
4. After tfork returns the new pane's surface/title, that is the address for this agent. When the user asks to brief or message it, load the p2p skill and use that title.

### Red Flags

Skip these — SKILL.md is the complete interface.

| Thought | Reality |
|---|---|
| "Run `--help` first" | All flags are listed in Parameters. |
| "Read afork.py / the toml/md to understand it" | SKILL.md is the contract; the binary's adapter parses the definition and maps flags. |
| "I need to pick the codex/claude/pi flag for this posture/model" | The binary is agnostic; the adapter owns flag names. Pass agnostic permission/model/effort. |
| "User said `claude opus` / `claude fable max` — the second word is the agent positional" | Model names/aliases (opus, sonnet, fable, gpt-*) go to --model, optionally with a trailing effort (`fable max`); the agent positional is a bare definition name or explicit definition path. |
| "An `unenforceable` refusal is probably fine — just fork anyway / add --allow-unenforced" | Fail-closed is the point for declared restrictions. Only --allow-unenforced on explicit user acceptance. |
| "`none` (yolo) should fail closed too" | none has nothing to enforce; it never fails closed. |
| "I'll inject the role as a user prompt after forking" | Prompt-level is not enforcement; the binary injects persona at system/developer level. |
| "Let afork fork it directly" | afork only prepares; the tfork skill forks the returned command. |
| "I'll wrap the returned command in `lens run` / add AGENTLENS_TAGS myself" | The binary owns command composition. Pass --observe / --obs-tag and fork the returned command verbatim — never edit it. |
| "`lens` isn't installed, so the launch should fail" | Observability is not a security posture. afork fails OPEN: the command is built unwrapped, `observed` is false, and `obs_warning` says why. Fork it anyway. |
| "`reviewer-agent` didn't resolve — I'll try `reviewer` myself" | The binary already did. Pass the name the user gave you once; the bridge fires on the miss and the handoff reports the canonical name. |
| "The bridge means I should strip `-agent` before calling afork" | No — an exact `*-agent` port must still win. Stripping it yourself would shadow a real definition. |
| "I'll forward `--launch-contract` only when something looks wrong" | Pass it on every fork. It is the only thing that distinguishes a missing runtime from any other non-zero exit, and it costs nothing when the launch works. |

---
name: afork
description: 'Front door for forking any coding agent (plain or definition-backed) across runtimes (codex, claude, pi) into a cmux pane: build a launch command and hand it to tfork. Agnostic to runtime flags; fails closed only when a declared restriction can''t be runtime-enforced. Never forks.'
---

## Parameters

- **runtime**:
  The coding-agent runtime, REQUIRED, positional-1: `codex`, `claude`, or `pi` (all launch plain + permission none); `antigravity` is unsupported this round.
  Required.
- **agent**:
  Optional agent definition to launch, resolved under <cwd>/.<runtime>/agents/ (e.g. `reviewer` -> .codex/agents/reviewer.toml, `systems-designer-agent` -> .claude/agents/systems-designer-agent.md). Omit for a plain agent (default params). pi has no agents dir — a custom agent there errors.
  Default: none.
- **permission**:
  Agnostic permission posture: `none` (yolo, default) | `read-only` | `workspace-write`. Unset resolves to the definition's declaration, else none. Restricted postures fail closed on runtimes that can't enforce them (claude/pi this round).
  Default: none.
- **model**: Agnostic model; falls back to the definition's declaration, else the runtime default (claude `opus`; codex/pi none). Accepts a combined spec with a trailing effort token — `fable max` splits into model `fable` + effort `max` (an explicit --effort wins). A model name right after the runtime (e.g. `claude opus`, `claude fable max`) is this parameter, not an agent definition. Default: none.
- **effort**:
  Agnostic reasoning effort; falls back to the definition's declaration, else the runtime default (codex `xhigh`; claude `high`).
  Default: none.
- **title**:
  cmux tab title for the forked pane, for p2p routing. Defaults to the agent name, else the runtime. Pass snake_case (e.g. reviewer_agent).
  Default: none.
- **cwd**:
  The target repo whose agent ports are resolved and where the agent runs. Defaults to the caller's cwd. Ports resolve relative to this, NOT the skill repo.
  Default: none.
- **placement**: Where the new pane opens: right, left, top, or bottom. Forwarded to tfork. Default: none.
- **allow_unenforced**:
  Explicitly proceed when a declared restriction cannot be runtime-enforced. Off by default — afork fails closed. Pass only on explicit user instruction to accept an unenforced launch.
  Default: none.

## Context

- **binary-contract**

  afork.py is deterministic and self-contained, and is agnostic to runtime flag names — a per-runtime adapter owns the mapping. It picks the runtime adapter, decides plain (no agent) vs custom (definition-backed) mode, resolves the permission posture by precedence (--permission > definition's declared sandbox > default none), checks the adapter can runtime-enforce a restricted posture (else fails closed), resolves model/effort (arg > definition > runtime default; a combined --model spec like `fable max` splits into model + trailing effort token, an explicit --effort winning), and builds the launch command. Plain agents get a flat shell-quoted argv (no temp launcher). Custom agents with a persona get a 0600 payload + generated `bash <launcher>` so multiline persona never crosses the agent->tfork shell boundary; the launcher enforces the posture via flags and injects the persona at system/developer level. It always prints exactly one JSON object. On success: a `ready_to_fork` handoff carrying command, handoff_skill ("tfork"), runtime, agent (null when plain), posture, enforced (bool; `none` is always enforced — nothing to enforce), title, cwd, type ("agent"), placement, workdir (null when plain), and an agent_instruction telling you exactly how to call tfork. On failure: ok false and a code: `port_not_found` (no definition under --cwd), `unenforceable` (fail-closed refusal — a declared restriction the adapter can't enforce), `custom_unsupported` (custom agent requested for a runtime with no agents dir, e.g. pi), `runtime_unsupported` (no adapter, e.g. antigravity), `bad_arguments`, or `port_unparsable`. Each failure carries human_message and agent_instruction.

## Constraints

- **Must:** A declared permission restriction (read-only / workspace-write) that the runtime adapter cannot prove it enforces is a refusal, not a best effort. afork refuses to launch a restricted posture it cannot enforce unless the user explicitly passes --allow-unenforced. The default posture `none` (yolo) has nothing to enforce and never fails closed. The binary owns this decision — never second-guess an `unenforceable` handoff into a launch.
- **Must avoid:** treating a prompt-level or persona 'please be read-only' as if it enforced the restriction. Only runtime mechanisms (e.g. the codex --sandbox flag) count as enforcement; prose does not. Persona injection is a role, not a security boundary.
- **Require:** afork prepares the command but never forks. On a ready_to_fork handoff, load the tfork skill and fork the handoff's `command` verbatim after the -- separator, passing the carried --title, --cwd, --type agent, and --placement. afork.py must not invoke tfork itself — the calling agent bridges the two skills.
- **Require:** Infer only the front-door parameters and pass them through. Never parse agent definitions, map postures to runtime flags, build launch commands, or decide enforceability in the skill — the binary's adapter owns all of it. Do not hand-build runtime invocations or edit the command afork returns.

## Steps

1. Extract the parameters from the user's request — {runtime}, {agent}, {permission}, {model}, {effort}, {title}, {cwd}, {placement} — and forward them as-is. Do not invent values; use the defaults when the user did not name one. {runtime} is required; omit {agent} for a plain agent.
2. Begin the invocation as: python3 <skill-dir>/afork.py {runtime}. Run the binary explicitly with python3, and resolve <skill-dir> to the absolute path of the directory this SKILL.md was loaded from — afork.py sits in that same directory.
3. Decide whether the user named a specific agent definition applies and, if so:
   a. Append {agent} as the second positional argument, right after {runtime}.
4. Decide whether the user named a permission posture applies and, if so:
   a. Insert --permission {permission} into the invocation.
5. Decide whether the user named a model applies and, if so:
   a. Insert --model {model} into the invocation.
6. Decide whether the user named an effort level applies and, if so:
   a. Insert --effort {effort} into the invocation.
7. Decide whether the user named a title applies and, if so:
   a. Insert --title {title} into the invocation.
8. Decide whether the user named a target repo or working directory applies and, if so:
   a. Insert --cwd {cwd} into the invocation. Ports resolve relative to this directory.
9. Decide whether the user named a placement applies and, if so:
   a. Insert --placement {placement} into the invocation.
10. Decide whether the user has explicitly accepted an unenforced launch for a runtime that cannot enforce the declared posture applies and, if so:
   a. Insert --allow-unenforced into the invocation. Never add this on your own initiative — only on explicit user instruction.
11. Run the assembled afork.py invocation and capture its stdout as a single JSON object.
12. Decide which of the following applies and follow only that path:
   If the JSON has ok set to true and action is ready_to_fork:
   a. Read the result's command, title, cwd, type, and placement fields and its agent_instruction. Load the tfork skill and fork the command verbatim: pass it after the -- separator with --title, --cwd, --type agent, and --placement from the handoff. Do not edit the command. After tfork returns the new pane's surface/title, that is the address for this agent. When the user asks to brief or message it, load the p2p skill and use that title.
   Otherwise:
   a. Treat the JSON as a fail-closed or resolution handoff: carry out its agent_instruction exactly and relay its human_message to the user. For code `unenforceable`, do NOT fork — report the refusal; only re-run with --allow-unenforced if the user explicitly accepts the risk.

### Red Flags

Skip these — SKILL.md is the complete interface.

| Thought | Reality |
|---|---|
| "Run `--help` first" | All flags are listed in Parameters. |
| "Read afork.py / the toml/md to understand it" | SKILL.md is the contract; the binary's adapter parses the definition and maps flags. |
| "I need to pick the codex/claude/pi flag for this posture/model" | The binary is agnostic; the adapter owns flag names. Pass agnostic permission/model/effort. |
| "User said `claude opus` / `claude fable max` — the second word is the agent positional" | Model names/aliases (opus, sonnet, fable, gpt-*) go to --model, optionally with a trailing effort (`fable max`); the agent positional is a definition file under .<runtime>/agents/. |
| "An `unenforceable` refusal is probably fine — just fork anyway / add --allow-unenforced" | Fail-closed is the point for declared restrictions. Only --allow-unenforced on explicit user acceptance. |
| "`none` (yolo) should fail closed too" | none has nothing to enforce; it never fails closed. |
| "I'll inject the role as a user prompt after forking" | Prompt-level is not enforcement; the binary injects persona at system/developer level. |
| "Let afork fork it directly" | afork only prepares; the tfork skill forks the returned command. |


---
name: cmux_status
description: 'Produce a static HTML+JSON ops dashboard of local cmux state, plus best-effort cross-workspace work-theme grouping.'
---

## Parameters

- **no_summarize**: Skip step 2; helpers still render the dashboard, agents lose summaries. Default: false.
- **no_themes**: Skip steps 3-4; the Work-themes UI section is omitted. Default: false.
- **no_open**: Write HTML/JSON but do not open the browser. Default: false.
- **rescan**: Invalidate the repo-discovery cache before running. Default: false.
- **config**: Optional path to a config TOML; defaults to ~/.config/cmux-observability/config.toml. Default: none.

## Context

- **json-contract**

  The helper exposes the JSON contract via five subcommands:
  - collect: returns {run_id, pending_summaries: [...], snapshot_preview}
  - record-summaries: stdin {summaries: [{surface_ref, summary, state_hint, needs_input_reason, confidence}]}
  - themes-payload: returns {payload: {surfaces: [{surface_ref, workspace_ref, workspace_title, title, cwd, type, state, summary}]} | null, omit: bool, reason?: string}. When omit is true, skip authoring themes and proceed to finalize.
  - record-themes: stdin {themes: [{label, member_refs, why, confidence}]}
  - finalize: returns {ok, html, json, failures}
  Each surface's scrollback in pending_summaries is already redacted; the original secrets never reach this agent.

## Constraints

- **Must:** This skill has no Anthropic, OpenAI, or other provider SDK dependency. There is no API key handling and no LLM client. Judgement work (summaries and theme grouping) is authored by the calling coding agent (you), exchanged with the helper as JSON over stdin/stdout.
- **Require:** All inputs and outputs are local: cmux CLI, git CLI, ~/.local/share/cmux-observability/, ~/.local/state/cmux-observability/, ~/.config/cmux-observability/. No network calls. No remote endpoints.

## Steps

1. Resolve <skill-dir> to the absolute directory this SKILL.md was loaded from — the python package lives at <skill-dir>/cmux_observability and the working directory is the user's project, not the skill directory, so a bare module path will not resolve. Resolve the Python interpreter at runtime (first match wins; required Python >= 3.11 with jinja2): for cand in python3 python; do if "$cand" -c 'import sys, jinja2; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then PY="$cand"; break; fi; done; [ -n "$PY" ] || { echo 'no suitable python (need >=3.11 with jinja2)' >&2; exit 1; }. Build the invocation prefix: PYTHONPATH=<skill-dir> "$PY" -m cmux_observability.cli. Use this prefix for every subcommand below. Algorithm is 'first match wins'; Python >= 3.11 is the minimum (matches the plan's stated tech stack).
2. Run: <prefix> collect (append --rescan if {rescan}, append --config {config} if provided). Capture stdout as a single JSON object; extract run_id, pending_summaries, and snapshot_preview.
3. Decide whether pending_summaries is non-empty and not {no_summarize} applies and, if so:
   a. For each entry in pending_summaries, author a Summary object in JSON: surface_ref echoed back, summary (one line <=140 chars, present tense), state_hint (running | needs_input | idle | unknown), needs_input_reason (string or null), confidence (0..1). Cross-check the cmux_state hint and let cmux win on disagreement; the helper records the disagreement non-fatally. Build a single JSON document {"summaries": [...]} and pipe it to: <prefix> record-summaries --run-id <id> (append --config {config} if provided).
4. Decide whether not {no_themes} applies and, if so:
   a. Run: <prefix> themes-payload --run-id <id> (append --config {config} if provided). If the helper returns {payload: null, omit: true, reason: ...}, write an empty themes list and skip record-themes; proceed straight to finalize — guardrails (sparse summaries, summaries disabled, or low confidence) already collapsed the section. Otherwise group surfaces into best-effort cross-workspace themes using titles, cwds, types, states, and summaries. Output JSON {"themes": [{label, member_refs, why, confidence}, ...]} and pipe to: <prefix> record-themes --run-id <id> (append --config {config} if provided). Return an empty themes list when signal is weak — the helper will omit the section.
5. Run: <prefix> finalize --run-id <id> (append --no-open if {no_open}, append --config {config} if provided). The helper persists, renders HTML+JSON, opens the browser by default, and emits the final envelope on stdout. Surface that envelope to the user.


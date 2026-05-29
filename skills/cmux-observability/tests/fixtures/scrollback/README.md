# Scrollback fixtures — v1.2 state classifier

Fixtures captured from `cmux read-screen` and used by
`tests/test_state_classifier.py` to drive the deterministic state classifier
(`state_from_scrollback(tail, kind)`).

## Filename convention

```
<kind>_<state>__<note>.txt
```

Examples:
- `claude_code_needs_input__empty_prompt.txt`
- `claude_code_needs_input__confirm_card.txt`
- `claude_code_running__late_turn.txt`
- `codex_running__worked_for.txt`
- `generic_unknown__plain_bash.txt`
- `generic_needs_input__are_you_sure.txt`

Fields:
- `kind` ∈ {`claude_code`, `codex`, `gemini`, `generic`}
- `state` ∈ {`needs_input`, `running`, `idle`, `unknown`}
- `<note>` — freeform short slug describing the variant (snake_case)

`kind=generic` is the fallback bucket for non-agent shells, plain TUIs
(vim/less/tail-f), and any prompt the kind-specific patterns don't recognize.
The test passes `kind=None` to the classifier for `generic` rows.

## Capture procedure

```
cmux read-screen \
  --workspace <workspace_ref> \
  --surface <surface_ref> \
  --scrollback \
  --lines 150 \
  > tests/fixtures/scrollback/<kind>_<state>__<note>.txt
```

Both `--workspace` and `--surface` are required (cmux 0.64.10+ rejects
surface-only invocations with `invalid_params: Surface is not a terminal`);
`--scrollback --lines 150` matches the wrapper default in
`cmux_observability/collector/cmux.py:read_screen`. Capture the surface in
the state you want to encode. Verify visually that the file's last ~20 lines
match the intended `(kind, state)` before committing.

## Spec inventory target (verbatim from the v1.2 spec)

Source the fixtures. Run the capture command above (with
`--workspace <workspace_ref> --surface <surface_ref> --scrollback --lines 150`)
on the user's live machine — there are 29 candidates today. Capture at least:

- 2× claude_code/needs_input (one empty-prompt, one confirm-card)
- 2× claude_code/running (one early, one late in a turn)
- 1× claude_code/idle
- 1× codex/needs_input
- 1× codex/running
- 1× generic/needs_input (a non-agent shell prompt with `Are you sure`)
- 1× generic running (plain shell idle prompt — must classify as `unknown` not
  `idle`)

Plus ≥3 negative fixtures (plain `bash` prompt, plain `vim`/`less` view, plain
`tail -f` log) — all must classify as `("unknown", *)`.

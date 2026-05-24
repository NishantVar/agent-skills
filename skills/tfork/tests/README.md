# tfork tests

## Unit tests — no cmux session required

```bash
python3 -m pytest tests -v --ignore=tests/test_e2e.py
```

Covers type resolution, registry I/O, the result/handoff JSON contracts, the
fork orchestration (against the in-memory `FakeTerminal`), CLI argument
parsing, and the front-door/binary contract.

## End-to-end tests — live cmux session required

```bash
python3 -m pytest tests/test_e2e.py -v
```

Exercises `CmuxTerminal` and surface resolution against the real cmux CLI.
Skipped automatically when not running inside cmux. Run it from inside each
agent runtime (Claude Code, Codex, Gemini) to cover the cross-runtime
surface-resolution matrix.

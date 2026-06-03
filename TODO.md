# Agent Skills TODO

## P2P / Delegated-Agent Trust

- Add a P2P/B2B-level convention for delegated-agent trust:
  - After sending a clear task to the owning agent, the lead should wait for
    the agent's completion report instead of polling its screen, process state,
    or file timestamps.
  - Status checks are appropriate only when the user asks, the delegated agent
    asks for help or review, the agent reports completion and outputs need
    review, a concrete failure signal appears, or an agreed timeout passes.
  - If a timeout passes, ask the same agent for a brief status first. Do not
    spawn a replacement or inspect aggressively unless the agent remains
    unreachable or a real conflict/failure is visible.
  - Core principle: handle concrete failure signals, not anxiety.

## P2P / tfork — Codex pane delivery reliability (bug)

- Fix the underlying delivery bug so a p2p `send` to a freshly-forked Codex
  pane (`tfork coxn`) is reliable — i.e. `ok:true` genuinely means the brief
  landed and was submitted, not just that the buffer was pasted.
  - Symptom seen in practice: forking `coxn` and immediately briefing it via
    p2p returned `ok:true`, but the Codex TUI was still booting, so the paste
    was lost and the pane sat idle at the welcome screen with empty input. The
    `tfork` result had already signalled this with `verified:false` /
    "start sentinel not observed".
  - The fix belongs in the tooling, not in a manual workaround. Requiring the
    lead to screen-read every spawn to confirm receipt contradicts the
    Delegated-Agent Trust principle above (don't poll; trust `ok:true`). So make
    the delivery path itself trustworthy:
    - p2p/tfork should gate (or retry) delivery on the Codex pane being ready to
      receive — e.g. wait for the prompt / readiness signal before pasting, and
      ensure the submit keystroke lands — rather than pasting into a booting TUI.
    - Consider surfacing a not-yet-delivered / not-ready status from `send`
      instead of `ok:true` when the target pane is still initializing, so the
      caller can rely on `ok:true == delivered`.
  - Claude panes (`tfork cx`) land first-try in practice; the race is
    Codex-specific, but the contract (`ok:true` == delivered) should hold for
    both.

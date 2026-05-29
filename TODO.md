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

---
name: cmux_watchdog
description: 'Monitor cmux panes (one workspace or all) for failure signatures and remediate them in tiers: auto-fix safe cases, ask before risky ones.'
---

## Parameters

- **scope**:
  Which panes to watch: omit for the caller's own workspace, pass a workspace title or ref (workspace:N / UUID) for one workspace, or the literal `all` for every workspace.
  Default: none.
- **interval**: Seconds between scans in the continuous watch loop. Ignored when {once} is set. Default: 6.
- **once**: Run a single scan-and-remediate pass instead of the continuous watch loop. Use for a one-off check. Default: false.
- **report_only**:
  List every detected failure and its suggested fix but take no action at all — not even the safe send-enter. Overrides tiered auto-remediation.
  Default: false.

## Context

- **binary-contract**

  watchdog.py is deterministic and exposes three subcommands, each emitting JSON:
  - scan [--workspace <ref|title|all>]: one-shot. Prints {ok, run_id, scope, candidates: [...]}. Each candidate carries surface_ref, workspace_ref, workspace_title, title, signature, tier (safe | risky), remediation, detail, and a redacted evidence snippet.
  - watch [--workspace <...>] [--interval <seconds>]: loops scan, printing NDJSON — a {event: watching, ...} banner then one {event: finding, ...} line per newly detected failure. Designed for the Monitor tool. Re-emits a finding only after it clears and recurs.
  - send-enter --surface <ref> --workspace <ref>: the one safe remediation. Confirms an unsent frame is present, presses Enter, re-reads, and reports {ok, action, cleared, note}. Idempotent.
  Default scope is the caller's workspace (CMUX_WORKSPACE_ID); pass --workspace to widen or retarget. Evidence snippets are already redacted; raw secrets never reach this agent.

- **failure-signatures**

  The binary detects two failure signatures from a pane's screen:
  - unsent_p2p (tier safe): a p2p [from: <peer>] frame is sitting in the input composer with no agent output or activity below it — the message was pasted but the final Enter never registered. Remediation: send-enter.
  - api_error (tier risky): a known API or transport error (overloaded / 5xx / rate limit / connection / timeout) appears in recent output, which usually stalls the agent. Remediation: the user's call — retry, re-send via p2p, or inspect.

## Constraints

- **Must:** Never shell out to the p2p or tfork binaries. Pressing Enter on a composer via watchdog.py send-enter is a raw cmux action (the message text is already pasted — only the final Enter is missing), so it is allowed. But re-composing a p2p message or forking a replacement agent belongs to those skills: surface the need and invoke the p2p or tfork skill, do not reimplement them here.
- **Must:** Auto-apply only the send-enter remediation for an unsent_p2p finding (tier safe). Every risky finding (api_error, an exited agent, anything ambiguous) must pause for the user before any action. When report_only is set, take no action at all, including the safe send-enter.
- **Require:** All inputs and outputs are local: the cmux CLI and watchdog.py only. No network calls, no provider SDKs, no API keys.
- **Avoid:** Switching the visible workspace or yanking pane focus while watching. The watchdog only reads screens and sends Enter to the exact target surface; it never calls select-workspace, focus-pane, or focus-panel, because the user may be looking at a different workspace.

## Steps

1. Resolve <skill-dir> to the absolute directory this SKILL.md was loaded from — watchdog.py sits in that same directory, and the working directory is the user's project, not the skill directory, so a bare watchdog.py will not resolve. Every subcommand below runs as: python3 <skill-dir>/watchdog.py <subcommand>.
2. If once:
   a. Run: python3 <skill-dir>/watchdog.py scan, appending --workspace {scope} when {scope} is set. Parse stdout as one JSON object and take its candidates array as the findings to process.
   Otherwise:
   a. Launch in the background: python3 <skill-dir>/watchdog.py watch --interval {interval}, appending --workspace {scope} when {scope} is set. The binary scans on a loop and prints one JSON object per line — a watching banner first, then one finding line per newly detected failure (re-emitted only after it has cleared and recurred).
   b. Stream the background process's stdout with the Monitor tool: each NDJSON line is one notification. React to every finding event as it arrives. Keep the watcher running until the user asks to stop — the skill owns this loop.
3. Process each finding — a candidate row from the one-shot scan, or a finding event from the watch loop — by its tier, using that finding's surface_ref, workspace_ref, signature, and redacted evidence.
4. If report_only:
   a. Report the finding to the user verbatim — surface_ref, title, workspace, signature, redacted evidence, and the binary's suggested remediation — and take no action at all, not even the safe send-enter.
   If the finding's signature is unsent_p2p (tier safe):
   a. Run: python3 <skill-dir>/watchdog.py send-enter --surface <surface_ref> --workspace <workspace_ref> using the finding's refs. The binary re-reads the pane, confirms an unsent frame is still in the composer, presses Enter, and re-reads to confirm it cleared — so it is self-verifying and a no-op if the composer is already empty. Surface the result's note to the user; if cleared is false, the frame survived the Enter, so point the user at the surface and do not retry blindly.
   Otherwise:
   a. This finding is risky (api_error, or anything ambiguous). Stop and show the user its evidence and the binary's suggested remediation, and ask how to proceed before taking any action. If completing the fix needs re-sending a p2p message, load the p2p skill and send through it — never call p2p directly. If it needs respawning a dead or exited agent, load the tfork skill and have it fork a replacement into the same workspace — never call tfork directly. Never act autonomously on a risky finding.


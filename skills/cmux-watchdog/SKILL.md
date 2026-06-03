---
name: cmux_watchdog
description: 'Monitor cmux panes (one workspace or all) for failure signatures and remediate them in tiers (auto-fix safe cases, ask before risky ones), while continuously journaling pane output and, each summary interval, summarizing it into structured Obsidian worklog bullets via subagents.'
---

## Parameters

- **scope**:
  Which panes to watch: omit for the caller's own workspace, pass a workspace title or ref (workspace:N / UUID) for one workspace, or the literal `all` for every workspace.
  Default: none.
- **interval**: Seconds between scans in the continuous watch loop. Ignored when {once} is set. Default: 6.
- **once**:
  Run a single scan-and-remediate pass instead of the continuous watch loop. Use for a one-off check. No journaling or worklog summaries happen in this mode.
  Default: false.
- **report_only**:
  List every detected failure and its suggested fix but take no action at all — not even the safe send-enter. Overrides tiered auto-remediation.
  Default: false.
- **summary_interval**:
  Seconds between automatic worklog-summary passes during the watch loop. The binary emits a summarize_due event each interval; the agent runs digest and dispatches summary subagents. Set 0 to disable summarization (pure capture + detection). Ignored when {once} is set.
  Default: 3600.

## Context

- **binary-contract**

  watchdog.py is deterministic and exposes six subcommands, each emitting JSON:
  - scan [--workspace <ref|title|all>]: one-shot. Prints {ok, run_id, scope, candidates: [...]}. Each candidate carries surface_ref, workspace_ref, workspace_title, title, signature, label (the granular sub-type), tier (safe | risky), remediation, detail, known_resolution (set when a learned resolution graduated it), and a redacted evidence snippet. Excludes the watchdog's own controlling pane. Does not journal.
  - watch [--workspace <...>] [--interval <seconds>] [--summary-interval <seconds>]: loops scan, printing NDJSON — a {event: watching, ...} banner, one {event: finding, ...} line per newly detected failure, and one {event: summarize_due, ...} line every summary-interval seconds (0 disables). On every tick it also journals newly-settled pane output to per-surface append-only logs under ~/.cmux-watchdog/journal/<date>/. Designed for the Monitor tool. Re-emits a finding only after it clears and recurs. Both watch and scan exclude the watchdog's own controlling pane (resolved from CMUX_SURFACE_ID, UUID mapped to surface:N via `cmux identify`) from detection and journaling, so the watcher never flags itself; nothing is skipped when CMUX_SURFACE_ID is unset.
  - digest [--workspace <...>] [--date <YYYY-MM-DD>]: writes each in-scope surface's unread journal lines (read-cursor to end of file) to a digest_file under ~/.cmux-watchdog/digests/<date>/, advances that surface's cursor, and prints {ok, date, scope, surfaces: [{surface_ref, workspace_title, title, digest_file, unread_line_count, from_cursor, to_cursor}]}. The cursor guarantees each captured line is digested exactly once.
  - send-enter --surface <ref> --workspace <ref>: the safe remediation for unsent_p2p. Confirms an unsent frame is present, presses Enter, re-reads, and reports {ok, action, cleared, note}. Idempotent.
  - resend --surface <ref> --workspace <ref>: recall the last input (send-key Up) and resubmit it (send-key Enter), then re-read to confirm the agent resumed (an active marker appeared, or the screen changed). Prints {ok, action, resumed, surface_ref, note}. Self-verifying and safe — the proven fix for an api_error that stalled an agent.
  - record-resolution --label <granular-label> --action <action>: persist the action that resolved a finding, keyed by the granular api-error label (server_5xx / overloaded / rate_limit / api_error / connection / timeout), to <state-root>/resolutions.json (respects CMUX_WATCHDOG_HOME). On a later scan or watch tick, a finding whose label has a stored resolution is graduated risky -> safe with remediation set to that action plus a known_resolution annotation; labels with no stored resolution stay risky. Prints {ok, label, action}.
  Default scope is the caller's workspace (CMUX_WORKSPACE_ID); pass --workspace to widen or retarget. Journal and evidence text is redacted before it touches disk; raw secrets never reach this agent.

- **failure-signatures**

  The binary detects two failure signatures from a pane's screen:
  - unsent_p2p (tier safe): a p2p [from: <peer>] frame is sitting in the input composer with no agent output or activity below it — the message was pasted but the final Enter never registered. Remediation: send-enter.
  - api_error (tier risky): a known API or transport error (overloaded / 5xx / rate limit / connection / timeout) appears in recent output, which usually stalls the agent. Remediation: the user's call — retry, re-send via p2p, or inspect. But once a resolution has been recorded for the error's granular label, a recurrence graduates to tier safe and the stored action (e.g. resend) is auto-applied without pausing.

- **journal-model**

  Capture is best-effort; digestion is exact. The watch loop diffs each pane snapshot against the last, strips volatile composer / footer / spinner chrome, and appends only newly-settled output lines (overlap-anchored) to the surface's daily journal. A burst larger than the read window between ticks can drop lines — those are flagged with a gap marker rather than silently lost. But every line that reaches the journal is handed to a summary subagent exactly once, because digest advances a per-surface read-cursor: no captured line is skipped or double-counted.

## Constraints

- **Must:** Never shell out to the p2p or tfork binaries. Pressing Enter on a composer via watchdog.py send-enter is a raw cmux action (the message text is already pasted — only the final Enter is missing), so it is allowed. But re-composing a p2p message or forking a replacement agent belongs to those skills: surface the need and invoke the p2p or tfork skill, do not reimplement them here.
- **Must:** Auto-apply remediation only for tier-safe findings: the send-enter fix for an unsent_p2p finding, and — for a finding the binary graduated to safe via a learned resolution (it carries a known_resolution) — the stored action, e.g. resend. Every risky finding (an api_error whose label has no learned resolution, an exited agent, anything ambiguous) must pause for the user before any action, and when report_only is set take no action at all. The periodic worklog summary is separate and benign — it only reads journals and appends bullets to the vault — so run it automatically on each summarize_due tick without pausing.
- **Require:** The watchdog.py binary makes no network calls and uses no provider SDKs or API keys: it only shells out to cmux and reads or writes local journal and digest files. The binary never summarizes — summary subagents do that — and the worklog is written to the local Obsidian vault via the obsidian CLI.
- **Avoid:** Switching the visible workspace or yanking pane focus while watching. The watchdog only reads screens and sends Enter to the exact target surface; it never calls select-workspace, focus-pane, or focus-panel, because the user may be looking at a different workspace.

## Steps

1. Resolve <skill-dir> to the absolute directory this SKILL.md was loaded from — watchdog.py sits in that same directory, and the working directory is the user's project, not the skill directory, so a bare watchdog.py will not resolve. Every subcommand below runs as: python3 <skill-dir>/watchdog.py <subcommand>.
2. If once:
   a. Run: python3 <skill-dir>/watchdog.py scan, appending --workspace {scope} when {scope} is set. Parse stdout as one JSON object and take its candidates array as the findings to process. A one-shot scan does not journal pane output — journaling and worklog summaries only happen in the continuous watch loop.
   Otherwise:
   a. Launch in the background: python3 <skill-dir>/watchdog.py watch --interval {interval} --summary-interval {summary_interval}, appending --workspace {scope} when {scope} is set. On each tick the loop reads every in-scope pane once, detects failures, and journals newly-settled output lines to a per-surface append-only log. It prints one JSON object per line: a watching banner, one finding line per newly detected failure (re-emitted only after it clears and recurs), and — unless {summary_interval} is 0 — one summarize_due line every {summary_interval} seconds.
   b. Stream the background process's stdout with the Monitor tool: each NDJSON line is one event. Handle each event by its type and keep the watcher running until the user asks to stop — the skill owns this loop.
3. Decide which of the following applies and follow only that path:
   If the event is a summarize_due tick, or the user has explicitly asked for an ad-hoc worklog summary pass:
   a. Follow the run-worklog-summary procedure.
   Otherwise:
   a. Otherwise this event is a failure finding — a candidate row from the one-shot scan, or a finding event from the watch loop. Process it by its tier, using its surface_ref, workspace_ref, signature, and redacted evidence.
   b. Follow the process-failure-finding procedure.

### Procedure: run-worklog-summary

1. Run: python3 <skill-dir>/watchdog.py digest, appending --workspace {scope} when {scope} is set. It writes each in-scope surface's unread journal lines to a digest_file, advances that surface's read-cursor, and prints {surfaces: [...]} with each surface's digest_file and unread_line_count. Skip any surface whose unread_line_count is 0.
2. For each remaining surface, dispatch a subagent in parallel, handing it only the digest_file path — never read the raw journal lines into your own context. Instruct each subagent to read its digest_file and return concise bullets grouped under these headings, omitting any heading with nothing to report: Done (what was accomplished), Issues (problems encountered), Stuck/Blocked (where work stalled and on what), Errors (concrete errors or failures hit), and Notes (anything else salient for later analysis). Use multiple bullets per heading when warranted, and summarize only what the digest_file shows — never invent.
3. Collect every subagent's bullets and append them to the Obsidian daily worklog at $OBSIDIAN/worklog/<today>.md via the obsidian CLI, grouped under an hourly heading of the form '## <HH:MM> — <workspace_title>' per workspace; create the note or heading if absent. Write only the synthesized bullets, never raw log lines.

### Procedure: process-failure-finding

1. If report_only:
   a. Report the finding to the user verbatim — surface_ref, title, workspace, signature, label, redacted evidence, and the binary's suggested remediation — and take no action at all, not even a safe auto-fix.
   If the finding's signature is unsent_p2p (tier safe):
   a. Run: python3 <skill-dir>/watchdog.py send-enter --surface <surface_ref> --workspace <workspace_ref> using the finding's refs. The binary re-reads the pane, confirms an unsent frame is still in the composer, presses Enter, and re-reads to confirm it cleared — so it is self-verifying and a no-op if the composer is already empty. Surface the result's note to the user; if cleared is false, the frame survived the Enter, so point the user at the surface and do not retry blindly.
   If the finding carries a known_resolution (the binary graduated it to tier safe from a learned resolution):
   a. Auto-apply the learned action. When known_resolution is resend, run: python3 <skill-dir>/watchdog.py resend --surface <surface_ref> --workspace <workspace_ref>. The binary recalls the last input (Up) and resubmits it (Enter), then re-reads to confirm the agent resumed — self-verifying and safe. Surface the result's note and resumed flag to the user; if resumed is false, point them at the surface and do not retry blindly.
   Otherwise:
   a. This finding is risky (an api_error whose label has no learned resolution, or anything ambiguous). Stop and show the user its evidence and the binary's suggested remediation, and ask how to proceed before taking any action. If completing the fix needs re-sending a p2p message, load the p2p skill and send through it — never call p2p directly. If it needs respawning a dead or exited agent, load the tfork skill and have it fork a replacement into the same workspace — never call tfork directly. Never act autonomously on a risky finding. Once a human-approved fix succeeds — for an api_error that stalled the agent, pressing Up then Enter (the resend pattern) typically clears it — record it so future recurrences auto-graduate to safe: run python3 <skill-dir>/watchdog.py record-resolution --label <the finding's label> --action <action> (e.g. --action resend).


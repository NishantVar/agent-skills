"""Fork orchestration — the resolve -> fork -> verify -> report flow.

``run_fork`` is the single entry point the CLI calls: it forks the pane with a
per-fork sentinel wrapper, verifies what happened, picks a label (``--type``
override > strong observation > registry > weak observation, where *strong*
means the wrapper captured an exit status and *weak* covers still-running or
missing-marker snapshots), persists the chosen label with one asymmetric
guard (an un-overridden command does not demote an existing agent registry
entry), and returns the result. Verification never raises and never closes
the pane: an unconfirmed fork is returned as a success with ``verified``
false so the user can inspect the open pane.
"""

import os
import secrets
import shlex

from .classify import classify_observed
from .errors import err_bad_arguments, err_workspace_anchor_conflict
from .registry import REGISTRY_PATH, read_registry, write_registry_entry
from .terminal import resolve_terminal
from .verify import DEFAULT_DELAY, verify_fork


def run_fork(command_words, placement=None, anchor=None, type_override=None,
             title=None, delay=None, workspace=None, terminal=None,
             nonce=None, registry_path=REGISTRY_PATH):
    """Fork, verify, label, persist, and return the result dict.

    Raises ``ForkError`` only for argument, terminal, surface-resolution,
    split, or spawn failures (the pane has been closed or never existed in
    those cases). A verified-false outcome is *not* an error — the result is
    returned with ``verified`` false and ``note`` describing what was
    observed; the pane is left open for the user.

    ``nonce`` is generated automatically; the parameter is exposed for tests
    that need a known marker to construct expected scrollback against.
    """
    if not command_words:
        raise err_bad_arguments("no command given after '--'")
    if workspace is not None and anchor is not None:
        raise err_workspace_anchor_conflict()
    word = command_words[0]
    # The post-``--`` values are argv tokens (the caller's shell already split
    # them). shlex.join re-quotes them so a token with spaces, quotes, or a
    # ``-c`` body survives intact when the line is handed to the new pane's
    # shell — a plain space-join would corrupt it.
    command_str = shlex.join(command_words)

    if terminal is None:
        terminal = resolve_terminal()
    if delay is None:
        delay = DEFAULT_DELAY
    if nonce is None:
        nonce = secrets.token_hex(4)

    workspace_info = None
    if workspace is not None:
        workspace_info = terminal.resolve_workspace(workspace, os.getcwd())

    session = terminal.fork(command_str, placement, os.getcwd(), nonce, anchor,
                            workspace=workspace_info)

    title_note = ""
    if title:
        rename_error, duplicate_refs = terminal.rename_tab(session, title)
        if rename_error:
            title_note = f"; tab rename to '{title}' failed: {rename_error}"
        elif duplicate_refs:
            title_note = (f"; tab title '{title}' is now shared with "
                          f"{', '.join(duplicate_refs)} in the same workspace "
                          f"— p2p will report peer_ambiguous on this title")

    verified, foreground, exit_status, note = verify_fork(
        terminal, session, nonce, delay)
    if title_note:
        note = f"{note}{title_note}"
    observed_type = classify_observed(exit_status, foreground)

    # Label resolution: --type wins, then a *strong* observation (one where
    # the wrapper recorded an exit status — clean exit, non-zero exit), then
    # the registry, then the *weak* observation we are left with (still
    # running, or missing markers). The strong/weak split keeps a generic
    # launcher like ``npm`` from being permanently labelled by one
    # `npm run dev` long-runner: a later `npm test` records an exit and is
    # honoured as a command regardless of what the registry said.
    registry = read_registry(registry_path)
    strong = exit_status is not None
    if type_override in ("agent", "command"):
        label = type_override
    elif strong:
        label = observed_type
    elif word in registry:
        label = "agent" if registry[word] else "command"
    else:
        label = observed_type

    # If the label we are returning disagrees with what we just observed,
    # surface the mismatch in the note so the user can confirm or correct.
    if label != observed_type:
        note = (f"{note}; registry/override has this as {label} but observed "
                f"behavior matches {observed_type} — pass "
                f"--type {observed_type} to correct if intended")

    # Persistence rule: write the run's label back, except don't *demote* an
    # existing agent registry entry on the strength of an un-overridden
    # command observation. This is the asymmetric guard against the
    # ``tfork -- claude --version`` case: the run is honestly reported as a
    # command, but rewriting ``claude = false`` would silently break the
    # next plain ``tfork -- claude`` (weak observation, registry wins,
    # type=command, no p2p). ``--type command`` still rewrites — explicit
    # corrections are always honoured.
    demoting_agent = (strong and label == "command"
                      and registry.get(word) is True
                      and type_override is None)
    if demoting_agent:
        note = (f"{note}; registry kept the agent label for '{word}' — "
                f"pass --type command to lock this word in as a command")
    else:
        write_registry_entry(word, label == "agent", registry_path)

    if workspace_info is not None:
        ws_title = workspace_info.get("title") or ""
        ws_created = bool(workspace_info.get("created"))
        ws_label = repr(ws_title) if ws_title else workspace_info.get("ref")
        ws_state = "created" if ws_created else "reused"
        note = f"{note}; opened in workspace {ws_label} ({ws_state})"
        ws_result = {
            "ref": workspace_info.get("ref"),
            "title": ws_title,
            "created": ws_created,
        }
    else:
        ws_result = None

    return {
        "ok": True,
        "session": session,
        "ran": word,
        "type": label,
        "verified": verified,
        "foreground": foreground,
        "exit_status": exit_status,
        "workspace": ws_result,
        "note": note,
    }

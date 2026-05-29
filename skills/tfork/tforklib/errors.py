"""Structured fork failures.

Every failure the fork can hit is a ``ForkError`` — it carries a human message,
an agent instruction, whether a retry is worthwhile, and a suggested next
command, so the calling agent has everything it needs to recover. The ``err_*``
factories build one per code in the failure taxonomy; ``EXIT_CODES`` maps each
code to the binary's non-zero exit status.
"""

# Non-zero exit code per failure taxonomy code.
EXIT_CODES = {
    "no_terminal": 2,
    "bad_arguments": 2,
    "surface_resolution_failed": 3,
    "split_failed": 4,
    "spawn_failed": 5,
    "anchor_not_found": 7,
    "anchor_ambiguous": 7,
    "workspace_unknown": 8,
    "workspace_ambiguous": 8,
    "workspace_anchor_conflict": 2,
}


class ForkError(Exception):
    """A fork failure carrying everything the calling agent needs to recover."""

    def __init__(self, code, human_message, agent_instruction, retryable,
                 suggested_next_command, extras=None):
        super().__init__(human_message)
        self.code = code
        self.human_message = human_message
        self.agent_instruction = agent_instruction
        self.retryable = retryable
        self.suggested_next_command = suggested_next_command
        self.extras = dict(extras) if extras else {}

    def handoff(self):
        """The handoff JSON object the binary prints on failure."""
        out = {
            "ok": False,
            "code": self.code,
            "human_message": self.human_message,
            "agent_instruction": self.agent_instruction,
            "retryable": self.retryable,
            "suggested_next_command": self.suggested_next_command,
        }
        out.update(self.extras)
        return out


def err_no_terminal():
    return ForkError(
        "no_terminal",
        "Not running inside a supported terminal multiplexer (cmux).",
        "Do not retry. tfork requires a cmux session; tell the user tfork only "
        "works from inside cmux.",
        False,
        "Open a cmux session and invoke tfork from inside it.",
    )


def err_bad_arguments(detail):
    return ForkError(
        "bad_arguments",
        f"Invalid arguments: {detail}.",
        "Do not retry verbatim. Fix the invocation, then call again.",
        False,
        "fork_terminal.py [--placement {right,left,top,bottom}] "
        "[--workspace <title-or-ref>] [--anchor <surface-ref-or-tab-name>] "
        "[--type {agent,command}] -- <command>",
    )


def err_surface_resolution_failed():
    return ForkError(
        "surface_resolution_failed",
        "Could not resolve the caller's own cmux surface; refusing to fork "
        "from whichever pane happens to be focused.",
        "Do not retry verbatim. Set the TFORK_SURFACE_ID environment variable "
        "to the caller's cmux surface ref, then call again.",
        False,
        "TFORK_SURFACE_ID=surface:N <same fork_terminal.py invocation>",
    )


def err_split_failed(detail):
    return ForkError(
        "split_failed",
        f"cmux could not create the new pane: {detail}.",
        "Retry the same invocation once; if it fails again, report the cmux "
        "error to the user.",
        True,
        "<same fork_terminal.py invocation>",
    )


def err_spawn_failed(detail):
    return ForkError(
        "spawn_failed",
        f"The command could not be delivered into the new pane: {detail}. "
        "The created pane has been closed.",
        "Retry the same invocation once.",
        True,
        "<same fork_terminal.py invocation>",
    )


def err_anchor_not_found(value):
    return ForkError(
        "anchor_not_found",
        f"No cmux surface or tab title matched the anchor '{value}'.",
        "Do not retry verbatim. Ask the user for a valid tab title or pass "
        "a surface ref (e.g. surface:42).",
        False,
        "fork_terminal.py --anchor <surface-ref-or-tab-name> -- <command>",
    )


def err_workspace_unknown(requested, detail=None):
    """Either ``--workspace <ref>`` did not resolve to a live workspace,
    or ``--workspace <title>`` matched zero workspaces AND creation
    failed. ``detail`` is the cmux error when creation was attempted; None
    when the value was a ref that did not resolve (refs are not names, so
    no implicit creation)."""
    if detail:
        human = (f"Could not create workspace {requested!r}: {detail}.")
    else:
        human = (
            f"No cmux workspace matched {requested!r}. Refs (workspace:N "
            f"or a UUID) are not names; no workspace is created on a ref "
            f"miss."
        )
    return ForkError(
        "workspace_unknown",
        human,
        "Do not retry verbatim. If you meant to name a new workspace, "
        "pass a title (not a workspace:N ref) — tfork creates titles "
        "that don't yet match a workspace. If you meant to target an "
        "existing one, list workspaces with 'cmux list-workspaces' and "
        "rerun with the right title or ref.",
        False,
        "fork_terminal.py --workspace <title-or-ref> -- <command>",
        extras={"requested": requested},
    )


def err_workspace_ambiguous(requested, candidates):
    """``--workspace <title>`` matched two or more live workspaces; refusing
    to guess. ``candidates`` is a list of ``{ref, title}`` dicts."""
    refs = [c.get("ref") for c in candidates if c.get("ref")]

    def _describe(c):
        return f"{c.get('ref') or '<unknown>'} ({c.get('title') or ''})"

    bulleted = "\n".join(f"  - {_describe(c)}" for c in candidates) \
        or "  <none>"
    listed_refs = ", ".join(refs) if refs else "<none>"
    return ForkError(
        "workspace_ambiguous",
        f"More than one cmux workspace is titled {requested!r}. Refusing "
        f"to guess which one to target. Candidates:\n{bulleted}",
        "Do not retry verbatim. Pick one of the listed refs and rerun "
        "with --workspace <ref>.",
        False,
        f"fork_terminal.py --workspace <one of: {listed_refs}> -- <command>",
        extras={"requested": requested,
                "candidates": [dict(c) for c in candidates]},
    )


def err_workspace_anchor_conflict():
    return ForkError(
        "workspace_anchor_conflict",
        "Cannot pass both --workspace and --anchor: the anchor's "
        "workspace is implicit, so the two flags can disagree.",
        "Do not retry verbatim. Pick one — drop --anchor and use "
        "--workspace, or drop --workspace and let the anchor decide.",
        False,
        "fork_terminal.py --workspace <title-or-ref> -- <command>  "
        "OR  fork_terminal.py --anchor <ref-or-tab> -- <command>",
    )


def err_anchor_ambiguous(value, candidates):
    """``candidates`` is a list of ``{ref, workspace_ref, workspace_title}``
    dicts — one per surface whose tab title matched. The human message lists
    each candidate by workspace so the user can pick by workspace name; the
    suggested command shows the surface refs themselves since that is what
    ``--anchor`` actually accepts."""
    refs = [c.get("ref") for c in candidates if c.get("ref")]

    def _describe(c):
        ws_title = c.get("workspace_title")
        ws_ref = c.get("workspace_ref") or "<unknown workspace>"
        location = f"'{ws_title}' ({ws_ref})" if ws_title else ws_ref
        return f"{c.get('ref') or '<unknown surface>'} in workspace {location}"

    lines = [f"  - {_describe(c)}" for c in candidates]
    bulleted = "\n".join(lines) if lines else "  <none>"
    listed_refs = ", ".join(refs) if refs else "<none>"
    return ForkError(
        "anchor_ambiguous",
        f"More than one cmux tab is titled '{value}'. Refusing to guess "
        f"which one to anchor on. Candidates:\n{bulleted}",
        "Do not retry verbatim. Ask the user which workspace they meant, "
        "then pass the matching surface ref above as --anchor.",
        False,
        f"fork_terminal.py --anchor <one of: {listed_refs}> -- <command>",
    )

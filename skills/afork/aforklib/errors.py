"""Structured afork failures and the ready-to-fork handoff.

afork resolves an agent definition, maps its declared permissions onto a
runtime-enforced launch command, and then hands the command to ``tfork`` — it
never forks itself. Every outcome is a single JSON object on stdout:

  * success  -> a ``ready_to_fork`` handoff (``ok`` true) the calling agent
               passes to the tfork skill.
  * failure  -> an ``AforkError`` handoff (``ok`` false) carrying a human
               message, an agent instruction, and recovery hints — the same
               shape tfork and p2p use.

Fail-closed is the rule: a declared restriction that the adapter cannot prove
it enforces at runtime is a refusal, not a prompt-level best effort.
"""

import shlex

# Non-zero exit code per failure taxonomy code.
EXIT_CODES = {
    "bad_arguments": 2,
    "port_not_found": 3,
    "runtime_unsupported": 4,
    "unenforceable": 5,
    "port_unparsable": 7,
    "custom_unsupported": 8,
}


class AforkError(Exception):
    """An afork failure carrying everything the calling agent needs to recover."""

    def __init__(self, code, human_message, agent_instruction, retryable=False,
                 extras=None):
        super().__init__(human_message)
        self.code = code
        self.human_message = human_message
        self.agent_instruction = agent_instruction
        self.retryable = retryable
        self.extras = dict(extras) if extras else {}

    def handoff(self):
        out = {
            "ok": False,
            "code": self.code,
            "human_message": self.human_message,
            "agent_instruction": self.agent_instruction,
            "retryable": self.retryable,
        }
        out.update(self.extras)
        return out


def err_bad_arguments(detail):
    return AforkError(
        "bad_arguments",
        f"Invalid arguments: {detail}.",
        "Do not retry verbatim. Fix the invocation, then call again.",
    )


def err_runtime_unsupported(runtime, reason):
    return AforkError(
        "runtime_unsupported",
        f"Runtime {runtime!r} is not supported for launch: {reason}",
        "Do not retry. Tell the user this runtime has no adapter yet. "
        "codex, claude, and pi launch (plain + permission none); antigravity "
        "is unsupported.",
        extras={"runtime": runtime},
    )


def err_custom_unsupported(runtime, reason):
    """A custom (definition-backed) agent was requested for a runtime that has
    no agent-definition directory (e.g. pi)."""
    return AforkError(
        "custom_unsupported",
        f"Runtime {runtime!r} does not support custom agents: {reason}",
        "Do not retry verbatim. Launch the plain agent instead (omit the agent "
        "name), or inject the persona another way.",
        extras={"runtime": runtime},
    )


def err_port_not_found(runtime, agent, path):
    """``path`` is the location(s) searched: a single string (explicit-path
    mode) or a list of bare-name candidates (repo-local then home)."""
    paths = list(path) if isinstance(path, (list, tuple)) else [path]
    primary = paths[0]
    where = " or ".join(paths)
    return AforkError(
        "port_not_found",
        f"No {runtime} agent definition for {agent!r} at {where}.",
        "Do not retry verbatim. For a bare agent name, check the name and "
        f"that the definition exists under <cwd>/.{runtime}/agents/ or "
        f"~/.{runtime}/agents/ (the repo-local dir is tried first, then home). "
        "For an explicit path, check that the file exists at that path. "
        "Bare-name ports resolve relative to --cwd and the home config; "
        "explicit paths do not.",
        extras={"runtime": runtime, "agent": agent,
                "expected_path": primary, "searched": paths},
    )


def err_port_unparsable(runtime, agent, path, detail):
    return AforkError(
        "port_unparsable",
        f"The {runtime} agent definition at {path} could not be parsed: {detail}.",
        "Do not retry verbatim. Fix the agent definition file, then call again.",
        extras={"runtime": runtime, "agent": agent, "path": path},
    )


def err_unenforceable(runtime, agent, declared, reason):
    """The fail-closed refusal: a declared restriction the adapter cannot prove
    it enforces at runtime. Overridable only with explicit --allow-unenforced."""
    who = f"agent {agent!r}" if agent else "plain agent"
    return AforkError(
        "unenforceable",
        f"Refusing to launch {runtime} {who}: declared "
        f"permission {declared!r} cannot be enforced at runtime. {reason} "
        "Prompt-level restriction is not sufficient.",
        "Do NOT fork. Report the refusal to the user. Only re-run with "
        "--allow-unenforced if the user explicitly accepts an unenforced launch.",
        extras={"runtime": runtime, "agent": agent, "declared": declared},
    )


def ready_to_fork(runtime, agent, posture, command, title, cwd,
                  workdir, enforced=True, placement=None):
    """The success handoff: a fully-built launch command for the tfork skill.

    afork stops here by design — it does not invoke tfork. The calling agent
    takes ``command`` and forks it via the tfork skill with the carried
    --title / --cwd / --type agent (and --placement when present).
    """
    tfork_args = (f"--title {shlex.quote(str(title))} "
                  f"--cwd {shlex.quote(str(cwd))} --type agent")
    if placement:
        tfork_args += f" --placement {shlex.quote(str(placement))}"
    who = f"agent {agent!r}" if agent else "plain agent"
    # A persona payload is only written in custom mode (workdir set).
    persona_note = (" Persona injected at system/developer level from a 0600 "
                    "temp payload (not user prose).") if workdir else ""
    if posture == "none":
        note = (f"permission posture {posture!r} (yolo): nothing to enforce, so "
                f"reported enforced.{persona_note}")
    elif enforced:
        note = (f"permission posture {posture!r} is runtime-enforced.{persona_note}")
    else:
        note = (f"UNENFORCED launch: --allow-unenforced was passed, so the "
                f"declared {posture!r} restriction is NOT runtime-enforced. "
                f"The user accepted this risk.")
    return {
        "ok": True,
        "action": "ready_to_fork",
        "handoff_skill": "tfork",
        "runtime": runtime,
        "agent": agent,
        "posture": posture,
        "enforced": enforced,
        "command": command,
        "title": title,
        "cwd": cwd,
        "type": "agent",
        "placement": placement,
        "workdir": workdir,
        "human_message": (
            f"afork prepared {runtime} {who} with permission posture "
            f"{posture!r}. Hand the command to tfork to launch."),
        "agent_instruction": (
            "Invoke the tfork skill to fork this command verbatim after the "
            f"-- separator, passing {tfork_args}. Do not edit the command."),
        "note": note,
    }

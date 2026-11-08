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
    "scoped_view_unsupported": 9,
    "scoped_view_unenforceable": 10,
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


def err_scoped_view_unsupported(runtime):
    """--scoped-view was requested for a runtime with no scoped-view controls."""
    return AforkError(
        "scoped_view_unsupported",
        f"Runtime {runtime!r} has no scoped native view: afork cannot hide "
        "personal or plugin skills and competing startup hooks for it.",
        "Do not retry verbatim and do not launch without --scoped-view as a "
        "substitute. Tell the user the scoped view is claude/codex only.",
        extras={"runtime": runtime},
    )


def err_scoped_view_unenforceable(runtime, detail):
    """The personal setup has something the scoped view cannot represent."""
    return AforkError(
        "scoped_view_unenforceable",
        f"Refusing a scoped {runtime} launch: {detail}.",
        "Do NOT fork. Report the refusal to the user; the personal host "
        "configuration needs a change only the user can make.",
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
                  workdir, enforced=True, placement=None, observed=None,
                  obs_tags=None, obs_warning=None, launch_contract=None,
                  attempt_id=None, persona=False, deprecation_warning=None,
                  native_view=None):
    """The success handoff: a fully-built launch command for the tfork skill.

    afork stops here by design — it does not invoke tfork. The calling agent
    takes ``command`` and forks it via the tfork skill with the carried
    --title / --cwd / --type agent / --launch-contract (and --placement when
    present).

    ``launch_contract`` is the 0600 sidecar in afork's private ``workdir``
    naming this ``attempt_id``, the runtime/model really invoked, and the
    adapter's failure signatures. tfork combines it with what it observes to
    return the versioned ``launch_outcome``; without it tfork can still report
    an outcome, but never a runtime-specific one.

    ``deprecation_warning`` is set only when a legacy ``-agent`` name had to be
    bridged to its suffixless port. ``agent`` is then already the canonical
    suffixless name — the warning tells the caller to start passing it.

    ``native_view`` is the --scoped-view report (controls applied, startup
    hooks kept, capabilities lost or unverified); it is omitted otherwise.

    ``observed`` is None when --observe was not requested at all, and the whole
    observability block is then omitted — a handoff without --observe is
    byte-for-byte what it always was, so existing consumers see no new fields.
    When requested, ``observed`` is True only if the command was really wrapped;
    the fail-open path (no `lens` on PATH) reports False plus ``obs_warning``.
    ``obs_tags`` echoes the attribution that was *requested*; ``observed`` is the
    only authority on whether it was actually applied.
    """
    tfork_args = (f"--title {shlex.quote(str(title))} "
                  f"--cwd {shlex.quote(str(cwd))} --type agent")
    if launch_contract:
        tfork_args += f" --launch-contract {shlex.quote(str(launch_contract))}"
    if placement:
        tfork_args += f" --placement {shlex.quote(str(placement))}"
    who = f"agent {agent!r}" if agent else "plain agent"
    # A persona payload is only written in custom (definition-backed) mode.
    persona_note = (" Persona injected at system/developer level from a 0600 "
                    "temp payload (not user prose).") if persona else ""
    if posture == "none":
        note = (f"permission posture {posture!r} (yolo): nothing to enforce, so "
                f"reported enforced.{persona_note}")
    elif enforced:
        note = (f"permission posture {posture!r} is runtime-enforced.{persona_note}")
    else:
        note = (f"UNENFORCED launch: --allow-unenforced was passed, so the "
                f"declared {posture!r} restriction is NOT runtime-enforced. "
                f"The user accepted this risk.")
    if observed:
        note += (" Launch wrapped with agentlens (`lens run`); capture itself "
                 "is fail-open and never changes the agent's exit code.")
    elif obs_warning:
        note += f" {obs_warning}"
    if deprecation_warning:
        note += f" {deprecation_warning}"
    out = {
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
        "launch_contract": launch_contract,
        "attempt_id": attempt_id,
        "human_message": (
            f"afork prepared {runtime} {who} with permission posture "
            f"{posture!r}. Hand the command to tfork to launch."),
        "agent_instruction": (
            "Invoke the tfork skill to fork this command verbatim after the "
            f"-- separator, passing {tfork_args}. Do not edit the command. "
            "--launch-contract is what lets tfork return a trustworthy "
            "launch_outcome; dropping it downgrades every ambiguous launch to "
            "state 'unknown'."),
        "note": note,
    }
    if deprecation_warning:
        out["deprecation_warning"] = deprecation_warning
    if native_view is not None:
        out["native_view"] = native_view
    if observed is not None:
        out["observed"] = observed
        out["obs_tags"] = obs_tags or None
        if obs_warning:
            out["obs_warning"] = obs_warning
    return out

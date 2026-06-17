"""Runtime adapters — one per coding-agent runtime.

afork is agnostic to runtime-specific flag names; the adapter owns the mapping
from agnostic concepts (permission posture, model, effort, persona) to a given
runtime's CLI flags. Each adapter knows:

  * its executable (``bin``) and default model/effort,
  * whether it has an agent-definition directory (``has_agent_dir``) and, if so,
    where definitions live (``port_filename``) and how to parse them (``parse``),
  * which postures it can runtime-*enforce* (``enforceable`` — the fail-closed
    pivot), and the argv tokens for a posture / model / effort,
  * how to inject a persona (``persona_inject``).

Postures are agnostic: ``none`` (yolo) | ``read-only`` | ``workspace-write``.
``none`` is always enforceable (every runtime has a real flag, or yolo is its
default). Restricted postures are enforceable only when the adapter proves it;
otherwise afork fails closed.

This round: codex enforces all three (OS seatbelt via ``--sandbox``, proven by
tests/proof_codex_readonly.sh). claude and pi enforce only ``none``; their
restricted modes are deferred and fail closed. antigravity has no adapter yet.
"""

import tomllib

from .errors import err_port_unparsable


class CodexAdapter:
    runtime = "codex"
    bin = "codex"
    has_agent_dir = True
    default_model = None
    default_effort = "xhigh"
    supports_context_window = False
    # codex injects the persona at developer level: -c key="$(cat payload)".
    persona_inject = {"style": "config_cat", "flag": "developer_instructions"}

    def port_filename(self, agent):
        return f"{agent}.toml"

    def parse(self, text, agent, path):
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise err_port_unparsable(self.runtime, agent, path, str(exc))
        sb = data.get("sandbox_mode")
        if sb is not None and not isinstance(sb, str):
            # A malformed sandbox_mode is a fix-the-file error, NOT an
            # --allow-unenforced-overridable refusal. Fail at parse time.
            raise err_port_unparsable(
                self.runtime, agent, path,
                f"sandbox_mode must be a string, got {type(sb).__name__}")
        return data

    def declared_posture(self, parsed):
        """Normalize a codex definition's sandbox_mode to an agnostic posture,
        or None when the definition declares no sandbox. parse() guarantees the
        value is a string or absent."""
        sb = parsed.get("sandbox_mode")
        if sb is None:
            return None
        return {
            "read-only": "read-only",
            "workspace-write": "workspace-write",
            "danger-full-access": "none",
        }.get(sb, sb)  # unknown values pass through -> not enforceable

    def declared_model(self, parsed):
        return parsed.get("model")

    def declared_effort(self, parsed):
        return parsed.get("model_reasoning_effort")

    def persona_body(self, parsed):
        return parsed.get("developer_instructions", "") or ""

    def enforceable(self, posture):
        return posture in ("none", "read-only", "workspace-write")

    def permission_flags(self, posture):
        return {
            "none": ["--dangerously-bypass-approvals-and-sandbox"],
            "read-only": ["--sandbox", "read-only"],
            "workspace-write": ["--sandbox", "workspace-write"],
        }.get(posture, [])  # unenforced override -> emit no posture flag

    def model_flag(self, m):
        return ["-c", f'model="{m}"']

    def effort_flag(self, e):
        return ["-c", f'model_reasoning_effort="{e}"']


class ClaudeAdapter:
    runtime = "claude"
    bin = "claude"
    has_agent_dir = True
    default_model = "opus"
    default_effort = "high"
    supports_context_window = True
    # claude injects the persona as a system-prompt append: --flag "$(cat payload)".
    persona_inject = {"style": "flag_cat", "flag": "--append-system-prompt"}

    def port_filename(self, agent):
        return f"{agent}.md"

    def parse(self, text, agent, path):
        # The whole .md body is the persona; no structured fields.
        return {"persona_body": text}

    def declared_posture(self, parsed):
        # Claude definitions carry no enforced sandbox declaration this round.
        return None

    def declared_model(self, parsed):
        return None

    def declared_effort(self, parsed):
        return None

    def persona_body(self, parsed):
        return parsed.get("persona_body", "") or ""

    def enforceable(self, posture):
        # Only yolo is enforced; restricted modes are deferred (fail closed).
        return posture == "none"

    def permission_flags(self, posture):
        # Restricted postures fail closed before build, unless --allow-unenforced
        # is passed (then emit no posture flag — we can't honestly enforce it).
        return {"none": ["--dangerously-skip-permissions"]}.get(posture, [])

    def model_flag(self, m):
        return ["--model", m]

    def effort_flag(self, e):
        return ["--effort", e]

    def context_window_prefix(self, context_window):
        return ["env", "CLAUDE_CODE_DISABLE_1M_CONTEXT=0"]

    def context_window_model(self, model, context_window):
        model = model or self.default_model
        if model.endswith("[1m]"):
            return model
        return f"{model}[1m]"


class PiAdapter:
    runtime = "pi"
    bin = "pi"
    has_agent_dir = False
    default_model = None
    default_effort = None
    supports_context_window = False
    # pi takes a file path directly: --flag <payload-path> (no $(cat)).
    persona_inject = {"style": "flag_path", "flag": "--append-system-prompt"}

    # No agent-definition directory -> no port_filename / parse / persona_body.

    def declared_posture(self, parsed):
        return None

    def declared_model(self, parsed):
        return None

    def declared_effort(self, parsed):
        return None

    def enforceable(self, posture):
        # pi is yolo by default (none = no flag). Restricted modes via --tools
        # are out of scope this round -> fail closed.
        return posture == "none"

    def permission_flags(self, posture):
        # none = NO flag (yolo is pi's default). Restricted fails closed earlier
        # (or, with --allow-unenforced, also emits no posture flag).
        return []

    def model_flag(self, m):
        return ["--model", m]

    def effort_flag(self, e):
        return ["--thinking", e]


_ADAPTERS = {
    "codex": CodexAdapter,
    "claude": ClaudeAdapter,
    "pi": PiAdapter,
}

# Runtimes named in the design brief but not yet built. Listed so afork can
# give a precise runtime_unsupported message instead of a generic one.
_PLACEHOLDER_RUNTIMES = {"antigravity"}


def get_adapter(runtime):
    """Return an adapter instance, or None when the runtime has no adapter."""
    cls = _ADAPTERS.get(runtime)
    return cls() if cls else None

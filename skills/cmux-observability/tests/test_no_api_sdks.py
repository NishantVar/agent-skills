"""Source-tree guard: no provider SDK imports, no API-key signals.

The cmux-observability skill is intentionally SDK-free. It consumes
agent-authored summaries via a JSON contract and never speaks to a model
provider directly. This test enforces that invariant by walking every
``.py`` file shipped in the ``cmux_observability`` package and asserting:

  1. No ``import``/``from ... import`` statement references a known
     provider SDK module (prefix-matched so ``google.generativeai`` is
     caught even though ``google`` is also a legitimate top-level
     namespace for unrelated libraries).
  2. No API-key environment variable name or known key-prefix literal
     appears anywhere in the source text.

Scope is strictly ``cmux_observability/**/*.py``. ``SKILL.md``, tests, and
fixtures are deliberately excluded because they may legitimately mention
provider names in negative context (e.g. "no Anthropic SDK"), in
assertion strings, or in regression fixtures.

The text scan only flags real env-var names and key-prefix tokens — bare
vendor words ("Anthropic", "OpenAI", "Google", "Gemini") are not in the
blacklist; this matches the policy already set in
``tests/test_skill_packaging.py`` (T15).

Design note on the import check: the previous draft used
``alias.name.split(".")[0] in FORBIDDEN`` which would miss
``import google.generativeai`` unless the bare ``"google"`` token were
forbidden. Adding ``"google"`` to the forbidden top-level set would
block any future legitimate ``google.*`` usage (cloud SDKs, etc.), so
instead we use a prefix-match helper (Option B) that treats each entry
in ``FORBIDDEN_MODULES`` as either an exact module name or a parent
package prefix.
"""

from __future__ import annotations

import ast
from pathlib import Path


PKG = Path(__file__).resolve().parents[1] / "cmux_observability"

# Provider SDK module names. Prefix-matched: an entry ``"google.generativeai"``
# matches ``google.generativeai`` itself and any ``google.generativeai.*``
# submodule, but NOT a bare ``import google`` or unrelated ``google.cloud.*``
# package.
FORBIDDEN_MODULES = (
    "anthropic",
    "openai",
    "google.generativeai",
    "cohere",
    "groq",
    "mistralai",
)

# Real env-var names and key-prefix literals. Bare vendor words are
# intentionally absent so prose / SKILL-adjacent strings can mention
# providers in negative context.
FORBIDDEN_KEY_PATTERNS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "XAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "COHERE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "sk-ant-",
    "sk-proj-",
)


def _iter_files() -> list[Path]:
    return sorted(PKG.rglob("*.py"))


def _is_forbidden_module(modname: str) -> bool:
    """Prefix-match ``modname`` against ``FORBIDDEN_MODULES``.

    ``modname`` is forbidden if it equals one of the forbidden entries or
    starts with ``"<entry>."``. This catches ``google.generativeai`` and
    ``google.generativeai.types`` without poisoning the bare ``google``
    namespace.
    """
    if not modname:
        return False
    return any(
        modname == f or modname.startswith(f + ".") for f in FORBIDDEN_MODULES
    )


def test_no_provider_sdk_imports() -> None:
    violations: list[str] = []
    for path in _iter_files():
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden_module(alias.name):
                        violations.append(
                            f"{path}:{node.lineno}: import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if _is_forbidden_module(mod):
                    violations.append(
                        f"{path}:{node.lineno}: from {mod} import ..."
                    )
    assert not violations, "forbidden provider SDK imports:\n" + "\n".join(
        violations
    )


def test_no_api_key_text_patterns() -> None:
    violations: list[str] = []
    for path in _iter_files():
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in FORBIDDEN_KEY_PATTERNS:
                if pat in line:
                    violations.append(f"{path}:{lineno}: {pat!r} in {line!r}")
    assert not violations, "forbidden API-key text patterns:\n" + "\n".join(
        violations
    )

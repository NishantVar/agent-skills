"""Packaging guard for the cmux-observability skill artifacts.

Asserts that SKILL.glyph and SKILL.md ship together, that SKILL.md has a
parseable YAML frontmatter with the expected fields, that no
provider-SDK / API-key signals leak into the skill prose, and that two
load-bearing workflow markers from the T14 amendments survive.
"""

from __future__ import annotations

from pathlib import Path

import yaml


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_GLYPH = SKILL_DIR / "SKILL.glyph"
SKILL_MD = SKILL_DIR / "SKILL.md"

# Provider SDK / API-key signals. The bare vendor names "Anthropic" and
# "OpenAI" are intentionally NOT blacklisted — the skill correctly states
# it has no provider SDK / API-key handling and may mention vendor names
# in prose.
FORBIDDEN_PROVIDER_SUBSTRINGS = (
    "import anthropic",
    "import openai",
    "from anthropic",
    "from openai",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "sk-ant-",
    "sk-proj-",
)


def test_skill_glyph_source_exists():
    assert SKILL_GLYPH.is_file(), f"missing {SKILL_GLYPH}"


def test_skill_md_exists():
    assert SKILL_MD.is_file(), f"missing {SKILL_MD}"


def test_skill_md_frontmatter_is_valid_yaml():
    text = SKILL_MD.read_text()
    assert text.startswith("---\n"), "SKILL.md missing opening frontmatter delimiter"
    parts = text.split("---", 2)
    assert len(parts) >= 3, "SKILL.md frontmatter not closed"
    data = yaml.safe_load(parts[1])
    assert isinstance(data, dict), "frontmatter is not a mapping"
    assert data.get("name") == "cmux_status", f"unexpected name: {data.get('name')!r}"
    description = data.get("description")
    assert isinstance(description, str), "description must be a string"
    assert len(description.strip()) > 0, "description must be non-empty"


def test_skill_md_has_no_provider_sdk_or_api_key_signals():
    text = SKILL_MD.read_text()
    for forbidden in FORBIDDEN_PROVIDER_SUBSTRINGS:
        assert forbidden not in text, (
            f"SKILL.md contains forbidden provider signal: {forbidden!r}"
        )


def test_skill_md_does_not_reference_themes_eligible():
    # T14 amendment regression guard: the old "themes_eligible" marker
    # was retired in favour of the new workflow language.
    text = SKILL_MD.read_text()
    assert "themes_eligible" not in text, (
        "SKILL.md still references retired 'themes_eligible' marker"
    )


def test_skill_md_has_python_probe_loop():
    # T14 amendment regression guard: the python-interpreter probe loop
    # must survive future edits.
    text = SKILL_MD.read_text()
    assert "for cand in python3 python" in text, (
        "SKILL.md missing python-interpreter probe loop"
    )

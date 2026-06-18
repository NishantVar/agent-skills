"""Front-door contract: the compiled SKILL.md and the binary must not drift.

Asserts the compiled ``SKILL.md`` declares the documented parameters and maps
them onto the binary's ``--placement`` / ``--anchor`` / ``--type`` / ``--``
invocation.
"""

from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def test_skill_md_exists():
    assert SKILL_MD.exists(), "compiled SKILL.md is missing"


def test_front_door_declares_the_parameters():
    text = SKILL_MD.read_text()
    for parameter in ("command", "placement", "anchor", "workspace",
                      "type_override", "window"):
        assert parameter in text, f"SKILL.md does not declare {parameter!r}"


def test_front_door_maps_onto_the_binary_invocation():
    text = SKILL_MD.read_text()
    for token in ("fork_terminal.py", "--placement", "--anchor",
                  "--workspace", "--window", "--type", "--"):
        assert token in text, f"SKILL.md does not reference {token!r}"


def test_front_door_invokes_the_binary_explicitly():
    """The compiled skill must pin an unambiguous invocation: run via
    ``python3``, with the binary addressed by its skill-directory path —
    not a bare ``fork_terminal.py`` that would not resolve from a project
    working directory. Placement is now optional, so the boilerplate
    invocation no longer pins ``--placement`` — flags are inserted
    conditionally per the steps."""
    text = SKILL_MD.read_text()
    assert "python3 <skill-dir>/fork_terminal.py" in text, (
        "SKILL.md does not pin the explicit python3 <skill-dir> invocation"
    )


def test_front_door_does_not_expose_delay():
    """``--delay`` is an internal binary knob; the skill must not surface
    it as a parameter the agent passes through."""
    text = SKILL_MD.read_text()
    assert "--delay" not in text, "SKILL.md leaks --delay into the front door"

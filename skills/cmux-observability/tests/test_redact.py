from pathlib import Path

from cmux_observability.redact import redact


def test_redact_replaces_known_secret_patterns(fixture_dir: Path):
    text = (fixture_dir / "redaction_secrets.txt").read_text()
    out, applied = redact(text)
    # Originals must NOT appear in the output.
    for needle in (
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "AKIAABCDEFGHIJKLMNOP",
        "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
        "xoxb-123456789012-987654321098-AbCdEfGhIjKlMnOpQrSt",
        "xyz.abc.def-1234567890abcdef1234",
        "hunter2_supersecret_value",
    ):
        assert needle not in out, f"original secret leaked: {needle}"
    # Each kind that fired must be recorded.
    kinds = {a.split(":", 1)[0] for a in applied}
    for kind in ("SK_TOKEN", "AWS_ACCESS_KEY", "GH_TOKEN", "SLACK_TOKEN", "BEARER", "PASSWORD"):
        assert kind in kinds, f"missing redaction kind: {kind}"
    assert "plain shell output should remain intact" in out
    # Non-secret shell prompts/commands must survive verbatim — guards against
    # over-broad redaction patterns eating real shell context.
    assert "$ aws s3 ls" in out
    assert "$ gh auth status" in out
    assert "$ slack post" in out
    assert "$ export ANTHROPIC_API_KEY=" in out


def test_redact_returns_unchanged_text_when_no_secrets():
    out, applied = redact("nothing interesting here\nls -la\n")
    assert out == "nothing interesting here\nls -la\n"
    assert applied == []

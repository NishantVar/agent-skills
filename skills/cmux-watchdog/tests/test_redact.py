"""Tests for the richer redactor moved into watchdog (sibling import)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import redact as r  # noqa: E402


def test_redact_meta_masks_and_reports_applied():
    text = "token sk-ABCDEFGHIJKLMNOPQRSTUVWX and AKIAABCDEFGHIJKLMNOP"
    out, applied = r.redact_meta(text)
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in out
    assert "AKIAABCDEFGHIJKLMNOP" not in out
    assert "SK_TOKEN:1" in applied
    assert "AWS_ACCESS_KEY:1" in applied


def test_redact_meta_clean_text_no_applied():
    out, applied = r.redact_meta("nothing secret here")
    assert out == "nothing secret here"
    assert applied == []


def test_redact_str_wrapper_passthrough():
    assert r.redact("nothing secret here") == "nothing secret here"


def test_redact_str_wrapper_masks():
    out = r.redact("password: hunter2xyz")
    assert "hunter2xyz" not in out
    assert "REDACTED" in out


def test_redact_meta_is_idempotent_for_hash():
    text = "leak sk-ABCDEFGHIJKLMNOPQRSTUVWX here"
    once, _ = r.redact_meta(text)
    twice, applied2 = r.redact_meta(once)
    # Second pass finds nothing (placeholders carry no secret) -> stable text.
    assert twice == once
    assert applied2 == []
    assert r.screen_hash(once) == r.screen_hash(twice)


def test_screen_hash_is_sha256_hex():
    h = r.screen_hash("abc")
    assert len(h) == 64
    assert h == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

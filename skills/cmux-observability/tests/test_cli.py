"""CLI dispatch tests: --help smoke, --config after subcommand, themes-payload."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cmux_observability import cli, runstate
from cmux_observability.model import Snapshot


MIN_CONFIG = """
[summarizer]
enabled = true
themes_enabled = true
"""


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(MIN_CONFIG)
    return cfg


def _empty_snapshot() -> Snapshot:
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
        host="localhost",
        cmux_version=None,
        workspaces=[],
        agents=[],
    )


def test_help_smoke_via_main(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "collect" in out
    assert "record-summaries" in out
    assert "themes-payload" in out
    assert "record-themes" in out
    assert "finalize" in out


def test_config_post_subcommand_position_parses(tmp_path: Path) -> None:
    """`collect --config <path>` (option after subcommand) must parse cleanly.

    Argparse only accepts options on the subcommand parser if they are
    registered on the subparser itself.
    """
    cfg = _write_config(tmp_path)
    parser = cli.build_parser()
    args = parser.parse_args(["collect", "--config", str(cfg)])
    assert args.cmd == "collect"
    assert args.config == str(cfg)


def test_themes_payload_uses_existing_runstate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """themes-payload reads runstate and emits a JSON envelope.

    Guards against the `load_config`/`_load_config` name mismatch in the
    plan snippet — a wrong name would surface here as NameError.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    cfg = _write_config(tmp_path)
    snap = _empty_snapshot()
    run_id = runstate.new_run_id()
    runstate.write(run_id, snap, screen_hashes={}, redactions_by_surface={})

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main([
            "themes-payload", "--run-id", run_id, "--config", str(cfg),
        ])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["ok"] is True
    # themes_payload envelope has either `payload` or `omit`+`reason`.
    assert "payload" in out or "omit" in out

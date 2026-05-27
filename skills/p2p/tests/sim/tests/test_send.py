import json
import sys
from pathlib import Path

from lib.send import send_and_log


def test_send_and_log_invokes_agent_msg_and_logs(tmp_path: Path, monkeypatch):
    log_path = tmp_path / "worker_alpha.jsonl"
    msg_file = tmp_path / "msg.txt"
    msg_file.write_text("hello")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        class R:
            returncode = 0
            stdout = json.dumps({"ok": True, "kind": "message",
                                 "peer_status": "live",
                                 "resolved_by": "title_in_workspace",
                                 "title": "worker_bravo",
                                 "surface": "surface:3"})
            stderr = ""
        return R()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = send_and_log(
        peer="worker_bravo",
        message_file=msg_file,
        log_path=log_path,
        run_id="r1", step_id=1, attempt_id="a1",
        my_title="worker_alpha",
    )

    assert result["ok"] is True
    assert "--peer" in captured["cmd"]
    assert "worker_bravo" in captured["cmd"]
    assert "--my-title" in captured["cmd"]
    assert "worker_alpha" in captured["cmd"]
    assert "--message-file" in captured["cmd"]

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "send_result"
    assert rec["observed_kind"] == "message"


def test_send_and_log_omits_my_title_when_none(tmp_path: Path, monkeypatch):
    log_path = tmp_path / "alpha.jsonl"
    msg_file = tmp_path / "m.txt"
    msg_file.write_text("hi")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        class R:
            returncode = 0
            stdout = json.dumps({"ok": True, "kind": "message"})
            stderr = ""
        return R()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)

    send_and_log(peer="bravo", message_file=msg_file, log_path=log_path,
                 run_id="r1", step_id=1, attempt_id="a1", my_title=None)
    assert "--my-title" not in captured["cmd"]


def test_send_and_log_passes_one_way_flag(tmp_path: Path, monkeypatch):
    log_path = tmp_path / "alpha.jsonl"
    msg_file = tmp_path / "m.txt"
    msg_file.write_text("hi")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        class R:
            returncode = 0
            stdout = json.dumps({"ok": True, "kind": "message", "one_way": True})
            stderr = ""
        return R()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)

    send_and_log(peer="bravo", message_file=msg_file, log_path=log_path,
                 run_id="r1", step_id=4, attempt_id="a1", one_way=True)
    assert "--one-way" in captured["cmd"]


def test_log_inbound_cli_writes_event(tmp_path: Path):
    import subprocess
    log_path = tmp_path / "bravo.jsonl"
    raw = '[from: worker_alpha] COUNTER:{"run_id":"r1","step_id":2,"attempt_id":"a1","sender":"worker_alpha","value":3}'
    cli = Path(__file__).resolve().parents[1] / "bin" / "log_inbound.py"
    proc = subprocess.run([sys.executable, str(cli),
                           "--log-path", str(log_path),
                           "--run-id", "r1", "--step-id", "2",
                           "--raw-frame", raw],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    rec = json.loads(log_path.read_text().splitlines()[0])
    assert rec["from_title"] == "worker_alpha"
    assert rec["one_way"] is False
    assert rec["parse_status"] == "ok"


def test_log_inbound_cli_marks_one_way(tmp_path: Path):
    import subprocess
    log_path = tmp_path / "bravo.jsonl"
    raw = '[from: worker_charlie | one-way] DEATH_NOTICE:{"from":"worker_charlie"}'
    cli = Path(__file__).resolve().parents[1] / "bin" / "log_inbound.py"
    proc = subprocess.run([sys.executable, str(cli),
                           "--log-path", str(log_path),
                           "--run-id", "r1", "--step-id", "7",
                           "--raw-frame", raw],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    rec = json.loads(log_path.read_text().splitlines()[0])
    assert rec["one_way"] is True
    assert rec["from_title"] == "worker_charlie"

"""P01: real CLI/module against a fake cmux Unix socket, never live cmux."""
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
import threading
import uuid

import pytest

from p2plib import cli, registry, surface, tabless


WS = str(uuid.UUID(int=1))
SURF = str(uuid.UUID(int=2))
WIN = str(uuid.UUID(int=3))


def tree(title="producer", surface_ref="surface:9", kind="terminal"):
    return {"windows": [{"id": WIN, "ref": "window:1", "workspaces": [
        {"id": WS, "ref": "workspace:7", "panes": [{"surfaces": [
            {"id": SURF, "ref": surface_ref, "title": title, "type": kind}
        ]}]}]}]}


@contextmanager
def fake_cmux(tmp_path, snapshot, fail_method=None, malformed=False):
    Path("tmp").mkdir(exist_ok=True)
    path = f"tmp/p2p-{uuid.uuid4().hex}.sock"
    calls = []
    errors = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen()
        server.settimeout(5)

        def serve():
            try:
                with server.accept()[0] as client, client.makefile("rwb") as stream:
                    while line := stream.readline():
                        request = json.loads(line)
                        calls.append(request)
                        response = {"id": request["id"], "ok": True,
                                    "result": snapshot if request["method"] == "system.tree" else {}}
                        if request["method"] == fail_method:
                            response = {"id": request["id"], "ok": False,
                                        "error": {"code": "unavailable"}}
                        stream.write(b"not json\n" if malformed else
                                     (json.dumps(response) + "\n").encode())
                        stream.flush()
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            yield path, calls
        finally:
            worker.join(6)
            Path(path).unlink(missing_ok=True)
        assert not worker.is_alive()
        assert not errors


@pytest.fixture
def no_caller(monkeypatch):
    for name in ("CMUX_SURFACE_ID", "CMUX_WORKSPACE_ID", "AGENT_MSG_SURFACE_ID"):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("caller discovery, registry or child process attempted")

    monkeypatch.setattr(surface, "my_surface", forbidden)
    monkeypatch.setattr(registry, "touch_self", forbidden)
    monkeypatch.setattr(registry, "get_self", forbidden)
    monkeypatch.setattr(registry, "all_manifests", forbidden)
    monkeypatch.setattr(registry, "register", forbidden)
    # Popen is the spawn point for subprocess.run and related helpers.
    spawned_argv = []

    def spawn_forbidden(argv, *args, **kwargs):
        spawned_argv.append(argv)
        raise AssertionError("child process attempted")

    monkeypatch.setattr(subprocess, "Popen", spawn_forbidden)
    monkeypatch.setattr(tabless.time, "sleep", lambda _: None)
    return spawned_argv


def invoke(path, message_file, **overrides):
    args = dict(sender="hri_daemon", peer_surface="surface:9",
                workspace="workspace:7", expected_title="producer",
                message_file=str(message_file), socket_path=path)
    args.update(overrides)
    return tabless.send_one_way(**args)


@pytest.mark.parametrize("body", ['{"run_id":"R","reason":"delta_available"}',
                                   '/literal $body `quotes` \\n\nend  ', "x" * 2500])
def test_cli_exact_frame_no_process_argv_no_manifest(tmp_path, no_caller, capsys, body):
    message = tmp_path / "body.txt"
    message.write_text(body)
    before = set(tmp_path.rglob("*"))
    with fake_cmux(tmp_path, tree()) as (path, calls):
        rc = cli.main(["send-one-way", "--sender", "hri_daemon",
                       "--peer-surface", "surface:9", "--workspace", "workspace:7",
                       "--expected-title", "producer", "--message-file", str(message),
                       "--socket-path", path])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "code": "delivered"}
    # Every attempted child spawn is recorded and prohibited.
    assert not any(body in arg for argv in no_caller for arg in argv)
    assert no_caller == []
    assert set(tmp_path.rglob("*")) == before
    assert calls[0]["params"] == {"all_windows": True}
    sends = [call for call in calls if call["method"] == "surface.send_text"]
    assert "".join(call["params"]["text"] for call in sends) == f"[from: hri_daemon | one-way] {body}"
    for call in calls[1:]:
        assert {key: call["params"][key] for key in ("window_id", "workspace_id", "surface_id")} == {
            "window_id": WIN, "workspace_id": WS, "surface_id": SURF}
    assert calls[-1]["method"] == "surface.send_key"
    assert calls[-1]["params"]["key"] == "enter"


@pytest.mark.parametrize("snapshot,overrides,code", [
    (tree(surface_ref="surface:10"), {}, "surface_missing"),
    (tree(), {"workspace": "workspace:8"}, "surface_missing"),
    (tree(title="other"), {}, "title_mismatch"),
    (tree(title="Producer"), {}, "title_mismatch"),
    (tree(kind="browser"), {}, "error"),
])
def test_refusals_never_send(tmp_path, no_caller, snapshot, overrides, code):
    message = tmp_path / "body.txt"
    message.write_text("private body")
    with fake_cmux(tmp_path, snapshot) as (path, calls):
        assert invoke(path, message, **overrides) == {"ok": False, "code": code}
    assert [call["method"] for call in calls] == ["system.tree"]


@pytest.mark.parametrize("method", ["system.tree", "surface.send_text", "surface.send_key"])
def test_transport_failure_is_error(tmp_path, no_caller, method):
    message = tmp_path / "body.txt"
    message.write_text("private body")
    with fake_cmux(tmp_path, tree(), fail_method=method) as (path, calls):
        assert invoke(path, message) == {"ok": False, "code": "error"}
    assert calls[-1]["method"] == method


def test_malformed_response_is_error(tmp_path, no_caller):
    message = tmp_path / "body.txt"
    message.write_text("body")
    with fake_cmux(tmp_path, tree(), malformed=True) as (path, _):
        assert invoke(path, message) == {"ok": False, "code": "error"}


def test_uuid_exact_target(tmp_path, no_caller):
    message = tmp_path / "body.txt"
    message.write_text("body")
    with fake_cmux(tmp_path, tree()) as (path, _):
        assert invoke(path, message, workspace=WS, peer_surface=SURF)["code"] == "delivered"


@pytest.mark.parametrize("overrides", [{"sender": "bad] sender"}, {"workspace": "all"},
                                     {"peer_surface": "producer"}, {"expected_title": ""}])
def test_invalid_inputs_are_error(tmp_path, no_caller, overrides):
    message = tmp_path / "body.txt"
    message.write_text("body")
    assert invoke(str(tmp_path / "absent.sock"), message, **overrides) == {"ok": False, "code": "error"}


def test_file_and_socket_errors(tmp_path, no_caller):
    message = tmp_path / "absent.txt"
    assert invoke(str(tmp_path / "absent.sock"), message)["code"] == "error"
    message.write_text(" ")
    assert invoke(str(tmp_path / "absent.sock"), message)["code"] == "error"
    message.write_text("body")
    assert invoke(str(tmp_path / "absent.sock"), message)["code"] == "error"


def test_no_inline_body_flag():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["send-one-way", "--message", "private"])


def test_stable_socket_defaults_use_account_home(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("HOME", "/unrelated")
    monkeypatch.setenv("CMUX_SOCKET_PATH", "/ignored")
    monkeypatch.setattr(tabless.os, "getuid", lambda: 42)
    monkeypatch.setattr(tabless.pwd, "getpwuid", lambda _: SimpleNamespace(pw_dir="/account"))
    assert tabless._socket_paths(None) == [
        "/account/.local/state/cmux/cmux.sock", "/tmp/cmux.sock",
        "/account/.local/state/cmux/cmux-42.sock", "/tmp/cmux-42.sock"]
    assert tabless._socket_paths("custom.sock") == ["custom.sock"]


def test_default_works_without_pane_or_socket_environment(tmp_path, no_caller, monkeypatch, capsys):
    monkeypatch.delenv("CMUX_SOCKET_PATH", raising=False)
    message = tmp_path / "body.txt"
    message.write_text("body")
    with fake_cmux(tmp_path, tree()) as (path, _):
        monkeypatch.setattr(tabless, "_socket_paths", lambda _: ["tmp/missing-cmux.sock", path])
        assert cli.main(["send-one-way", "--sender", "hri_daemon",
                         "--peer-surface", "surface:9", "--workspace", "workspace:7",
                         "--expected-title", "producer", "--message-file", str(message)]) == 0
    assert json.loads(capsys.readouterr().out)["code"] == "delivered"


def test_does_not_switch_sockets_after_rpc_failure(tmp_path, no_caller, monkeypatch):
    message = tmp_path / "body.txt"
    message.write_text("body")
    with fake_cmux(tmp_path, tree(), fail_method="system.tree") as (path, calls):
        monkeypatch.setattr(tabless, "_socket_paths", lambda _: [path, "tmp/never-connect.sock"])
        assert invoke(None, message)["code"] == "error"
    assert len(calls) == 1


@pytest.mark.parametrize("snapshot,code,rc", [
    (tree(surface_ref="surface:10"), "surface_missing", 2),
    (tree(title="other"), "title_mismatch", 2),
    (tree(kind="browser"), "error", 1),
])
def test_cli_failure_result_and_exit(tmp_path, no_caller, capsys, snapshot, code, rc):
    message = tmp_path / "body.txt"
    message.write_text("body")
    with fake_cmux(tmp_path, snapshot) as (path, _):
        assert cli.main(["send-one-way", "--sender", "hri_daemon",
                         "--peer-surface", "surface:9", "--workspace", "workspace:7",
                         "--expected-title", "producer", "--message-file", str(message),
                         "--socket-path", path]) == rc
    assert json.loads(capsys.readouterr().out) == {"ok": False, "code": code}


@pytest.mark.parametrize("bad_id", [None, "", "surface:9"])
def test_invalid_snapshot_uuid_never_falls_back(tmp_path, no_caller, bad_id):
    message = tmp_path / "body.txt"
    message.write_text("body")
    snapshot = tree()
    snapshot["windows"][0]["workspaces"][0]["panes"][0]["surfaces"][0]["id"] = bad_id
    with fake_cmux(tmp_path, snapshot) as (path, calls):
        assert invoke(path, message) == {"ok": False, "code": "error"}
    assert [call["method"] for call in calls] == ["system.tree"]


def test_unowned_socket_is_not_connected(tmp_path, no_caller, monkeypatch):
    from types import SimpleNamespace
    message = tmp_path / "body.txt"
    message.write_text("body")
    # Connection creation is replaced by a spy so no real socket is needed.
    class NeverConnect:
        def connect(self, *_):
            raise AssertionError("unowned socket connected")
        def close(self):
            pass

    import stat
    monkeypatch.setattr(tabless.os, "stat", lambda _: SimpleNamespace(st_mode=stat.S_IFSOCK,
                                                                       st_uid=tabless.os.getuid() + 1))
    monkeypatch.setattr(tabless.socket, "socket", lambda *_: NeverConnect())
    assert invoke("ignored.sock", message) == {"ok": False, "code": "error"}

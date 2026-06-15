import io
import json

from fluxmcplib import jsonrpc


def test_iter_requests_parses_line_delimited_json():
    stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
                        '\n'  # blank line ignored
                        '{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
    reqs = list(jsonrpc.iter_requests(stdin))
    assert [r["id"] for r in reqs] == [1, 2]


def test_iter_requests_skips_non_json_lines():
    stdin = io.StringIO('not json\n{"jsonrpc":"2.0","id":7,"method":"ping"}\n')
    reqs = list(jsonrpc.iter_requests(stdin))
    assert [r["id"] for r in reqs] == [7]


def test_send_writes_one_compact_line():
    out = io.StringIO()
    jsonrpc.send(out, {"jsonrpc": "2.0", "id": 1, "result": {}})
    text = out.getvalue()
    assert text.endswith("\n")
    assert text.count("\n") == 1
    assert json.loads(text) == {"jsonrpc": "2.0", "id": 1, "result": {}}

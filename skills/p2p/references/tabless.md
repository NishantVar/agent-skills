# Tab-less one-way sender contract

```sh
python3 <p2p-skill>/agent_msg.py send-one-way \
  --sender hri_daemon \
  --peer-surface surface:9 \
  --workspace workspace:7 \
  --expected-title producer \
  --message-file <body-file> \
  [--socket-path <cmux-socket>]
```

All flags except `--socket-path` are required. Sender matches
`[a-z][a-z0-9_]*`. Target accepts exact `surface:N` / `workspace:N` refs or
UUIDs, never titles, indexes or `all`. Expected title is nonempty and checked
case-sensitively. The nonempty UTF-8 body is read only from the file; there is
no inline body flag. Bytes decoded as text, including line endings, whitespace
and slash prefixes, are preserved in exactly
`[from: <sender> | one-way] <body>`. Enter is sent after the framed text.
No bootstrap, reply request or newline substitution is added.

The mode needs no calling pane, never discovers one, never reads or writes a
manifest, and spawns no processes. It calls cmux v2 over a Unix socket:
`system.tree` with `all_windows: true`, then `surface.send_text` in chunks of
at most 1000 characters and `surface.send_key` with `key: enter`. It checks the
surface within the supplied workspace before delivery and pins window,
workspace and surface UUIDs from that snapshot. It never recovers a missing
surface by title or uses the focused target.

## Socket source for launchd

`--socket-path` overrides discovery with one exact socket path. When omitted,
the following stable cmux defaults are tried in this order, where `HOME_ACCOUNT`
is the account home from `pwd.getpwuid(os.getuid())`, independent of pane
environment, and `UID` is `os.getuid()`:

1. `HOME_ACCOUNT/.local/state/cmux/cmux.sock`
2. `/tmp/cmux.sock`
3. `HOME_ACCOUNT/.local/state/cmux/cmux-UID.sock`
4. `/tmp/cmux-UID.sock`

Only socket files owned by the current UID are eligible. Failed connections
advance to the next candidate; the first successful connection is selected.
Once RPC starts, failure never switches sockets or retries delivery.
No `CMUX_SOCKET_PATH`, pane environment, settings, password store or marker
file is read. Issue08's production sender can omit `--socket-path` under the
approved launchd HOME/PATH environment, without daemon config changes.
Custom, nightly and debug sockets require an explicit override; they are not
searched by default. Password authentication is not implemented: a cmux auth
refusal returns `error`. Permission from launchd remains a separate live gate.

The path order and real-account home are grounded in cmux source revision
`d65cbf2e3757bfd0151b9f37d7f9b89760f6aaaa`:
`CLI/CLISocketPathResolver.swift` (`stableImplicitDefaultPaths`,
`stableSocketDirectoryURL`, `stableDefaultSocketPath`) and
`Packages/macOS/CmuxSettings/Sources/CmuxSettings/SocketControl/CmuxStateDirectory.swift`
(`url(homeDirectory:)`). This is the stable path subset, not cmux's marker or
variant discovery. The v2 request protocol follows `CLI/cmux.swift`
(`SocketClient.sendV2`, `buildTreePayload`, `send`, `send-key`).

## Machine results

A syntactically valid invocation emits exactly one JSON object on stdout:

| Exit | JSON | Meaning |
|---|---|---|
| 0 | `{"ok":true,"code":"delivered"}` | cmux accepted framed text and Enter |
| 2 | `{"ok":false,"code":"surface_missing"}` | Exact surface absent in exact workspace |
| 2 | `{"ok":false,"code":"title_mismatch"}` | Exact surface title differs from expected title |
| 1 | `{"ok":false,"code":"error"}` | Invalid values/body file, nonterminal target, unavailable socket, malformed response or RPC failure |

CLI syntax errors (missing/unknown flags) use argparse's stderr and exit 2,
without result JSON. Callers must treat any other exit/output as a generic
failure. These results do not carry `send`'s interactive handoff instructions.
Issue08 maps `delivered` to `delivered`, both `surface_missing` and
`title_mismatch` to `surface_missing`, and anything else to `error`.

`delivered` acknowledges transport acceptance, not agent processing. Title
validation and sending are separate RPCs: a rename between them can race the
check, though pinning UUIDs prevents ref recycling from changing the target.
An error may follow partial text or submission; it is not proof of nondelivery
and must not trigger an automatic replay. Multiline bodies retain literal
newlines, so receiver terminal handling remains relevant; the daemon wake
body is single-line JSON.

## Verification

From the skill-source repository root:

```sh
python -m pytest -q skills/p2p/tests
```

`tests/test_tabless.py` supplies a fake cmux Unix socket. It denies every child
process spawn and caller/registry access, checks the exact reconstructed wire
text and route UUIDs, asserts distinct refusals and generic failures, and tests
stable defaults with cmux environment variables absent. No live cmux or
launchd calls are involved.

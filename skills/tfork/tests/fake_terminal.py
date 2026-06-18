"""An in-memory ``Terminal`` for unit-testing the fork orchestration without a
live terminal multiplexer."""

from tforklib import Terminal


class FakeTerminal(Terminal):
    """Records every call and returns scripted inspection results.

    process            -- what ``pane_process`` returns (None means no
                          process)
    text               -- what ``pane_text`` returns (full scrollback)
    fork_error         -- a ``ForkError`` to raise from ``fork``, or None
    workspace_resolver -- callable(value, cwd) returning the resolved
                          workspace dict, or raising. Tests set this to
                          script workspace_unknown / workspace_ambiguous
                          / created / reused.
    """

    def __init__(self, *, process=None, text="", fork_error=None,
                 session="surface:fake", rename_result=(None, []),
                 workspace_resolver=None, window_resolver=None):
        self.process = process
        self.text = text
        self.fork_error = fork_error
        self.session = session
        self.rename_result = rename_result
        self.workspace_resolver = workspace_resolver
        self.window_resolver = window_resolver
        self.calls = []
        self.killed = []

    @classmethod
    def detect(cls):
        return True

    def fork(self, command, placement, cwd, nonce, anchor=None,
             workspace=None):
        self.calls.append(
            ("fork", command, placement, cwd, nonce, anchor, workspace))
        if self.fork_error is not None:
            raise self.fork_error
        return self.session

    def resolve_workspace(self, value, cwd):
        self.calls.append(("resolve_workspace", value, cwd))
        if self.workspace_resolver is None:
            return {"ref": "workspace:fake", "title": value or "",
                    "created": True}
        return self.workspace_resolver(value, cwd)

    def resolve_window(self, value, workspace, cwd):
        self.calls.append(("resolve_window", value, workspace, cwd))
        if self.window_resolver is None:
            return ({"ref": "window:fake", "created": value == "new"},
                    {"ref": "workspace:fake", "title": workspace or "",
                     "created": True})
        return self.window_resolver(value, workspace, cwd)

    def pane_process(self, session):
        self.calls.append(("pane_process", session))
        return self.process

    def pane_text(self, session):
        self.calls.append(("pane_text", session))
        return self.text

    def kill(self, session):
        self.calls.append(("kill", session))
        self.killed.append(session)

    def rename_tab(self, session, title):
        self.calls.append(("rename_tab", session, title))
        return self.rename_result

    def methods_called(self):
        return [call[0] for call in self.calls]


def make_scrollback(nonce, *, start=True, exit_status=None, body=""):
    """Build a pane-text string the way the sentinel wrapper would leave it.

    ``start`` controls whether the start marker is present (set False to
    simulate paste corruption / wrapper failure); ``exit_status`` controls
    whether the end marker is present and what status it carries (None
    leaves it absent — the long-runner case). ``body`` is any extra output
    that would appear between the markers.
    """
    parts = []
    if start:
        parts.append(f"__tfork_start_{nonce}__")
    if body:
        parts.append(body)
    if exit_status is not None:
        parts.append(f"__tfork_end_{nonce}={exit_status}__")
    return "\n".join(parts) + "\n"

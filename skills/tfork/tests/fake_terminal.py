"""An in-memory ``Terminal`` for unit-testing the fork orchestration without a
live terminal multiplexer."""

from tforklib import Terminal


class FakeTerminal(Terminal):
    """Records every call and returns scripted inspection results.

    process     -- what ``pane_process`` returns (None means no/dead process)
    text        -- what ``pane_text`` returns (the pane's full scrollback)
    fork_error  -- a ``ForkError`` to raise from ``fork``, or None
    """

    def __init__(self, *, process=None, text="", fork_error=None,
                 session="surface:fake", rename_result=(None, [])):
        self.process = process
        self.text = text
        self.fork_error = fork_error
        self.session = session
        self.rename_result = rename_result
        self.calls = []
        self.killed = []

    @classmethod
    def detect(cls):
        return True

    def fork(self, command, placement, cwd, nonce, anchor=None):
        self.calls.append(
            ("fork", command, placement, cwd, nonce, anchor))
        if self.fork_error is not None:
            raise self.fork_error
        return self.session

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

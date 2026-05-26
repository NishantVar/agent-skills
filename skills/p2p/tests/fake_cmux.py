"""In-memory cmux model used by tests.

`FakeCmux` builds a synthetic `cmux tree --all` document from a list
of (workspace_ref, workspace_title, surface_ref, tty, title) tuples
and exposes `apply()` to monkeypatch the points where p2plib calls out
to surface/transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeSurface:
    workspace_ref: str
    workspace_title: str
    surface_ref: str
    tty: str = ""
    title: str = ""


@dataclass
class FakeCmux:
    surfaces: list[FakeSurface] = field(default_factory=list)
    # Records every transport.send_buffer call: (surface, ws, text).
    sent: list[tuple[str, str | None, str]] = field(default_factory=list)
    # Records every transport.read_screen call.
    reads: list[tuple[str, str | None]] = field(default_factory=list)
    # Scripted scrollback returned by read_screen, keyed by surface_ref.
    screen_text: dict[str, str] = field(default_factory=dict)

    def add(self, **kw) -> FakeSurface:
        s = FakeSurface(**kw)
        self.surfaces.append(s)
        return s

    def tree(self) -> dict:
        # Group surfaces by workspace.
        workspaces: dict[str, dict] = {}
        for s in self.surfaces:
            ws = workspaces.setdefault(s.workspace_ref, {
                "ref": s.workspace_ref,
                "title": s.workspace_title,
                "panes": [{"surfaces": []}],
            })
            ws["panes"][0]["surfaces"].append({
                "ref": s.surface_ref,
                "tty": s.tty,
                "title": s.title,
            })
        return {"windows": [{"workspaces": list(workspaces.values())}]}

    def apply(self, monkeypatch, *, my_surface_ref: str | None = None):
        """Patch surface/transport call seams. `my_surface_ref` is what
        `surface.my_surface()` will return for the duration of the test."""
        from p2plib import surface, transport

        monkeypatch.setattr(surface, "cmux_tree", self.tree)
        monkeypatch.setattr(surface, "my_surface",
                            lambda: my_surface_ref)

        def fake_send(surf, ws, text):
            self.sent.append((surf, ws, text))

        def fake_read(surf, ws, lines=300):  # noqa: ARG001
            self.reads.append((surf, ws))
            return self.screen_text.get(surf, "")

        def fake_rename(surf, _ws, new_title):
            # Mirror cmux: update the in-memory surface title so the next
            # tree read reflects the rename. Without this, subsequent
            # sweeps that compare manifest.title vs current cmux title
            # would reap a just-renamed agent's own manifest.
            for s in self.surfaces:
                if s.surface_ref == surf:
                    s.title = new_title
                    return None
            return None

        monkeypatch.setattr(transport, "send_buffer", fake_send)
        monkeypatch.setattr(transport, "read_screen", fake_read)
        monkeypatch.setattr(transport, "rename_tab", fake_rename)

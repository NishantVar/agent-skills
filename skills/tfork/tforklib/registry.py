"""The self-building TOML classification registry.

Maps a command's first word to whether it is a coding agent. The file at
``REGISTRY_PATH`` is built automatically from use and works fine when absent;
all read and write errors are swallowed so registry I/O never blocks or fails
a fork.
"""

import tomllib
from pathlib import Path

REGISTRY_PATH = Path.home() / ".config" / "tfork" / "registry.toml"

REGISTRY_HEADER = """\
# tfork classification registry.
#
# Maps a command's first word to whether it is a coding agent:
#   "<command>" = true    -> verified as a coding agent
#   "<command>" = false   -> verified as a plain command
#
# This file is built automatically from use and works fine when absent.
# To correct a misclassification, edit the boolean on the relevant line
# (or pass --type on the next run).
"""


def read_registry(path=REGISTRY_PATH):
    """Return the classification map. A missing or unparsable file -> ``{}``."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, bool)}


def write_registry_entry(word, is_agent, path=REGISTRY_PATH):
    """Persist one classification. Any write error is swallowed: registry I/O
    never blocks or fails a fork."""
    path = Path(path)
    registry = read_registry(path)
    registry[word] = bool(is_agent)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [REGISTRY_HEADER.rstrip("\n"), ""]
        for key in sorted(registry):
            esc = key.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'"{esc}" = {"true" if registry[key] else "false"}')
        path.write_text("\n".join(lines) + "\n")
    except OSError:
        pass

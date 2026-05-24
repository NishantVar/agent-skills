"""Put the skill directory (for ``fork_terminal``) and the tests directory
(for ``fake_terminal``) on the import path."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (_HERE.parent, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import sys
from pathlib import Path

# Put the skill dir on sys.path so `import fluxmcplib...` works under pytest.
SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

import stat
import textwrap

import pytest


def _write_exec(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fake_binaries(tmp_path):
    """A skills-root tree of stub binaries that echo a JSON record of how they
    were invoked (argv, the two surface env vars, and any --message-file body).
    Lets gateway tests assert argv mapping, env injection, and verbatim
    passthrough without a live cmux or runtime.
    """
    root = tmp_path / "skills"
    stub = textwrap.dedent('''\
        #!/usr/bin/env python3
        import json, os, sys
        argv = sys.argv[1:]
        rec = {
            "argv": argv,
            "env_AGENT_MSG_SURFACE_ID": os.environ.get("AGENT_MSG_SURFACE_ID"),
            "env_TFORK_SURFACE_ID": os.environ.get("TFORK_SURFACE_ID"),
        }
        if "--message-file" in argv:
            p = argv[argv.index("--message-file") + 1]
            with open(p) as fh:
                rec["message_body"] = fh.read()
        print(json.dumps(rec))
    ''')
    for skill, fname in (("p2p", "agent_msg.py"), ("afork", "afork.py"),
                         ("tfork", "fork_terminal.py")):
        _write_exec(root / skill / fname, stub)
    return root

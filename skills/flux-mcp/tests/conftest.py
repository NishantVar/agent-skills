import sys
from pathlib import Path

# Put the skill dir on sys.path so `import fluxmcplib...` works under pytest.
SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

import sys
from pathlib import Path

# Put the skill dir on the path so `import aforklib` works from the tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

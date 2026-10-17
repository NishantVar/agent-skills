import sys
from pathlib import Path

# Allow `from lib.X import Y` in tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

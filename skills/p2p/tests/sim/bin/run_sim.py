#!/usr/bin/env python3
"""Spawn the sim_driver pane in cmux and exit.

This is the human-facing entrypoint. After this script returns, the
sim_driver agent runs the simulation autonomously in its own pane.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


SIM_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default=None,
                   help="ULID/uuid for this run; auto-generated if omitted")
    args = p.parse_args()

    run_id = args.run_id or uuid.uuid4().hex[:16]
    run_dir = SIM_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Render the driver prompt with concrete paths
    template = (SIM_ROOT / "driver_prompt.md").read_text()
    rendered = template.replace("{sim_root}", str(SIM_ROOT)).replace("{run_id}", run_id)
    rendered_path = run_dir / "driver_prompt.rendered.md"
    rendered_path.write_text(rendered)

    agent_cmd = os.environ.get("P2P_SIM_AGENT_CMD", "claude")

    print(f"run_id={run_id}")
    print(f"run_dir={run_dir}")
    print(f"rendered driver prompt: {rendered_path}")
    print(f"agent spawn cmd: {agent_cmd}  (override via P2P_SIM_AGENT_CMD env var)")
    print()
    print("Next: spawn the sim_driver pane in cmux with the rendered prompt as")
    print("its first user-turn input. Example via tfork skill:")
    print(f"  fork {agent_cmd} --placement new-workspace -- {agent_cmd}")
    print(f"  then paste {rendered_path} as the first user prompt.")
    print()
    print("The driver will read P2P_SIM_AGENT_CMD from its own env when spawning")
    print("worker panes, so export it before launching this script if you use a")
    print("non-default alias (e.g. `cm`).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

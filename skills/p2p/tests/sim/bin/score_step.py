#!/usr/bin/env python3
"""Driver CLI: score one step's assertions and print a result JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.catalog import load_catalog
from lib.score import score_assertion


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True, type=Path)
    p.add_argument("--step-id", required=True, type=int)
    p.add_argument("--log-dir", required=True, type=Path,
                   help="runs/<run_id>/ directory")
    p.add_argument("--phase", default="main", choices=["main", "post_recovery"])
    args = p.parse_args()

    cat = load_catalog(args.catalog)
    step = next((s for s in cat.steps if s.id == args.step_id), None)
    if step is None:
        print(json.dumps({"error": f"no step_id={args.step_id}"}))
        return 2

    assertions = step.assertions if args.phase == "main" else step.post_recovery_assertions
    results = []
    overall_pass = True
    for a in assertions:
        r = score_assertion(a, step_id=args.step_id, log_dir=args.log_dir)
        results.append({"assertion": a, "passed": r.passed, "reason": r.reason})
        if not r.passed:
            overall_pass = False

    print(json.dumps({
        "step_id": args.step_id,
        "name": step.name,
        "phase": args.phase,
        "classification": step.classification,
        "overall_pass": overall_pass,
        "results": results,
    }, indent=2))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())

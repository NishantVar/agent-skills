#!/usr/bin/env python3
"""Driver CLI: age a manifest in the shared p2p registry by title."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.manifest_aging import DEFAULT_REGISTRY, age_manifest, find_manifest_by_title


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True, help="manifest title to age")
    p.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY)
    p.add_argument("--ttl-seconds", type=int, default=1800)
    p.add_argument("--margin-seconds", type=int, default=60)
    args = p.parse_args()

    target = find_manifest_by_title(args.registry_dir, args.title)
    if target is None:
        print(f"no manifest with title={args.title!r} in {args.registry_dir}", file=sys.stderr)
        return 2
    age_manifest(target, ttl_seconds=args.ttl_seconds, margin_seconds=args.margin_seconds)
    print(str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

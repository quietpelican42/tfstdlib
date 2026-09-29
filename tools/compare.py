#!/usr/bin/env python3
"""Compare tfstdlib with tests/data/gold.jsonl and print a summary and the mismatches."""

from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import gold  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    skip = tuple(a[1:] for a in args if a.startswith('-'))
    only = [a for a in args if not a.startswith('-')]
    meta, recs = gold.load_gold()
    counts: collections.Counter[str] = collections.Counter()
    shown = 0
    for r in recs:
        if only and not r.expr.startswith(tuple(only)):
            continue
        if skip and r.expr.startswith(skip):
            continue
        status, detail = gold.compare(r)
        counts[status] += 1
        if status != "ok":
            shown += 1
            if shown <= int(__import__("os").environ.get("MAXSHOW", "60")):
                print(f"[{status}] {r.expr}\n         {detail}")
    total = sum(counts.values())
    print(f"\n{counts['ok']}/{total} equal ({100 * counts['ok'] / max(total, 1):.2f}%)  " + ", ".join(f"{k}={v}" for k, v in counts.items() if k != "ok"))
    return 0 if counts["ok"] == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

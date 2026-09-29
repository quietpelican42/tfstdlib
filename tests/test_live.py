"""Live checks against a real `terraform console`. Skipped loudly when terraform is not installed."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

import gold

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

TERRAFORM = shutil.which("terraform")

pytestmark = pytest.mark.skipif(
    TERRAFORM is None,
    reason="terraform is not on PATH: install Terraform (https://developer.hashicorp.com/terraform/install) to run the live tests",
)


def test_sample_against_live_terraform() -> None:
    import make_gold

    _meta, recs = gold.load_gold()
    sample = recs[:: max(1, len(recs) // 60)]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(gold.DATA / "templates", work / "templates")
        mismatches = []
        for rec in sample:
            live = make_gold.evaluate(work, rec.expr)
            if bool(live["ok"]) != rec.ok:
                mismatches.append(f"outcome differs for {rec.expr!r}")
                continue
            if rec.ok and live.get("json") != rec.json:
                mismatches.append(f"value differs for {rec.expr!r}: {live.get('json')!r} vs {rec.json!r}")
        # the recorded corpus was produced by a specific Terraform version; report drift instead of hiding it
        assert not mismatches, "installed terraform disagrees with tests/data/gold.jsonl:\n" + "\n".join(mismatches)

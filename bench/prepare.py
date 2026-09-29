"""Write exprs.txt and gold_min.json (inputs for run_checkov.py, run_pyhcl2.py, score.py) from the gold corpus."""

import json
from pathlib import Path

gold = Path(__file__).resolve().parent.parent / "tests" / "data" / "gold.jsonl"
recs = [json.loads(ln) for ln in gold.read_text(encoding="utf-8").split("\n")[1:] if ln]
Path("exprs.txt").write_text("\n".join(r["expr"] for r in recs), encoding="utf-8")
Path("gold_min.json").write_text(json.dumps([[r["expr"], r["ok"], r.get("json")] for r in recs]), encoding="utf-8")
print(len(recs), "expressions")

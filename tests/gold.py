"""Helpers that compare tfstdlib against the recorded `terraform console` output."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from tfstdlib.errors import FuncFail
from tfstdlib import Context, TerraformError, evaluate_value, format_value
from tfstdlib.jsonutil import json_encode

DATA = Path(__file__).resolve().parent / "data"
GOLD = DATA / "gold.jsonl"


@dataclass
class Record:
    expr: str
    ok: bool
    raw: str | None
    json: str | None
    json_error: str | None
    error: str | None


def load_gold() -> tuple[dict[str, object], list[Record]]:
    lines = [ln for ln in GOLD.read_text(encoding="utf-8").split("\n") if ln]
    meta = json.loads(lines[0])
    recs = []
    for ln in lines[1:]:
        d = json.loads(ln)
        recs.append(Record(d["expr"], d["ok"], d.get("raw"), d.get("json"), d.get("json_error"), d.get("error")))
    return meta, recs


def norm_raw(s: str) -> str:
    return s.replace(str(DATA), "<cwd>")


def compare(rec: Record) -> tuple[str, str]:
    """Return (status, detail); status is 'ok', 'outcome', 'raw', 'json' or 'crash'."""
    cwd = os.getcwd()
    try:
        os.chdir(DATA)
        try:
            val = evaluate_value(rec.expr, Context(base_dir=str(DATA)))
            err = None
        except TerraformError as exc:
            val = None
            err = f"{type(exc).__name__}: {exc.message}"
    except Exception as exc:  # noqa: BLE001
        return "crash", f"{type(exc).__name__}: {exc}"
    finally:
        os.chdir(cwd)
    if rec.ok != (err is None):
        return "outcome", f"terraform {'ok' if rec.ok else 'error'}; tfstdlib {err or 'ok'}"
    if err is not None:
        return "ok", ""
    raw = format_value(val)
    assert rec.raw is not None
    if raw != rec.raw:
        return "raw", f"terraform {rec.raw!r}\n         tfstdlib  {raw!r}"
    try:
        js: str | None = json_encode(val)
    except FuncFail:
        js = None
    if rec.json is None and rec.json_error is not None and js is not None:
        return "json", f"terraform refuses to jsonencode this ({rec.json_error[-60:]!r}); tfstdlib gave {js!r}"
    if rec.json is not None:
        if js != rec.json:
            return "json", f"terraform {rec.json!r}\n         tfstdlib  {js!r}"
    return "ok", ""

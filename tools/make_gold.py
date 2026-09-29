#!/usr/bin/env python3
"""Generate the gold corpus by running every expression through `terraform console`.

    python tools/make_gold.py [--out tests/data/gold.jsonl] [--workers 8] [--limit N]

Each expression is evaluated twice in a scratch working directory (stdin comes
from a file, never a terminal): once as written, once wrapped in jsonencode().
The record keeps Terraform's console rendering, the jsonencode() text and the
error text, so tests can compare values, types and error/no-error outcomes.
The scratch directory is deleted at the end and its path is scrubbed from the
recorded output.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import corpus_collections  # noqa: E402
import corpus_encoding  # noqa: E402
import corpus_strings  # noqa: E402

DATA = HERE.parent / "tests" / "data"


def all_expressions() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for mod in (corpus_strings, corpus_collections, corpus_encoding):
        for e in mod.all_exprs():
            if "\n" in e or e in seen:
                continue
            seen.add(e)
            out.append(e)
    return out


def terraform_version() -> str:
    r = subprocess.run(
        ["terraform", "version", "-json"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL
    )
    return str(json.loads(r.stdout)["terraform_version"])


ERR_RE = re.compile(r"^\s*Error: ", re.M)


def run_console(workdir: Path, expr: str) -> tuple[bool, str]:
    """Return (ok, text). Stdin is a file."""
    infile = workdir.parent / f".in-{workdir.name}.txt"
    infile.write_text(expr)
    env = dict(os.environ)
    env.pop("TF_LOG", None)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_CLI_ARGS"] = ""
    with infile.open("rb") as fh:
        try:
            r = subprocess.run(
                ["terraform", "console", "-no-color"],
                stdin=fh,
                capture_output=True,
                timeout=30,
                cwd=workdir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT"
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0 or ERR_RE.search(out) or ERR_RE.search(err):
        return False, (err + out).strip()
    return True, out.rstrip("\n")


def unquote_hcl(s: str) -> str:
    """Decode the quoted string terraform console prints for a string value."""
    s = s.strip()
    assert s.startswith('"') and s.endswith('"'), s[:80]
    body = s[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n in '"\\':
                out.append(n)
                i += 2
            elif n == "n":
                out.append("\n")
                i += 2
            elif n == "r":
                out.append("\r")
                i += 2
            elif n == "t":
                out.append("\t")
                i += 2
            elif n in "abfv":
                out.append({"a": "\a", "b": "\b", "f": "\f", "v": "\v"}[n])
                i += 2
            elif n == "x":
                out.append(chr(int(body[i + 2 : i + 4], 16)))
                i += 4
            elif n == "u":
                out.append(chr(int(body[i + 2 : i + 6], 16)))
                i += 6
            elif n == "U":
                out.append(chr(int(body[i + 2 : i + 10], 16)))
                i += 10
            else:
                raise ValueError(f"unknown escape \\{n}")
        elif c == "$" and body.startswith("$${", i):
            out.append("${")
            i += 3
        elif c == "%" and body.startswith("%%{", i):
            out.append("%{")
            i += 3
        else:
            out.append(c)
            i += 1
    return "".join(out)


def scrub(text: str, workdir: Path) -> str:
    text = text.replace(str(workdir), "<cwd>")
    text = text.replace(str(workdir.resolve()), "<cwd>")
    home = os.path.expanduser("~")
    return text.replace(home, "~")


def evaluate(workdir: Path, expr: str) -> dict[str, object]:
    rec: dict[str, object] = {"expr": expr}
    ok, text = run_console(workdir, expr)
    if not ok:
        rec.update(ok=False, error=scrub(text, workdir))
        return rec
    rec["ok"] = True
    rec["raw"] = scrub(text, workdir)
    jok, jtext = run_console(workdir, f"jsonencode({expr})")
    if jok:
        try:
            rec["json"] = scrub(unquote_hcl(jtext), workdir)
        except Exception as exc:  # pragma: no cover - diagnostic only
            rec["json_error"] = f"undecodable: {exc}: {jtext[:200]}"
    else:
        rec["json_error"] = scrub(jtext, workdir)
    return rec


def worker(args: tuple[Path, list[str]]) -> list[dict[str, object]]:
    workdir, exprs = args
    return [evaluate(workdir, e) for e in exprs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA / "gold.jsonl"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--scratch", default=os.environ.get("TFSTDLIB_SCRATCH", ""), help="parent dir for the temporary working directories")
    ns = ap.parse_args()

    exprs = all_expressions()
    if ns.limit:
        exprs = exprs[: ns.limit]
    version = terraform_version()
    parent = ns.scratch or None
    root = Path(tempfile.mkdtemp(prefix="tfgold-", dir=parent)).resolve()
    try:
        dirs = []
        for i in range(ns.workers):
            d = root / f"w{i}"
            d.mkdir()
            shutil.copytree(DATA / "templates", d / "templates")
            dirs.append(d)
        chunks: list[list[str]] = [[] for _ in dirs]
        order: list[tuple[int, int]] = []
        for idx, e in enumerate(exprs):
            w = idx % len(dirs)
            order.append((w, len(chunks[w])))
            chunks[w].append(e)
        with concurrent.futures.ThreadPoolExecutor(len(dirs)) as pool:
            results = list(pool.map(worker, zip(dirs, chunks)))
        recs = [results[w][j] for w, j in order]
    finally:
        shutil.rmtree(root, ignore_errors=True)

    with open(ns.out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"terraform_version": version, "count": len(recs)}) + "\n")
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_ok = sum(1 for r in recs if r["ok"])
    print(f"terraform {version}: {len(recs)} expressions, {n_ok} values, {len(recs) - n_ok} errors -> {ns.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

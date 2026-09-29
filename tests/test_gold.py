"""Every recorded `terraform console` result must be reproduced exactly (value, type and error/no-error)."""

from __future__ import annotations

import re
from collections import defaultdict

import pytest

import gold

_META, _RECORDS = gold.load_gold()


def _group(expr: str) -> str:
    m = re.match(r"(?:provider::\w+::|core::)?([A-Za-z_][\w-]*)\(", expr)
    return m.group(1) if m else "expressions"


_GROUPS: dict[str, list[gold.Record]] = defaultdict(list)
for _r in _RECORDS:
    _GROUPS[_group(_r.expr)].append(_r)


def test_corpus_size() -> None:
    assert len(_RECORDS) >= 1500
    assert _META["terraform_version"]
    values = sum(1 for r in _RECORDS if r.ok)
    errors = len(_RECORDS) - values
    assert values > 500 and errors > 200


@pytest.mark.parametrize("name", sorted(_GROUPS))
def test_matches_terraform(name: str) -> None:
    bad = []
    for rec in _GROUPS[name]:
        status, detail = gold.compare(rec)
        if status != "ok":
            bad.append(f"[{status}] {rec.expr}\n    {detail}")
    assert not bad, f"{len(bad)} of {len(_GROUPS[name])} differ from terraform console:\n" + "\n".join(bad[:15])

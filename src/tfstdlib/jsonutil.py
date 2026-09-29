"""JSON encoding of Terraform values, shared by ``jsonencode`` and ``format``."""

from __future__ import annotations

from .errors import FuncFail
from .numbers import Number
from .values import Map, Null, TfSet, Unknown, Value


def json_string(s: str) -> str:
    """Encode ``s`` the way Go's encoding/json does with HTML escaping on."""
    out = ['"']
    for ch in s:
        c = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif c < 0x20 or ch in "<>&" or c in (0x2028, 0x2029):
            out.append(f"\\u{c:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def json_encode(v: Value) -> str:
    """Encode a known Terraform value as compact JSON with sorted object keys."""
    if isinstance(v, Unknown):
        raise FuncFail("cannot serialize an unknown value as JSON")
    if isinstance(v, Null):
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json_string(v)
    if isinstance(v, Number):
        if v.is_inf:
            raise FuncFail("cannot serialize infinity as JSON")
        return v.text()
    if isinstance(v, (list, tuple, TfSet)):
        return "[" + ",".join(json_encode(x) for x in v) + "]"
    if isinstance(v, dict):
        keys = sorted(v)
        return "{" + ",".join(json_string(k) + ":" + json_encode(v[k]) for k in keys) + "}"
    raise TypeError(f"not a Terraform value: {v!r}")


__all__ = ["json_encode", "json_string", "Map"]

"""Render values the way ``terraform console`` prints them."""

from __future__ import annotations

from .numbers import Number
from .values import (
    BOOL,
    NUMBER,
    STRING,
    DynamicT,
    ListT,
    MapT,
    Map,
    Null,
    Object,
    SetT,
    TfSet,
    Type,
    Unknown,
    Value,
    PrimT,
)


def quote_string(s: str) -> str:
    """Quote ``s`` like Go's strconv.Quote, which is what the console prints."""
    out = ['"']
    for ch in s:
        c = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch in _SHORT:
            out.append(_SHORT[ch])
        elif ch.isprintable() or ch == " ":
            out.append(ch)
        elif c < 0x20 or c == 0x7F:
            out.append(f"\\x{c:02x}")
        elif c < 0x10000:
            out.append(f"\\u{c:04x}")
        else:
            out.append(f"\\U{c:08x}")
    out.append('"')
    return "".join(out)


_SHORT = {"\a": "\\a", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\v": "\\v"}


def _type_desc(t: Type) -> str:
    if isinstance(t, DynamicT):
        return "dynamic"
    return t.friendly()


def format_value(v: Value, indent: int = 0) -> str:
    """Return the ``terraform console`` rendering of ``v``."""
    if isinstance(v, Unknown):
        return "(known after apply)"
    if isinstance(v, Null):
        t = v.type
        if isinstance(t, DynamicT):
            return "null"
        if t == STRING:
            return "tostring(null)"
        if t == NUMBER:
            return "tonumber(null)"
        if t == BOOL:
            return "tobool(null)"
        if isinstance(t, ListT):
            return f"tolist(null) /* of {_type_desc(t.elem)} */"
        if isinstance(t, SetT):
            return f"toset(null) /* of {_type_desc(t.elem)} */"
        if isinstance(t, MapT):
            return f"tomap(null) /* of {_type_desc(t.elem)} */"
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Number):
        return v.text()
    if isinstance(v, str):
        if "\n" in v:
            if indent == 0:
                return "<<EOT\n" + v + "\nEOT"
            pad0 = " " * indent
            return "<<-EOT\n" + "\n".join(pad0 + ln for ln in v.split("\n")) + "\n" + pad0 + "EOT"
        return quote_string(v)
    pad = " " * indent
    inner = " " * (indent + 2)
    if isinstance(v, (list, tuple, TfSet)):
        wrap = "tolist(" if isinstance(v, list) else "toset(" if isinstance(v, TfSet) else ""
        close = ")" if wrap else ""
        items = list(v)
        if not items:
            return f"{wrap}[]{close}"
        body = "".join(f"{inner}{format_value(x, indent + 2)},\n" for x in items)
        return f"{wrap}[\n{body}{pad}]{close}"
    if isinstance(v, dict):
        wrap = "tomap(" if isinstance(v, Map) else ""
        close = ")" if wrap else ""
        if not v:
            return f"{wrap}{{}}{close}"
        body = "".join(f"{inner}{quote_string(k)} = {format_value(x, indent + 2)}\n" for k, x in v.items())
        return f"{wrap}{{\n{body}{pad}}}{close}"
    raise TypeError(f"not a Terraform value: {v!r}")


__all__ = ["format_value", "quote_string", "Object", "PrimT"]

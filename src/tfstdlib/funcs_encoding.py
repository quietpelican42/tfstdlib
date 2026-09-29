"""Encoding functions: JSON, CSV, base64, URL, text encodings."""

from __future__ import annotations

import base64
import gzip as _gzip
import json
import re
import struct
import urllib.parse
import zlib
from typing import Any

from .errors import ArgumentError, FuncFail
from .jsonutil import json_encode
from .numbers import Number
from .registry import Param, register
from .values import DYNAMIC, NULL, STRING, Null, Object, Unknown, Value

S = STRING

# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


@register("jsonencode", Param("val", DYNAMIC, allow_null=True, allow_unknown=True))
def _jsonencode(v: Value) -> Value:
    if isinstance(v, Unknown):
        return Unknown()
    return json_encode(v)


_SURR = re.compile("[\ud800-\udfff]")


def _clean(s: str) -> str:
    return _SURR.sub("�", s)


def _from_json(x: Any) -> Value:
    if x is None:
        return NULL
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        return _clean(x)
    if isinstance(x, _Num):
        n = Number.parse(x.text)
        assert n is not None
        return n
    if isinstance(x, list):
        return tuple(_from_json(i) for i in x)
    if isinstance(x, dict):
        return Object({_clean(k): _from_json(v) for k, v in x.items()})
    raise FuncFail("unsupported JSON value")


class _Num:
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


def _bad_const(name: str) -> Any:
    raise ValueError(f"invalid character {name[0]!r} looking for beginning of value")


@register("jsondecode", Param("str", S))
def _jsondecode(s: str) -> Value:
    dec = json.JSONDecoder(parse_float=_Num, parse_int=_Num, parse_constant=_bad_const)
    text = s.lstrip(" \t\r\n")
    if not text:
        raise FuncFail("EOF")
    try:
        obj, end = dec.raw_decode(text)
    except (ValueError, RecursionError) as exc:
        raise FuncFail(str(exc)) from None
    if text[end:].strip(" \t\r\n"):
        raise FuncFail("extraneous data after JSON object")
    return _from_json(obj)


# ---------------------------------------------------------------------------
# base64, url
# ---------------------------------------------------------------------------

_B64_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")


def _b64_decode(s: str) -> bytes | None:
    t = s.replace("\r", "").replace("\n", "")
    if len(t) % 4:
        return None
    body = t.rstrip("=")
    pad = len(t) - len(body)
    if pad > 2 or any(c not in _B64_CHARS for c in body):
        return None
    if len(body) % 4 == 1:
        return None
    try:
        return base64.b64decode(t, validate=True)
    except Exception:
        return None


@register("base64encode", Param("str", S))
def _b64encode(s: str) -> Value:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


@register("base64decode", Param("str", S))
def _b64decode(s: str) -> Value:
    raw = _b64_decode(s)
    if raw is None:
        raise FuncFail(f'failed to decode base64 data "{s}"')
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise FuncFail("the result of decoding the provided string is not valid UTF-8") from None


def go_gzip(data: bytes) -> bytes:
    """A gzip stream shaped like Go's compress/gzip output (empty stored block at the end)."""
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = comp.compress(data) + comp.flush(zlib.Z_SYNC_FLUSH) + b"\x01\x00\x00\xff\xff"
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
    trailer = struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF)
    return header + body + trailer


@register("base64gzip", Param("str", S))
def _b64gzip(s: str) -> Value:
    return base64.b64encode(go_gzip(s.encode("utf-8"))).decode("ascii")


@register("urlencode", Param("str", S))
def _urlencode(s: str) -> Value:
    return urllib.parse.quote_plus(s, safe="")


__all__ = ["go_gzip", "_gzip", "Null", "ArgumentError"]

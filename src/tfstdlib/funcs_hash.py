"""Hashing and identifier functions."""

from __future__ import annotations

import base64
import hashlib
import time
import uuid as _uuid

from .errors import FuncFail
from .registry import Param, register
from .values import STRING, Value

S = STRING


def _digest(name: str, s: str) -> bytes:
    return hashlib.new(name, s.encode("utf-8")).digest()


@register("md5", Param("str", S))
def _md5(s: str) -> Value:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


@register("sha1", Param("str", S))
def _sha1(s: str) -> Value:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


@register("sha256", Param("str", S))
def _sha256(s: str) -> Value:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@register("sha512", Param("str", S))
def _sha512(s: str) -> Value:
    return hashlib.sha512(s.encode("utf-8")).hexdigest()


@register("base64sha256", Param("str", S))
def _b64sha256(s: str) -> Value:
    return base64.b64encode(_digest("sha256", s)).decode("ascii")


@register("base64sha512", Param("str", S))
def _b64sha512(s: str) -> Value:
    return base64.b64encode(_digest("sha512", s)).decode("ascii")


_NAMESPACES = {
    "dns": _uuid.NAMESPACE_DNS,
    "url": _uuid.NAMESPACE_URL,
    "oid": _uuid.NAMESPACE_OID,
    "x500": _uuid.NAMESPACE_X500,
}


def parse_uuid(s: str) -> _uuid.UUID:
    """Parse the UUID forms google/uuid accepts, raising ``ValueError(reason)``."""
    n = len(s)
    if n == 36:
        text = s
    elif n == 36 + 9 and s.lower().startswith("urn:uuid:"):
        text = s[9:]
    elif n == 36 + 2 and s.startswith("{") and s.endswith("}"):
        text = s[1:-1]
    elif n == 32:
        text = f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"
    else:
        raise ValueError(f"invalid UUID length: {n}")
    if text[8] != "-" or text[13] != "-" or text[18] != "-" or text[23] != "-":
        raise ValueError("invalid UUID format")
    hexs = text.replace("-", "")
    if len(hexs) != 32 or not all(c in "0123456789abcdefABCDEF" for c in hexs):
        raise ValueError("invalid UUID format")
    return _uuid.UUID(hexs)


@register("uuidv5", Param("namespace", S), Param("name", S))
def _uuidv5(ns: str, name: str) -> Value:
    nsid = _NAMESPACES.get(ns)
    if nsid is None:
        try:
            nsid = parse_uuid(ns)
        except ValueError as exc:
            raise FuncFail(f"uuidv5() doesn't support namespace {ns} ({exc})") from None
    return str(_uuid.uuid5(nsid, name))


@register("uuid")
def _uuid4() -> Value:
    return str(_uuid.uuid4())


@register("timestamp")
def _timestamp() -> Value:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@register("plantimestamp")
def _plantimestamp() -> Value:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

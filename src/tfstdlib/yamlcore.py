"""A small YAML reader and writer that follow what Terraform's yamldecode/yamlencode do.

Terraform decodes with a go-yaml derived parser (YAML 1.1 style scalar
resolution: ``yes``/``no``/``on``/``off``/``y``/``n`` are booleans, ``0o17`` and
``0x1f`` are integers, dates become RFC 3339 strings) and encodes with the
same emitter, double-quoting every string. This module implements those
behaviours without a dependency. It covers block and flow collections, quoted
and block scalars, anchors, aliases, merge keys and the core tags. Multi-document
streams, complex mapping keys and the more exotic tags are rejected.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .console import quote_string  # noqa: F401  (re-exported for symmetry)
from .funcs_datetime import Timestamp, days_from_civil
from .numbers import Number
from .values import NULL, Map, Null, Object, STRING, TfSet, Unknown, Value

# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------


class YamlError(Exception):
    """A YAML syntax or type error."""


_BOOL_TRUE = {"y", "Y", "yes", "Yes", "YES", "true", "True", "TRUE", "on", "On", "ON"}
_BOOL_FALSE = {"n", "N", "no", "No", "NO", "false", "False", "FALSE", "off", "Off", "OFF"}
_NULLS = {"", "~", "null", "Null", "NULL"}
_INF = {".inf", ".Inf", ".INF", "+.inf", "+.Inf", "+.INF"}
_NINF = {"-.inf", "-.Inf", "-.INF"}
_NAN = {".nan", ".NaN", ".NAN"}
_INT_RE = re.compile(r"[-+]?[0-9]+")
_HEX_RE = re.compile(r"[-+]?0x[0-9a-fA-F]+")
_OCT_RE = re.compile(r"[-+]?0o[0-7]+")
_FLOAT_RE = re.compile(r"[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?")
_TS_RE = re.compile(
    r"([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})(?:(?:[Tt]|[ \t]+)([0-9]{1,2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]*))?(?:[ \t]*(Z|[-+][0-9]{1,2}(?::[0-9]{2})?))?)?"
)


def _timestamp(text: str) -> str | None:
    m = _TS_RE.fullmatch(text)
    if not m:
        return None
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    h = int(m[4] or 0)
    mi = int(m[5] or 0)
    s = int(m[6] or 0)
    if not (1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60 and s < 60):
        return None
    dim = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
    if d > dim:
        return None
    off = 0
    zone = m[8]
    if zone and zone != "Z":
        sign = -1 if zone[0] == "-" else 1
        parts = zone[1:].split(":")
        off = sign * (int(parts[0]) * 3600 + (int(parts[1]) * 60 if len(parts) > 1 else 0))
    secs = days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s - off
    return Timestamp(secs, 0, off).rfc3339()


def _int_value(text: str) -> Number | None:
    if _INT_RE.fullmatch(text):
        return Number.parse(text)
    if _HEX_RE.fullmatch(text):
        neg = text.startswith("-")
        body = text.lstrip("+-")[2:]
        n = Number.from_int(int(body, 16), 512)
        return n.neg() if neg else n
    if _OCT_RE.fullmatch(text):
        neg = text.startswith("-")
        body = text.lstrip("+-")[2:]
        n = Number.from_int(int(body, 8), 512)
        return n.neg() if neg else n
    return None


def resolve_plain(text: str) -> Value:
    """Resolve an unquoted, untagged scalar."""
    if text in _NULLS:
        return NULL
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    iv = _int_value(text)
    if iv is not None:
        return iv
    if _FLOAT_RE.fullmatch(text):
        n = Number.parse(text)
        if n is not None:
            return n
    if text in _INF:
        return Number.infinity(False)
    if text in _NINF:
        return Number.infinity(True)
    if text in _NAN:
        raise YamlError("floating point NaN is not supported")
    if text[:1].isdigit():
        ts = _timestamp(text)
        if ts is not None:
            return ts
    return text


_ESC = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ", "P": " "}
_PLAIN_BAD_START = set("@`%")
_WS = " \t"


class _Parser:
    def __init__(self, text: str) -> None:
        text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
        self.ends_nl = text.endswith("\n")
        self.lines = text.split("\n")
        if self.ends_nl:
            self.lines.pop()
        self.pos = 0
        self.anchors: dict[str, Value] = {}

    # -- line helpers --
    def _skip_blank(self) -> None:
        while self.pos < len(self.lines):
            t = self.lines[self.pos].strip(_WS)
            if t == "" or t.startswith("#"):
                self.pos += 1
            else:
                break

    def _peek(self) -> tuple[int, str] | None:
        """Indent and text of the next content line without consuming it."""
        i = self.pos
        while i < len(self.lines):
            raw = self.lines[i]
            t = raw.strip(_WS)
            if t == "" or t.startswith("#"):
                i += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if raw[indent : indent + 1] == "\t":
                raise YamlError("found character that cannot start any token")
            if raw.startswith("---") and (len(raw) == 3 or raw[3] in " \t") or raw.startswith("...") and (len(raw) == 3 or raw[3] in " \t"):
                return (-1, raw)
            return indent, raw[indent:]
        return None

    # -- document --
    def parse_document(self) -> Value:
        # directives
        while self.pos < len(self.lines) and self.lines[self.pos].startswith("%"):
            self.pos += 1
        self._skip_blank()
        if self.pos >= len(self.lines):
            raise YamlError("missing start of document")
        first = self.lines[self.pos]
        if first.startswith("---") and (len(first) == 3 or first[3] in " \t"):
            rest = first[3:].strip(_WS)
            if rest and not rest.startswith("#"):
                self.lines[self.pos] = first[3:].lstrip(_WS)
            else:
                self.pos += 1
        value = self.parse_node(-1)
        nxt = self._peek()
        if nxt is not None:
            if nxt[0] == -1:
                line = nxt[1]
                if line.startswith("..."):
                    return value
                raise YamlError("unexpected extra content after value")
            raise YamlError("unexpected extra content after value")
        return value

    # -- nodes --
    def parse_node(self, parent: int) -> Value:
        nxt = self._peek()
        if nxt is None or nxt[0] == -1:
            return NULL
        indent, text = nxt
        if indent <= parent:
            return NULL
        self._skip_blank()
        return self._parse_block(indent, parent)

    def _parse_block(self, indent: int, parent: int) -> Value:
        raw = self.lines[self.pos]
        text = raw[indent:]
        props = self._properties(text)
        if props[0] or props[1]:
            # node properties on their own line (or before an inline node)
            anchor, tag, rest, consumed = props
            if rest.strip(_WS) == "" or rest.strip(_WS).startswith("#"):
                self.pos += 1
                val = self.parse_node(parent)
                if isinstance(val, Null) and tag is not None:
                    return self._finish(anchor, tag, val, "", False)
                return self._finish(anchor, tag, val, None, False)
            # properties followed by content on the same line: decide if it is a block map key
            if self._find_key_end(rest) is not None and not rest.startswith(("[", "{")):
                # anchor/tag apply to the first key
                self.lines[self.pos] = " " * indent + rest
                return self._parse_block(indent, parent)
            self.lines[self.pos] = " " * (indent + consumed) + rest
            v = self._inline(indent + consumed, parent, anchor, tag)
            return v
        if text == "-" or text.startswith("- "):
            return self._parse_seq(indent)
        if text == "?" or text.startswith("? "):
            return self._parse_map(indent)
        if self._find_key_end(text) is not None:
            return self._parse_map(indent)
        return self._inline(indent, parent, None, None)

    def _properties(self, text: str) -> tuple[str | None, str | None, str, int]:
        anchor = tag = None
        i = 0
        while i < len(text):
            if text[i] == "&" and anchor is None:
                j = i + 1
                while j < len(text) and text[j] not in " \t,[]{}":
                    j += 1
                anchor = text[i + 1 : j]
            elif text[i] == "!" and tag is None:
                j = i + 1
                if j < len(text) and text[j] == "<":
                    k = text.find(">", j)
                    if k < 0:
                        raise YamlError("did not find expected tag URI")
                    j = k + 1
                else:
                    while j < len(text) and text[j] not in " \t,[]{}":
                        j += 1
                tag = text[i:j]
            else:
                break
            k = j
            while k < len(text) and text[k] in _WS:
                k += 1
            i = k
        return anchor, tag, text[i:], i

    def _finish(self, anchor: str | None, tag: str | None, val: Value, raw: str | None, quoted: bool) -> Value:
        if tag is not None:
            val = self._apply_tag(tag, val, raw, quoted)
        if anchor:
            self.anchors[anchor] = val
        return val

    def _apply_tag(self, tag: str, val: Value, raw: str | None, quoted: bool) -> Value:
        if tag.startswith("!<") and tag.endswith(">"):
            tag = tag[2:-1]
            if tag.startswith("tag:yaml.org,2002:"):
                tag = "!!" + tag[len("tag:yaml.org,2002:") :]
        if not tag.startswith("!!"):
            raise YamlError(f'unsupported tag "{tag}"')
        kind = tag[2:]
        full = "tag:yaml.org,2002:" + kind
        if raw is not None:  # scalar
            if kind == "str":
                return raw
            if quoted:
                return val
            if kind == "int":
                iv = _int_value(raw)
                if iv is None:
                    raise YamlError(f'cannot parse "{raw}" as {full}')
                return iv
            if kind == "float":
                if _FLOAT_RE.fullmatch(raw):
                    n = Number.parse(raw)
                    assert n is not None
                    return n
                iv = _int_value(raw)
                if iv is not None:
                    return iv
                if raw in _INF or raw in _NINF:
                    return resolve_plain(raw)
                raise YamlError(f'cannot parse "{raw}" as {full}')
            if kind == "bool":
                if raw in _BOOL_TRUE:
                    return True
                if raw in _BOOL_FALSE:
                    return False
                raise YamlError(f'cannot parse "{raw}" as {full}')
            if kind == "null":
                return NULL
            if kind == "timestamp":
                ts = _timestamp(raw)
                if ts is None:
                    raise YamlError(f'cannot parse "{raw}" as {full}')
                return ts
            if kind == "binary":
                return raw
            if kind in ("seq", "map", "set", "omap", "pairs"):
                raise YamlError(f"can't interpret scalar as {full}")
            raise YamlError(f'unsupported tag "{tag}"')
        if kind == "seq" and isinstance(val, tuple):
            return val
        if kind == "map" and isinstance(val, dict):
            return val
        if kind in ("str", "int", "float", "bool", "null", "timestamp", "binary", "set", "omap", "pairs", "seq", "map"):
            what = "sequence" if isinstance(val, tuple) else "mapping"
            raise YamlError(f"can't interpret {what} as {full}")
        raise YamlError(f'unsupported tag "{tag}"')

    # -- key detection --
    @staticmethod
    def _find_key_end(text: str) -> int | None:
        """Index of the ':' that ends a mapping key on this line, or None."""
        if not text or text[0] in "[{":
            # flow collection used as a key: only when followed by ':' after the closer
            if text and text[0] in "[{":
                depth = 0
                for i, ch in enumerate(text):
                    if ch in "[{":
                        depth += 1
                    elif ch in "]}":
                        depth -= 1
                        if depth == 0:
                            rest = text[i + 1 :]
                            if rest.startswith(":") and (len(rest) == 1 or rest[1] in " \t"):
                                return i + 1
                            return None
            return None
        i = 0
        n = len(text)
        if text[0] in "\"'":
            q = text[0]
            i = 1
            while i < n:
                if q == '"' and text[i] == "\\":
                    i += 2
                    continue
                if text[i] == q:
                    if q == "'" and i + 1 < n and text[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            while i < n and text[i] in _WS:
                i += 1
            if i < n and text[i] == ":" and (i + 1 == n or text[i + 1] in " \t"):
                return i
            return None
        if text[0] == "*":
            pass
        while i < n:
            ch = text[i]
            if ch == "#" and i > 0 and text[i - 1] in _WS:
                return None
            if ch == ":" and (i + 1 == n or text[i + 1] in " \t"):
                return i
            i += 1
        return None

    # -- sequences --
    def _parse_seq(self, indent: int) -> Value:
        items: list[Value] = []
        while True:
            nxt = self._peek()
            if nxt is None or nxt[0] == -1:
                break
            ind, text = nxt
            if ind != indent or not (text == "-" or text.startswith("- ")):
                if ind > indent:
                    raise YamlError("did not find expected '-' indicator")
                break
            self._skip_blank()
            raw = self.lines[self.pos]
            rest = raw[indent + 1 :]
            stripped = rest.strip(_WS)
            if stripped == "" or stripped.startswith("#"):
                self.pos += 1
                items.append(self.parse_node(indent))
            else:
                lead = len(rest) - len(rest.lstrip(_WS))
                self.lines[self.pos] = " " * (indent + 1 + lead) + rest[lead:]
                items.append(self._parse_block(indent + 1 + lead, indent))
        return tuple(items)

    # -- mappings --
    def _parse_map(self, indent: int) -> Value:
        out: dict[str, Value] = {}
        merges: list[Value] = []
        while True:
            nxt = self._peek()
            if nxt is None or nxt[0] == -1:
                break
            ind, text = nxt
            if ind > indent:
                raise YamlError("did not find expected key")
            if ind < indent:
                break
            if text == "-" or text.startswith("- "):
                raise YamlError("did not find expected key")
            self._skip_blank()
            raw = self.lines[self.pos]
            text = raw[indent:]
            explicit = text == "?" or text.startswith("? ")
            if explicit:
                rest = text[1:]
                lead = len(rest) - len(rest.lstrip(_WS))
                self.lines[self.pos] = " " * (indent + 1 + lead) + rest[lead:]
                if rest.strip(_WS) == "":
                    self.pos += 1
                key_val = self.parse_node(indent)
                nx = self._peek()
                value: Value = NULL
                if nx is not None and nx[0] == indent and nx[1].startswith(":"):
                    self._skip_blank()
                    raw2 = self.lines[self.pos]
                    r2 = raw2[indent + 1 :]
                    if r2.strip(_WS) == "":
                        self.pos += 1
                        value = self._block_value(indent)
                    else:
                        lead2 = len(r2) - len(r2.lstrip(_WS))
                        self.lines[self.pos] = " " * (indent + 1 + lead2) + r2[lead2:]
                        value = self._inline(indent + 1 + lead2, indent, None, None)
                self._store(out, merges, key_val, value)
                continue
            props = self._properties(text)
            kanchor, ktag, ktext, kcons = props
            end = self._find_key_end(ktext)
            if end is None:
                raise YamlError("did not find expected key")
            key_src = ktext[:end].strip(_WS)
            key_val = self._scalar_key(key_src, ktag, kanchor)
            rest = ktext[end + 1 :]
            col = indent + kcons + end + 1
            stripped = rest.strip(_WS)
            if stripped == "" or stripped.startswith("#"):
                self.pos += 1
                value = self._block_value(indent)
            else:
                lead = len(rest) - len(rest.lstrip(_WS))
                self.lines[self.pos] = " " * (col + lead) + rest[lead:]
                value = self._inline(col + lead, indent, None, None, in_map_value=True)
            self._store(out, merges, key_val, value)
        result = dict(out)
        for m in merges:
            if isinstance(m, dict):
                for k, v in m.items():
                    result.setdefault(k, v)
            else:
                kind = "tuple" if isinstance(m, tuple) else "number" if isinstance(m, Number) else "string" if isinstance(m, str) else "value"
                raise YamlError(f"cannot merge {kind} into mapping")
        return Object(result)

    def _block_value(self, indent: int) -> Value:
        nxt = self._peek()
        if nxt is not None and nxt[0] == indent and (nxt[1] == "-" or nxt[1].startswith("- ")):
            self._skip_blank()
            return self._parse_seq(indent)
        return self.parse_node(indent)

    def _scalar_key(self, src: str, tag: str | None, anchor: str | None) -> Value:
        if src[:1] in "[{":
            raise YamlError("only strings are allowed as mapping keys")
        if src[:1] == "*":
            name = src[1:]
            if name not in self.anchors:
                raise YamlError(f'reference to undefined anchor "{name}"')
            return self.anchors[name]
        if src[:1] in "\"'":
            val, _ = self._quoted_from_text(src)
            return val
        if src == "<<":
            return _MERGE
        v = resolve_plain(src)
        if tag is not None:
            v = self._apply_tag(tag, v, src, False)
        if anchor:
            self.anchors[anchor] = v
        return v

    def _store(self, out: dict[str, Value], merges: list[Value], key: Value, value: Value) -> None:
        if key is _MERGE:
            if isinstance(value, tuple):
                raise YamlError("cannot merge tuple into mapping")
            merges.append(value)
            return
        if isinstance(key, Null):
            raise YamlError("mapping key cannot be null")
        if isinstance(key, bool):
            key = "true" if key else "false"
        elif isinstance(key, Number):
            key = key.text()
        elif not isinstance(key, str):
            raise YamlError("only strings are allowed as mapping keys")
        out[key] = value

    # -- inline (scalar / flow / alias / block scalar) --
    def _inline(self, col: int, parent: int, anchor: str | None, tag: str | None, in_map_value: bool = False) -> Value:
        raw = self.lines[self.pos]
        text = raw[col:]
        a2, t2, rest, cons = self._properties(text)
        if a2 or t2:
            anchor = anchor or a2
            tag = tag or t2
            col += cons
            text = rest
            if text.strip(_WS) == "" or text.strip(_WS).startswith("#"):
                self.pos += 1
                val = self.parse_node(parent)
                if isinstance(val, Null) and tag is not None:
                    return self._finish(anchor, tag, val, "", False)
                return self._finish(anchor, tag, val, None, False)
        first = text[:1]
        if first == "*":
            name = re.split(r"[ \t,\]}]", text[1:], maxsplit=1)[0]
            if name not in self.anchors:
                raise YamlError(f'reference to undefined anchor "{name}"')
            self.pos += 1
            return self.anchors[name]
        if first in "|>":
            return self._finish(anchor, tag, self._block_scalar(text, parent), None, False) if tag is None else self._finish(anchor, tag, self._block_scalar(text, parent), "", True)
        if first in "[{":
            src = self._gather_flow(col)
            p = _Flow(src, self)
            val = p.parse()
            return self._finish(anchor, tag, val, None, False)
        if first in "\"'":
            val, raw_text = self._quoted_multi(col)
            return self._finish(anchor, tag, val, raw_text, True)
        if text.startswith("- ") or text == "-":
            raise YamlError("block sequence entries are not allowed in this context")
        if text.startswith("? "):
            raise YamlError("mapping keys are not allowed in this context")
        if first in _PLAIN_BAD_START:
            raise YamlError("found character that cannot start any token")
        return self._plain(col, parent, anchor, tag)

    def _plain(self, col: int, parent: int, anchor: str | None, tag: str | None) -> Value:
        raw = self.lines[self.pos]
        text = self._strip_comment(raw[col:])
        if ": " in text or text.endswith(":"):
            raise YamlError("mapping values are not allowed in this context")
        parts = [text.strip(_WS)]
        blanks = 0
        i = self.pos + 1
        consumed = self.pos + 1
        while i < len(self.lines):
            ln = self.lines[i]
            t = ln.strip(_WS)
            if t == "":
                blanks += 1
                i += 1
                continue
            if t.startswith("#"):
                break
            ind = len(ln) - len(ln.lstrip(" "))
            if ind <= parent or (ln.startswith("---") or ln.startswith("...")) and ind == 0:
                break
            cont = self._strip_comment(ln.strip(_WS))
            if ": " in cont or cont.endswith(":"):
                raise YamlError("mapping values are not allowed in this context")
            if blanks:
                parts.append("\n" * blanks)
            else:
                parts.append(" ")
            parts.append(cont.strip(_WS))
            blanks = 0
            consumed = i + 1
            i += 1
        self.pos = consumed
        joined = "".join(parts)
        # fix folding: a run of blank lines is newlines only (no extra space)
        joined = re.sub(r" (\n+) ", r"\1", joined)
        val = resolve_plain(joined)
        if tag is not None:
            val = self._apply_tag(tag, val, joined, False)
        if anchor:
            self.anchors[anchor] = val
        return val

    @staticmethod
    def _strip_comment(s: str) -> str:
        for i in range(len(s)):
            if s[i] == "#" and (i == 0 or s[i - 1] in _WS):
                return s[:i].rstrip(_WS)
        return s.rstrip(_WS)

    # -- quoted scalars --
    def _quoted_from_text(self, text: str) -> tuple[str, int]:
        val, used = _scan_quoted(text)
        return val, used

    def _quoted_multi(self, col: int) -> tuple[str, str]:
        src = self.lines[self.pos][col:]
        start_pos = self.pos
        q = src[0]
        buf = src
        i = self.pos
        while True:
            try:
                val, used = _scan_quoted(buf)
                break
            except _Unterminated:
                i += 1
                if i >= len(self.lines):
                    raise YamlError("found unexpected end of stream") from None
                buf = buf + "\n" + self.lines[i]
        tail = buf[used:].strip(_WS)
        if tail and not tail.startswith("#"):
            raise YamlError("did not find expected key")
        self.pos = i + 1
        _ = (start_pos, q)
        return val, val

    # -- flow --
    def _gather_flow(self, col: int) -> str:
        buf = self.lines[self.pos][col:]
        i = self.pos
        while True:
            if _flow_balanced(buf):
                break
            i += 1
            if i >= len(self.lines):
                raise YamlError("did not find expected ',' or ']'" if buf.lstrip().startswith("[") else "did not find expected ',' or '}'")
            buf += "\n" + self.lines[i]
        self.pos = i + 1
        return buf

    # -- block scalars --
    def _block_scalar(self, header: str, parent: int) -> Value:
        m = re.fullmatch(r"([|>])([-+]?)([1-9]?)([-+]?)\s*(?:#.*)?", header.strip(_WS))
        if not m:
            raise YamlError("did not find expected comment or line break")
        style = m[1]
        chomp = m[2] or m[4]
        explicit = int(m[3]) if m[3] else 0
        self.pos += 1
        content: list[str] = []
        indent: int | None = None
        if explicit:
            indent = max(parent, 0) + explicit if parent >= 0 else explicit
        i = self.pos
        while i < len(self.lines):
            ln = self.lines[i]
            if ln.strip(" ") == "":
                content.append("")
                i += 1
                continue
            ind = len(ln) - len(ln.lstrip(" "))
            if indent is None:
                if ind <= parent:
                    break
                indent = ind
            if ind < indent:
                break
            if ind == 0 and (ln.startswith("---") or ln.startswith("...")):
                break
            content.append(ln[indent:])
            i += 1
        # trailing blank lines belong to chomping
        trail = 0
        while content and content[-1] == "":
            content.pop()
            trail += 1
        self.pos = i - 0
        if not content and trail == 0:
            return Null(STRING)
        if style == "|":
            body = "\n".join(content)
        else:
            body = _fold(content)
        if not content:
            return "\n" * trail if chomp == "+" else ""
        at_end = i >= len(self.lines)
        if chomp == "-":
            return body
        if chomp == "+":
            return body + "\n" * (trail + (1 if (self.ends_nl or not at_end) else 0))
        return body + ("\n" if (self.ends_nl or not at_end) else "")


class _Merge:
    pass


_MERGE: Any = _Merge()


class _Unterminated(Exception):
    pass


def _fold(lines: list[str]) -> str:
    out: list[str] = []
    prev_more = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        more = ln.startswith((" ", "\t"))
        if i > 0:
            # count preceding blanks
            pass
        out.append(ln)
        i += 1
    # rebuild with folding rules
    res: list[str] = []
    blanks = 0
    started = False
    prev_more = False
    for ln in lines:
        if ln == "":
            blanks += 1
            continue
        more = ln.startswith((" ", "\t"))
        if not started:
            res.append("\n" * blanks + ln)
            started = True
        elif blanks:
            sep = "\n" * (blanks + (1 if (more or prev_more) else 0))
            res.append(sep + ln)
        else:
            res.append(("\n" if (more or prev_more) else " ") + ln)
        blanks = 0
        prev_more = more
    return "".join(res)


def _scan_quoted(text: str) -> tuple[str, int]:
    q = text[0]
    i = 1
    n = len(text)
    out: list[str] = []
    pending_ws = ""  # trailing whitespace on the current line (dropped before a fold)
    while i < n:
        ch = text[i]
        if q == "'":
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    out.append(pending_ws + "'")
                    pending_ws = ""
                    i += 2
                    continue
                return "".join(out) + pending_ws, i + 1
        else:
            if ch == '"':
                return "".join(out) + pending_ws, i + 1
            if ch == "\\":
                if i + 1 >= n:
                    raise _Unterminated
                e = text[i + 1]
                if e == "\n":
                    out.append(pending_ws)
                    pending_ws = ""
                    i += 2
                    while i < n and text[i] in _WS:
                        i += 1
                    continue
                if e in "xuU":
                    width = {"x": 2, "u": 4, "U": 8}[e]
                    hx = text[i + 2 : i + 2 + width]
                    if len(hx) < width:
                        raise _Unterminated
                    if not all(c in "0123456789abcdefABCDEF" for c in hx):
                        raise YamlError("did not find expected hexdecimal number")
                    cp = int(hx, 16)
                    if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
                        raise YamlError("found invalid Unicode character escape code")
                    out.append(pending_ws + chr(cp))
                    pending_ws = ""
                    i += 2 + width
                    continue
                if e not in _ESC:
                    raise YamlError("found unknown escape character")
                out.append(pending_ws + _ESC[e])
                pending_ws = ""
                i += 2
                continue
        if ch == "\n":
            # line folding
            j = i
            blanks = 0
            while j < n and text[j] == "\n":
                blanks += 1
                j += 1
                while j < n and text[j] in _WS:
                    j += 1
            if j >= n:
                raise _Unterminated
            out.append("\n" * (blanks - 1) if blanks > 1 else " ")
            pending_ws = ""
            i = j
            continue
        if ch in _WS:
            pending_ws += ch
        else:
            out.append(pending_ws + ch)
            pending_ws = ""
        i += 1
    raise _Unterminated


def _flow_balanced(s: str) -> bool:
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in "\"'":
            try:
                _, used = _scan_quoted(s[i:])
            except _Unterminated:
                return False
            except YamlError:
                return True
            i += used
            continue
        if ch == "#" and (i == 0 or s[i - 1] in _WS + "\n"):
            while i < n and s[i] != "\n":
                i += 1
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        i += 1
    return depth <= 0


class _Flow:
    def __init__(self, src: str, parser: _Parser) -> None:
        self.s = src
        self.i = 0
        self.n = len(src)
        self.p = parser

    def ws(self) -> None:
        while self.i < self.n:
            c = self.s[self.i]
            if c in " \t\n":
                self.i += 1
            elif c == "#" and (self.i == 0 or self.s[self.i - 1] in " \t\n"):
                while self.i < self.n and self.s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def parse(self) -> Value:
        self.ws()
        v = self.node()
        self.ws()
        if self.i < self.n:
            raise YamlError("did not find expected <document start>")
        return v

    def node(self) -> Value:
        self.ws()
        if self.i >= self.n:
            raise YamlError("did not find expected node content")
        anchor, tag, _rest, cons = self.p._properties(self.s[self.i :])
        if anchor or tag:
            self.i += cons
            self.ws()
        c = self.s[self.i] if self.i < self.n else ""
        if c == "[":
            v = self.seq()
            return self.p._finish(anchor, tag, v, None, False)
        if c == "{":
            v = self.map()
            return self.p._finish(anchor, tag, v, None, False)
        if c == "*":
            j = self.i + 1
            while j < self.n and self.s[j] not in " \t\n,[]{}":
                j += 1
            name = self.s[self.i + 1 : j]
            self.i = j
            if name not in self.p.anchors:
                raise YamlError(f'reference to undefined anchor "{name}"')
            return self.p.anchors[name]
        if c in "\"'":
            qval, used = _scan_quoted(self.s[self.i :])
            self.i += used
            return self.p._finish(anchor, tag, qval, qval, True)
        if c == "":
            raise YamlError("did not find expected node content")
        j = self.i
        while j < self.n:
            ch = self.s[j]
            if ch in ",[]{}\n":
                break
            if ch == ":" and (j + 1 >= self.n or self.s[j + 1] in " \t\n,[]{}"):
                break
            if ch == "#" and j > self.i and self.s[j - 1] in " \t":
                break
            j += 1
        text = self.s[self.i : j].strip(_WS)
        self.i = j
        if text[:1] in _PLAIN_BAD_START:
            raise YamlError("found character that cannot start any token")
        val = resolve_plain(text) if text or tag else NULL
        if tag is not None:
            val = self.p._apply_tag(tag, val, text, False)
        if anchor:
            self.p.anchors[anchor] = val
        return val

    def seq(self) -> Value:
        self.i += 1
        items: list[Value] = []
        while True:
            self.ws()
            if self.i >= self.n:
                raise YamlError("did not find expected ',' or ']'")
            if self.s[self.i] == "]":
                self.i += 1
                return tuple(items)
            items.append(self.node())
            self.ws()
            if self.i < self.n and self.s[self.i] == ",":
                self.i += 1
            elif self.i < self.n and self.s[self.i] == "]":
                continue
            else:
                raise YamlError("did not find expected ',' or ']'")

    def map(self) -> Value:
        self.i += 1
        out: dict[str, Value] = {}
        merges: list[Value] = []
        while True:
            self.ws()
            if self.i >= self.n:
                raise YamlError("did not find expected ',' or '}'")
            if self.s[self.i] == "}":
                self.i += 1
                break
            key = self.node()
            if isinstance(key, str) and key == "<<":
                key = _MERGE
            self.ws()
            value: Value = NULL
            if self.i < self.n and self.s[self.i] == ":":
                self.i += 1
                self.ws()
                if self.i < self.n and self.s[self.i] not in ",}":
                    value = self.node()
            self.p._store(out, merges, key, value)
            self.ws()
            if self.i < self.n and self.s[self.i] == ",":
                self.i += 1
            elif self.i < self.n and self.s[self.i] == "}":
                continue
            else:
                raise YamlError("did not find expected ',' or '}'")
        result = dict(out)
        for m in merges:
            if isinstance(m, dict):
                for k, v in m.items():
                    result.setdefault(k, v)
            else:
                raise YamlError("cannot merge value into mapping")
        return Object(result)


def _nfc(v: Value) -> Value:
    from .values import deep_nfc

    return deep_nfc(v)


def decode(text: str) -> Value:
    """Decode a YAML document into a Terraform value."""
    p = _Parser(text)
    return _nfc(p.parse_document())


# ---------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------


def _is_printable(ch: str) -> bool:
    c = ord(ch)
    if c == 0x0A or 0x20 <= c <= 0x7E:
        return True
    if 0xA0 <= c <= 0xD7FF or 0xE000 <= c <= 0xFFFD:
        return c != 0xFEFF
    return False


def _is_break(ch: str) -> bool:
    return ch in "\r\n\x85  "


_DQ = {0x00: "0", 0x07: "a", 0x08: "b", 0x09: "t", 0x0A: "n", 0x0B: "v", 0x0C: "f", 0x0D: "r", 0x1B: "e", 0x22: '"', 0x5C: "\\", 0x85: "N", 0xA0: "_", 0x2028: "L", 0x2029: "P"}


def _dq(s: str, col: int, indent: int, allow_breaks: bool = True) -> str:
    out = ['"']
    col += 1
    spaces = False
    n = len(s)
    i = 0
    while i < n:
        ch = s[i]
        c = ord(ch)
        if not _is_printable(ch) or _is_break(ch) or ch in '"\\' or c == 0xFEFF:
            if c in _DQ:
                esc = "\\" + _DQ[c]
            elif c <= 0xFF:
                esc = f"\\x{c:02X}"
            elif c <= 0xFFFF:
                esc = f"\\u{c:04X}"
            else:
                esc = f"\\U{c:08X}"
            out.append(esc)
            col += len(esc)
            spaces = False
        elif ch == " ":
            if allow_breaks and not spaces and col > 80 and 0 < i < n - 1:
                out.append("\n" + " " * indent)
                col = indent
                if s[i + 1] == " ":
                    out.append("\\")
                    col += 1
            else:
                out.append(ch)
                col += 1
            spaces = True
        else:
            out.append(ch)
            col += 1
            spaces = False
        i += 1
    out.append('"')
    return "".join(out)


def _block_allowed(s: str) -> bool:
    if s == "":
        return False
    prev_space = False
    for ch in s:
        if not _is_printable(ch) or (ch != "\n" and _is_break(ch)):
            return False
        if ch == "\n" and prev_space:
            return False
        prev_space = ch == " "
    if s.endswith(" "):
        return False
    return True


def _literal(s: str, indent: int) -> str:
    hint = "2" if s[0] in " \n" else ""
    if not s.endswith("\n"):
        chomp = "-"
    elif len(s) == 1 or s[-2] == "\n":
        chomp = "+"
    else:
        chomp = ""
    body = s[:-1] if s.endswith("\n") else s
    if chomp == "+":
        body = s[:-1]
    lines = body.split("\n")
    pad = " " * indent
    return "|" + hint + chomp + "\n" + "\n".join((pad + ln) if ln else "" for ln in lines)


def _scalar_text(v: Value, col: int, indent: int, simple_key: bool = False) -> tuple[str, bool]:
    """Return (text, is_block). Block scalars start with '|' and carry their own newlines."""
    if isinstance(v, Null):
        return "null", False
    if isinstance(v, bool):
        return ("true" if v else "false"), False
    if isinstance(v, Number):
        return v.text() if not v.is_inf else ("+Inf" if not v.negative else "-Inf"), False
    assert isinstance(v, str)
    if "\n" in v and not simple_key and _block_allowed(v):
        return _literal(v, indent), True
    return _dq(v, col, indent, allow_breaks=not simple_key), False


def encode(v: Value) -> str:
    """Encode a Terraform value the way ``yamlencode`` does."""
    if isinstance(v, Unknown):
        raise YamlError("cannot encode unknown value")
    if isinstance(v, (Null, bool, Number, str)):
        text, block = _scalar_text(v, 0, 2)
        if block or isinstance(v, str):
            return text + "\n"
        return text + "\n...\n"
    if _items(v) == []:
        return "[]\n"
    if isinstance(v, dict) and not v:
        return "{}\n"
    lines: list[str] = []
    _collection(v, 0, lines)
    return "\n".join(lines) + "\n"


def _items(v: Value) -> list[Value] | None:
    if isinstance(v, (list, tuple, TfSet)):
        return list(v)
    return None


def _collection(v: Value, indent: int, lines: list[str]) -> None:
    """Emit a non-empty sequence or mapping whose entries start at column ``indent``."""
    pad = " " * indent
    items = _items(v)
    if items is not None:
        for it in items:
            _entry(pad + "-", it, indent, lines, True)
        return
    assert isinstance(v, dict)
    for k in sorted(v):
        if "\n" in k or len(k) > 128:
            ktext, _ = _scalar_text(k, 0, indent + 2)
            lines.append(pad + "? " + ktext)
            _entry(pad + ":", v[k], indent, lines, False)
        else:
            _entry(pad + _dq(k, indent, indent + 2, allow_breaks=False) + ":", v[k], indent, lines, False)


def _entry(head: str, val: Value, indent: int, lines: list[str], dash: bool) -> None:
    items = _items(val)
    if items is not None:
        if not items:
            lines.append(head + " []")
        elif dash:
            sub: list[str] = []
            _collection(val, indent + 2, sub)
            sub[0] = head + " " + sub[0][indent + 2 :]
            lines.extend(sub)
        else:
            lines.append(head)
            _collection(val, indent, lines)
        return
    if isinstance(val, dict):
        if not val:
            lines.append(head + " {}")
        elif dash:
            sub = []
            _collection(val, indent + 2, sub)
            sub[0] = head + " " + sub[0][indent + 2 :]
            lines.extend(sub)
        else:
            lines.append(head)
            _collection(val, indent + 2, lines)
        return
    text, _block = _scalar_text(val, len(head) + 1, indent + 2)
    lines.append(head + " " + text)


__all__ = ["decode", "encode", "YamlError", "resolve_plain", "Map", "Object", "unicodedata"]

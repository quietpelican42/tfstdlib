"""String functions."""

from __future__ import annotations

import unicodedata

from .errors import ArgumentError, FuncFail
from .graphemes import grapheme_count, split_graphemes
from .jsonutil import json_encode
from .numbers import Number
from .re2 import RegexError, compile_regex, expand
from .registry import Param, register
from .values import (
    BOOL,
    DYNAMIC,
    NULL,
    NUMBER,
    STRING,
    ListT,
    Null,
    Object,
    TfSet,
    Unknown,
    Value,
    convert,
    type_of,
)
from .errors import ConversionError

S = STRING

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1
_WHOLE_MSG = "value must be a whole number, between -9223372036854775808 and 9223372036854775807."


def whole_int(n: Number) -> int:
    """Convert a number argument to an int64 as ``gocty.FromCtyValue`` would."""
    if n.is_inf or not n.is_int():
        raise FuncFail(_WHOLE_MSG)
    v = n.to_int()
    if v < INT64_MIN or v > INT64_MAX:
        raise FuncFail(_WHOLE_MSG)
    return v


# Go's unicode.IsSpace
_GO_SPACE = "\t\n\v\f\r \x85\xa0                　"

_SPECIAL_UP = {0x1FB3: 0x1FBC, 0x1FC3: 0x1FCC, 0x1FF3: 0x1FFC}


def go_upper_char(c: str) -> str:
    cp = ord(c)
    if 0x1F80 <= cp <= 0x1FAF and (cp & 0xF) < 8:
        return chr(cp + 8)
    if cp in _SPECIAL_UP:
        return chr(_SPECIAL_UP[cp])
    u = c.upper()
    return u if len(u) == 1 else c


def go_lower_char(c: str) -> str:
    if c == "İ":
        return "i"
    lo = c.lower()
    return lo if len(lo) == 1 else c


def go_title_char(c: str) -> str:
    cp = ord(c)
    if 0x1F80 <= cp <= 0x1FAF and (cp & 0xF) < 8:
        return chr(cp + 8)
    if cp in _SPECIAL_UP:
        return chr(_SPECIAL_UP[cp])
    t = c.title()
    return t if len(t) == 1 else c


def _is_separator(c: str) -> bool:
    cp = ord(c)
    if cp <= 0x7F:
        return not (c.isalnum() or c == "_")
    if unicodedata.category(c)[0] == "L" or unicodedata.category(c) == "Nd":
        return False
    return c in _GO_SPACE


# ---------------------------------------------------------------------------
# simple functions
# ---------------------------------------------------------------------------


@register("upper", Param("str", S))
def _upper(s: str) -> Value:
    return "".join(go_upper_char(c) for c in s)


@register("lower", Param("str", S))
def _lower(s: str) -> Value:
    return "".join(go_lower_char(c) for c in s)


@register("title", Param("str", S))
def _title(s: str) -> Value:
    out = []
    prev = " "
    for c in s:
        out.append(go_title_char(c) if _is_separator(prev) else c)
        prev = c
    return "".join(out)


@register("chomp", Param("str", S))
def _chomp(s: str) -> Value:
    return s.rstrip("\r\n")


@register("trimspace", Param("str", S))
def _trimspace(s: str) -> Value:
    return s.strip(_GO_SPACE)


@register("trim", Param("str", S), Param("cutset", S))
def _trim(s: str, cutset: str) -> Value:
    return s.strip(cutset) if cutset else s


@register("trimprefix", Param("str", S), Param("prefix", S))
def _trimprefix(s: str, prefix: str) -> Value:
    return s[len(prefix) :] if prefix and s.startswith(prefix) else s


@register("trimsuffix", Param("str", S), Param("suffix", S))
def _trimsuffix(s: str, suffix: str) -> Value:
    return s[: len(s) - len(suffix)] if suffix and s.endswith(suffix) else s


@register("startswith", Param("str", S), Param("prefix", S))
def _startswith(s: str, prefix: str) -> Value:
    return s.startswith(prefix)


@register("endswith", Param("str", S), Param("suffix", S))
def _endswith(s: str, suffix: str) -> Value:
    return s.endswith(suffix)


@register("strcontains", Param("str", S), Param("substr", S))
def _strcontains(s: str, sub: str) -> Value:
    return sub in s


@register("strrev", Param("str", S))
def _strrev(s: str) -> Value:
    return "".join(reversed(split_graphemes(s)))


@register("indent", Param("spaces", NUMBER), Param("str", S))
def _indent(spaces: Number, s: str) -> Value:
    n = whole_int(spaces)
    if n < 0:
        raise FuncFail("panic in function implementation: strings: negative Repeat count")
    return ("\n" + " " * n).join(s.split("\n"))


@register("substr", Param("str", S), Param("offset", NUMBER), Param("length", NUMBER))
def _substr(s: str, offset: Number, length: Number) -> Value:
    off = whole_int(offset)
    ln = whole_int(length)
    clusters = split_graphemes(s)
    n = len(clusters)
    if off < 0:
        off = max(n + off, 0)
    if off >= n:
        return ""
    end = n if ln < 0 else min(off + ln, n)
    return "".join(clusters[off:end])


@register("split", Param("separator", S), Param("str", S))
def _split(sep: str, s: str) -> Value:
    if sep == "":
        return list(s)
    return s.split(sep)


@register("join", Param("separator", S), varargs=Param("lists", ListT(S)))
def _join(sep: str, *lists: Value) -> Value:
    if not lists:
        raise FuncFail("at least one list is required")
    items: list[str] = []
    for lst in lists:
        for i, x in enumerate(lst):
            if isinstance(x, Null):
                raise ArgumentError(f'Invalid value for "lists" parameter: element {i} is null; cannot concatenate null values.')
            items.append(x)
    return sep.join(items)


@register("replace", Param("str", S), Param("substr", S), Param("replace", S))
def _replace(s: str, sub: str, rep: str) -> Value:
    if len(sub) > 1 and sub.startswith("/") and sub.endswith("/"):
        try:
            rx = compile_regex(sub[1:-1])
        except RegexError as exc:
            raise FuncFail(str(exc)) from None
        out: list[str] = []
        last = 0
        for m in rx.find_all(s):
            out.append(s[last : m[0]])
            out.append(expand(rep, s, m, rx.group_names))
            last = m[1]
        out.append(s[last:])
        return "".join(out)
    return s.replace(sub, rep)


# ---------------------------------------------------------------------------
# regex
# ---------------------------------------------------------------------------


def _compile(pattern: str):  # type: ignore[no-untyped-def]
    try:
        rx = compile_regex(pattern)
    except RegexError as exc:
        raise ArgumentError(f'Invalid value for "pattern" parameter: invalid regexp pattern: {exc.code} in {exc.expr}.') from None
    names = rx.group_names[1:]
    named = [n for n in names if n]
    if named and len(named) != len(names):
        raise ArgumentError('Invalid value for "pattern" parameter: invalid regexp pattern: cannot mix both named and unnamed capture groups.')
    return rx


def _match_value(rx, text: str, m: list[int]) -> Value:  # type: ignore[no-untyped-def]
    names = rx.group_names[1:]
    if not names:
        return text[m[0] : m[1]]
    vals = []
    for i in range(1, len(names) + 1):
        a, b = m[2 * i], m[2 * i + 1]
        vals.append(text[a:b] if a >= 0 else Null(S))
    if names[0]:
        return Object({nm: v for nm, v in zip(names, vals)})
    return tuple(vals)


@register("regex", Param("pattern", S), Param("string", S))
def _regex(pattern: str, text: str) -> Value:
    rx = _compile(pattern)
    m = rx.search(text, 0)
    if m is None:
        raise FuncFail("pattern did not match any part of the given string")
    return _match_value(rx, text, m)


@register("regexall", Param("pattern", S), Param("string", S))
def _regexall(pattern: str, text: str) -> Value:
    rx = _compile(pattern)
    return [_match_value(rx, text, m) for m in rx.find_all(text)]


# ---------------------------------------------------------------------------
# format / formatlist
# ---------------------------------------------------------------------------

_KNOWN_VERBS = set("vsdxXobqtfeEgG")


def _pad(body: str, width: int | None, left: bool, zero: bool) -> str:
    if width is None or len(body) >= width:
        return body
    n = width - len(body)
    if left:
        return body + " " * n
    if zero:
        return "0" * n + body
    return " " * n + body


from .console import quote_string as _go_quote  # noqa: E402


def _fmt_int(n: int, verb: str, plus: bool, space: bool, sharp: bool, minus: bool, zero: bool, width: int | None, prec: int | None) -> str:
    neg = n < 0
    sign = "-" if neg else "+" if plus else " " if space else ""
    a = abs(n)
    base = {"d": 10, "x": 16, "X": 16, "o": 8, "b": 2}[verb]
    digits = _int_to_base(a, base)
    if verb == "X":
        digits = digits.upper()
    prefix = ""
    if sharp:
        prefix = {"b": "0b", "o": "0", "x": "0x", "X": "0X"}.get(verb, "")
    zeros = 0
    if prec is not None:
        if len(digits) < prec:
            zeros = prec - len(digits)
        elif digits == "0" and prec == 0:
            return ""
    left = right = 0
    length = len(sign) + len(prefix) + zeros + len(digits)
    if width is not None and length < width:
        d = width - length
        if minus:
            right = d
        elif zero and prec is None:
            zeros = d
        else:
            left = d
    return " " * left + sign + prefix + "0" * zeros + digits + " " * right


def _int_to_base(n: int, base: int) -> str:
    if n == 0:
        return "0"
    if base == 10:
        return str(n)
    if base == 16:
        return f"{n:x}"
    if base == 8:
        return f"{n:o}"
    return f"{n:b}"


def _fmt_float(x: Number, verb: str, plus: bool, space: bool, minus: bool, zero: bool, width: int | None, prec: int | None) -> str:
    if verb in "eEfF" and prec is None:
        prec = 6
    if verb in "gG" or verb == "v":
        pass
    text = x.format(verb, prec)
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
    elif text.startswith("+"):
        sign = " " if space else "+"
        text = text[1:]
    elif plus:
        sign = "+"
    elif space:
        sign = " "
    padding = 0
    if width is not None and width > len(sign) + len(text):
        padding = width - len(sign) - len(text)
    if zero and not x.is_inf and padding:
        return sign + "0" * padding + text
    if minus:
        return sign + text + " " * padding
    return " " * padding + sign + text


def format_string(fmt: str, args: list[Value]) -> str:
    """Terraform's ``format``: ``fmt`` with ``args`` (already-evaluated values)."""
    out: list[str] = []
    n = len(fmt)
    i = 0
    arg_num = 0
    max_used = 0
    while i < n:
        c = fmt[i]
        if c != "%":
            j = fmt.find("%", i)
            if j < 0:
                j = n
            out.append(fmt[i:j])
            i = j
            continue
        spec_start = i
        i += 1
        if i >= n:
            raise FuncFail(f"invalid format string starting at offset {i}")
        if fmt[i] == "%":
            out.append("%")
            i += 1
            continue
        plus = minus = sharp = zero = space = False
        while i < n and fmt[i] in "+-# 0":
            ch = fmt[i]
            if ch == "+":
                plus = True
            elif ch == "-":
                minus = True
            elif ch == "#":
                sharp = True
            elif ch == "0":
                zero = True
            else:
                space = True
            i += 1
        explicit: int | None = None

        def parse_index() -> None:
            nonlocal i, explicit
            if i < n and fmt[i] == "[":
                j = i + 1
                if j >= n or not ("1" <= fmt[j] <= "9"):
                    bad = fmt[j] if j < n else ""
                    raise FuncFail(f"unrecognized format character {bad!r} at offset {j}" if bad else f"invalid format string starting at offset {j}")
                k = j
                while k < n and fmt[k].isdigit():
                    k += 1
                if k >= n or fmt[k] != "]":
                    bad = fmt[k] if k < n else ""
                    raise FuncFail(f"unrecognized format character {bad!r} at offset {k}" if bad else f"invalid format string starting at offset {k}")
                explicit = int(fmt[j:k])
                i = k + 1

        parse_index()
        width: int | None = None
        j = i
        while j < n and fmt[j].isdigit() and fmt[j].isascii():
            j += 1
        if j > i:
            width = int(fmt[i:j])
            i = j
        prec: int | None = None
        if i < n and fmt[i] == ".":
            i += 1
            j = i
            while j < n and fmt[j].isdigit() and fmt[j].isascii():
                j += 1
            prec = int(fmt[i:j]) if j > i else 0
            i = j
        parse_index()
        if i >= n:
            raise FuncFail(f"invalid format string starting at offset {i}")
        verb = fmt[i]
        if not (verb.isascii() and verb.isalpha()):
            raise FuncFail(f"unrecognized format character {verb!r} at offset {i}")
        i += 1
        spec = fmt[spec_start:i]
        if verb not in _KNOWN_VERBS:
            raise FuncFail(f"unsupported format verb {verb!r} in \"{spec}\" at offset {spec_start}")
        if explicit is not None:
            arg_num = explicit - 1
        if arg_num >= len(args):
            raise FuncFail(f'not enough arguments for "{spec}" at {spec_start}: need index {arg_num + 1} but have {len(args)} total')
        arg = args[arg_num]
        arg_num += 1
        max_used = max(max_used, arg_num)
        try:
            out.append(_format_one(verb, arg, plus, space, sharp, minus, zero, width, prec))
        except _ValueFail as exc:
            raise FuncFail(f'unsupported value for "{spec}" at {spec_start}: {exc.msg}') from None
    if len(args) > max_used:
        if max_used == 0:
            raise ArgumentError('Invalid value for "args" parameter: too many arguments; no verbs in format string.')
        raise ArgumentError(f'Invalid value for "args" parameter: too many arguments; only {max_used} used by format string.')
    return "".join(out)


class _ValueFail(Exception):
    def __init__(self, msg: str) -> None:
        super().__init__(msg)
        self.msg = msg


def _conv(arg: Value, target) -> Value:  # type: ignore[no-untyped-def]
    if isinstance(arg, Null):
        raise _ValueFail("null value cannot be formatted")
    try:
        return convert(arg, target)
    except ConversionError as exc:
        raise _ValueFail(exc.message) from None


def _format_one(verb: str, arg: Value, plus: bool, space: bool, sharp: bool, minus: bool, zero: bool, width: int | None, prec: int | None) -> str:
    if verb == "v":
        if isinstance(arg, Null):
            return _pad("null", width, minus, zero)
        if isinstance(arg, str) and not sharp:
            return _pad(arg[:prec] if prec is not None else arg, width, minus, zero)
        if isinstance(arg, bool) and not sharp:
            return _pad("true" if arg else "false", width, minus, zero)
        if isinstance(arg, Number) and not sharp:
            return _fmt_float(arg, "g", plus, space, minus, zero, width, prec)
        try:
            body = json_encode(arg)
        except FuncFail as exc:
            raise _ValueFail(exc.message) from None
        return _pad(body, width, minus, zero)
    if verb == "s":
        s = _conv(arg, STRING)
        assert isinstance(s, str)
        return _pad(s[:prec] if prec is not None else s, width, minus, zero)
    if verb == "q":
        s = _conv(arg, STRING)
        assert isinstance(s, str)
        return _pad(_go_quote(s), width, minus, zero)
    if verb == "t":
        b = _conv(arg, BOOL)
        return _pad("true" if b else "false", width, minus, zero)
    num = _conv(arg, NUMBER)
    assert isinstance(num, Number)
    if verb in "dxXob":
        if not num.is_int():
            raise _ValueFail("an integer is required")
        return _fmt_int(num.to_int(), verb, plus, space, sharp, minus, zero, width, prec)
    return _fmt_float(num, verb, plus, space, minus, zero, width, prec)


@register("format", Param("format", S), varargs=Param("args", DYNAMIC, allow_null=True, allow_unknown=True))
def _format(fmt: str, *args: Value) -> Value:
    return format_string(fmt, list(args))


@register("formatlist", Param("format", S), varargs=Param("args", DYNAMIC, allow_null=True, allow_unknown=True))
def _formatlist(fmt: str, *args: Value) -> Value:
    first = -1
    length = 0
    is_list = []
    for idx, a in enumerate(args):
        il = isinstance(a, (list, tuple, TfSet))
        is_list.append(il)
        if il:
            ln = len(a)
            if first < 0:
                first, length = idx, ln
            elif ln != length:
                raise ArgumentError(
                    f'Invalid value for "args" parameter: argument {idx + 1} has length {ln}, which is inconsistent with argument {first + 1} of length {length}.'
                )
    count = length if first >= 0 else 1
    seqs = [list(a) if il else None for a, il in zip(args, is_list)]
    out: list[Value] = []
    for k in range(count):
        cur = [seqs[j][k] if seqs[j] is not None else args[j] for j in range(len(args))]  # type: ignore[index]
        try:
            out.append(format_string(fmt, cur))
        except (FuncFail, ArgumentError) as exc:
            msg = exc.message
            if msg.startswith('Invalid value for "args" parameter: '):
                msg = msg[len('Invalid value for "args" parameter: ') :].rstrip(".")
            raise FuncFail(f"error on format iteration {k}: {msg}") from None
    return out


__all__ = ["format_string", "whole_int", "grapheme_count", "Unknown", "type_of", "NULL"]

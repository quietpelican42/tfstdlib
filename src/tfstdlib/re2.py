"""A Go ``regexp`` (RE2 syntax) engine written from the public syntax reference.

Terraform's ``regex``, ``regexall`` and ``replace`` use Go's regexp package.
Python's ``re`` differs from it in syntax (``\\pL``, ``\\z``, ``(?P<n>)``,
``[[:alpha:]]``), in character-class semantics (``\\d`` is ASCII in Go), in
how empty matches and nested empty loops behave, and it can backtrack
exponentially. This module parses the RE2 dialect and runs it on a small
backtracking machine with a visited set (each state is explored at most once),
which reproduces Go's leftmost-first results and runs in O(pattern * text).

Parse errors carry Go's error code and expression text so callers can build
the same message Terraform prints.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache

MAX_RUNE = 0x10FFFF
MAX_REPEAT = 1000
MAX_PROG = 300_000


class RegexError(Exception):
    """A pattern that Go's regexp rejects."""

    def __init__(self, code: str, expr: str) -> None:
        super().__init__(f"error parsing regexp: {code}: `{expr}`")
        self.code = code
        self.expr = expr


Ranges = list[tuple[int, int]]


# ---------------------------------------------------------------------------
# character sets
# ---------------------------------------------------------------------------


def _norm(r: Ranges) -> Ranges:
    if not r:
        return []
    r = sorted(r)
    out = [r[0]]
    for lo, hi in r[1:]:
        plo, phi = out[-1]
        if lo <= phi + 1:
            if hi > phi:
                out[-1] = (plo, hi)
        else:
            out.append((lo, hi))
    return out


def _negate(r: Ranges) -> Ranges:
    r = _norm(r)
    out: Ranges = []
    nxt = 0
    for lo, hi in r:
        if lo > nxt:
            out.append((nxt, lo - 1))
        nxt = hi + 1
    if nxt <= MAX_RUNE:
        out.append((nxt, MAX_RUNE))
    return out


_PERL: dict[str, Ranges] = {
    "d": [(0x30, 0x39)],
    "s": [(0x09, 0x0A), (0x0C, 0x0D), (0x20, 0x20)],
    "w": [(0x30, 0x39), (0x41, 0x5A), (0x5F, 0x5F), (0x61, 0x7A)],
}

_POSIX: dict[str, Ranges] = {
    "alnum": [(0x30, 0x39), (0x41, 0x5A), (0x61, 0x7A)],
    "alpha": [(0x41, 0x5A), (0x61, 0x7A)],
    "ascii": [(0x00, 0x7F)],
    "blank": [(0x09, 0x09), (0x20, 0x20)],
    "cntrl": [(0x00, 0x1F), (0x7F, 0x7F)],
    "digit": [(0x30, 0x39)],
    "graph": [(0x21, 0x7E)],
    "lower": [(0x61, 0x7A)],
    "print": [(0x20, 0x7E)],
    "punct": [(0x21, 0x2F), (0x3A, 0x40), (0x5B, 0x60), (0x7B, 0x7E)],
    "space": [(0x09, 0x0D), (0x20, 0x20)],
    "upper": [(0x41, 0x5A)],
    "word": [(0x30, 0x39), (0x41, 0x5A), (0x5F, 0x5F), (0x61, 0x7A)],
    "xdigit": [(0x30, 0x39), (0x41, 0x46), (0x61, 0x66)],
}

# Script tables are block-range approximations for common scripts. Python's
# unicodedata has no Script property.
_SCRIPTS: dict[str, Ranges] = {
    "Latin": [(0x41, 0x5A), (0x61, 0x7A), (0xAA, 0xAA), (0xBA, 0xBA), (0xC0, 0xD6), (0xD8, 0xF6), (0xF8, 0x2B8), (0x2E0, 0x2E4), (0x1D00, 0x1D25), (0x1D2C, 0x1D5C), (0x1D62, 0x1D65), (0x1D6B, 0x1D77), (0x1D79, 0x1DBE), (0x1E00, 0x1EFF), (0x2071, 0x2071), (0x207F, 0x207F), (0x2090, 0x209C), (0x212A, 0x212B), (0x2132, 0x2132), (0x214E, 0x214E), (0x2160, 0x2188), (0x2C60, 0x2C7F), (0xA722, 0xA787), (0xA78B, 0xA7FF), (0xAB30, 0xAB5A), (0xAB5C, 0xAB64), (0xFB00, 0xFB06), (0xFF21, 0xFF3A), (0xFF41, 0xFF5A)],
    "Greek": [(0x370, 0x373), (0x375, 0x377), (0x37A, 0x37D), (0x37F, 0x37F), (0x384, 0x384), (0x386, 0x386), (0x388, 0x3E1), (0x3F0, 0x3FF), (0x1D26, 0x1D2A), (0x1F00, 0x1FFE), (0x2126, 0x2126)],
    "Cyrillic": [(0x400, 0x484), (0x487, 0x52F), (0x1C80, 0x1C88), (0x1D2B, 0x1D2B), (0x2DE0, 0x2DFF), (0xA640, 0xA69F)],
    "Armenian": [(0x531, 0x556), (0x559, 0x58A), (0x58D, 0x58F), (0xFB13, 0xFB17)],
    "Hebrew": [(0x591, 0x5C7), (0x5D0, 0x5EA), (0x5EF, 0x5F4), (0xFB1D, 0xFB4F)],
    "Arabic": [(0x600, 0x604), (0x606, 0x60B), (0x60D, 0x61A), (0x61C, 0x61E), (0x620, 0x63F), (0x641, 0x64A), (0x656, 0x66F), (0x671, 0x6DC), (0x6DE, 0x6FF), (0x750, 0x77F), (0x8A0, 0x8FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFC)],
    "Devanagari": [(0x900, 0x950), (0x955, 0x963), (0x966, 0x97F), (0xA8E0, 0xA8FF)],
    "Bengali": [(0x980, 0x9FE)],
    "Tamil": [(0xB82, 0xBFA)],
    "Thai": [(0xE01, 0xE3A), (0xE40, 0xE5B)],
    "Georgian": [(0x10A0, 0x10C5), (0x10C7, 0x10C7), (0x10CD, 0x10CD), (0x10D0, 0x10FA), (0x10FC, 0x10FF), (0x1C90, 0x1CBF), (0x2D00, 0x2D2D)],
    "Hangul": [(0x1100, 0x11FF), (0x302E, 0x302F), (0x3131, 0x318E), (0x3200, 0x321E), (0x3260, 0x327E), (0xA960, 0xA97C), (0xAC00, 0xD7A3), (0xD7B0, 0xD7FB), (0xFFA0, 0xFFDC)],
    "Hiragana": [(0x3041, 0x3096), (0x309D, 0x309F), (0x1B001, 0x1B11F), (0x1F200, 0x1F200)],
    "Katakana": [(0x30A1, 0x30FA), (0x30FD, 0x30FF), (0x31F0, 0x31FF), (0x32D0, 0x32FE), (0x3300, 0x3357), (0xFF66, 0xFF6F), (0xFF71, 0xFF9D)],
    "Han": [(0x2E80, 0x2E99), (0x2E9B, 0x2EF3), (0x2F00, 0x2FD5), (0x3005, 0x3005), (0x3007, 0x3007), (0x3021, 0x3029), (0x3038, 0x303B), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFA6D), (0xFA70, 0xFAD9), (0x20000, 0x2A6DF), (0x2A700, 0x2EBE0), (0x2F800, 0x2FA1D), (0x30000, 0x323AF)],
    "Common": [(0x00, 0x40), (0x5B, 0x60), (0x7B, 0xA9), (0xAB, 0xB9), (0xBB, 0xBF), (0xD7, 0xD7), (0xF7, 0xF7), (0x2000, 0x206F), (0x20A0, 0x20C0), (0x2100, 0x2125), (0x2190, 0x2BFF), (0x3000, 0x3004), (0xFF01, 0xFF20)],
}


@lru_cache(maxsize=1)
def _category_table() -> dict[str, Ranges]:
    """General-category range lists, built once by scanning every code point."""
    tbl: dict[str, Ranges] = {}
    cat = unicodedata.category
    last: str | None = None
    start = 0
    for cp in range(MAX_RUNE + 2):
        c = cat(chr(cp)) if cp <= MAX_RUNE and not (0xD800 <= cp <= 0xDFFF) else ("Cs" if cp <= MAX_RUNE else "")
        if c != last:
            if last is not None:
                tbl.setdefault(last, []).append((start, cp - 1))
            last = c
            start = cp
    out: dict[str, Ranges] = dict(tbl)
    for k in list(out):
        out.setdefault(k[0], [])
    merged: dict[str, Ranges] = {}
    for k, v in out.items():
        merged[k] = v
    for major in {k[0] for k in out if len(k) == 2}:
        merged[major] = _norm([r for k, v in out.items() if len(k) == 2 and k[0] == major for r in v])
    return merged


def unicode_class(name: str) -> Ranges | None:
    """Ranges for a ``\\p{name}`` class, or ``None`` if unknown."""
    if name == "Any":
        return [(0, MAX_RUNE)]
    tbl = _category_table()
    if name in tbl and name != "Cn":
        return list(tbl[name])
    if name in _SCRIPTS:
        return list(_SCRIPTS[name])
    return None


# --- case folding orbits -------------------------------------------------------

_SPECIAL_UP = {0x1FB3: 0x1FBC, 0x1FC3: 0x1FCC, 0x1FF3: 0x1FFC}


def _simple_upper(c: str) -> str:
    cp = ord(c)
    if 0x1F80 <= cp <= 0x1FAF and (cp & 0xF) < 8:
        return chr(cp + 8)
    if cp in _SPECIAL_UP:
        return chr(_SPECIAL_UP[cp])
    u = c.upper()
    return u if len(u) == 1 else c


def _simple_lower(c: str) -> str:
    if c == "İ":
        return "i"
    lo = c.lower()
    return lo if len(lo) == 1 else c


@lru_cache(maxsize=1)
def _fold_table() -> dict[int, tuple[int, ...]]:
    groups: dict[int, list[int]] = {}
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        ch = chr(cp)
        if ch.isascii() and not ch.isalpha():
            continue
        key = ord(_simple_lower(_simple_upper(ch)))
        if key != cp or _simple_upper(ch) != ch or _simple_lower(ch) != ch:
            groups.setdefault(key, []).append(cp)
            if key != cp:
                groups.setdefault(key, [])
                if key not in groups[key]:
                    groups[key].append(key)
    table: dict[int, tuple[int, ...]] = {}
    for members in groups.values():
        uniq = tuple(sorted(set(members)))
        if len(uniq) > 1:
            for m in uniq:
                table[m] = uniq
    return table


def fold_orbit(cp: int) -> tuple[int, ...]:
    if cp < 0x80 and not chr(cp).isalpha():
        return (cp,)
    if chr(cp).isascii():
        # ASCII letters: also the two non-ASCII members of the orbit (k, s)
        return _fold_table().get(cp, (cp,))
    return _fold_table().get(cp, (cp,))


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

FOLD, MULTI, DOTALL, UNGREEDY = 1, 2, 4, 8


@dataclass
class _Node:
    kind: str
    # lit: cp; cls: ranges/neg; empty: op; cat/alt: subs; rep: min,max,greedy; cap: index
    cp: int = 0
    ranges: Ranges | None = None
    neg: bool = False
    fold: bool = False
    op: str = ""
    subs: list["_Node"] | None = None
    lo: int = 0
    hi: int = -1
    greedy: bool = True
    index: int = 0


class _Parser:
    def __init__(self, s: str) -> None:
        self.s = s
        self.i = 0
        self.n = len(s)
        self.ncap = 0
        self.names: list[str] = [""]

    def peek(self) -> str:
        return self.s[self.i] if self.i < self.n else ""

    def parse(self) -> _Node:
        node = self.alternation(0, top=True)
        if self.i < self.n:
            raise RegexError("unexpected )", self.s)
        return node

    def alternation(self, flags: int, top: bool = False) -> _Node:
        branches = [self.concat(flags)]
        # concat may have altered flags via (?i) at this level; retrieve them
        while self.peek() == "|":
            self.i += 1
            branches.append(self.concat(self._flags))
        if len(branches) == 1:
            return branches[0]
        return _Node("alt", subs=branches)

    _flags = 0

    def concat(self, flags: int) -> _Node:
        self._flags = flags
        items: list[_Node] = []
        last_repeat = ""
        while self.i < self.n:
            c = self.s[self.i]
            if c in "|)":
                break
            flags = self._flags
            atom = self.atom(flags)
            if atom is not None and atom.kind == "cat" and atom.op == "Q":
                assert atom.subs is not None
                items.extend(atom.subs[:-1])
                atom = atom.subs[-1]
            if atom is None:
                # a flag group that changed self._flags; nothing to add
                last_repeat = ""
                continue
            # repetition operators
            while True:
                op_start = self.i
                r = self.repeat_op()
                if r is None:
                    break
                lo, hi, greedy, text = r
                if last_repeat:
                    raise RegexError("invalid nested repetition operator", last_repeat + text)
                if self._flags & UNGREEDY:
                    greedy = not greedy
                atom = _Node("rep", subs=[atom], lo=lo, hi=hi, greedy=greedy)
                last_repeat = text
                _ = op_start
            last_repeat = ""
            items.append(atom)
        if len(items) == 1:
            return items[0]
        return _Node("cat", subs=items)

    def repeat_op(self) -> tuple[int, int, bool, str] | None:
        c = self.peek()
        start = self.i
        if c in ("*", "+", "?"):
            self.i += 1
            lo, hi = {"*": (0, -1), "+": (1, -1), "?": (0, 1)}[c]
        elif c == "{":
            m = self._try_repeat_braces()
            if m is None:
                return None
            lo, hi = m
        else:
            return None
        greedy = True
        if self.peek() == "?":
            self.i += 1
            greedy = False
        return lo, hi, greedy, self.s[start : self.i]

    def _try_repeat_braces(self) -> tuple[int, int] | None:
        j = self.i + 1
        s = self.s
        k = j
        while k < self.n and s[k].isdigit() and s[k].isascii():
            k += 1
        if k == j:
            return None
        lo = int(s[j:k])
        hi = lo
        if k < self.n and s[k] == ",":
            k += 1
            j2 = k
            while k < self.n and s[k].isdigit() and s[k].isascii():
                k += 1
            hi = int(s[j2:k]) if k > j2 else -1
        if k >= self.n or s[k] != "}":
            return None
        text = s[self.i : k + 1]
        self.i = k + 1
        if lo > MAX_REPEAT or hi > MAX_REPEAT or (hi >= 0 and lo > hi):
            raise RegexError("invalid repeat count", text)
        return lo, hi

    def atom(self, flags: int) -> _Node | None:
        s = self.s
        c = s[self.i]
        if c == "(":
            return self.group(flags)
        if c == "[":
            return self.char_class(flags)
        if c == ".":
            self.i += 1
            if flags & DOTALL:
                return _Node("cls", ranges=[(0, MAX_RUNE)])
            return _Node("cls", ranges=[(0, 9), (11, MAX_RUNE)])
        if c == "^":
            self.i += 1
            return _Node("empty", op="bol" if flags & MULTI else "bot")
        if c == "$":
            self.i += 1
            return _Node("empty", op="eol" if flags & MULTI else "eot")
        if c in "*+?":
            raise RegexError("missing argument to repetition operator", c + ("?" if s.startswith("?", self.i + 1) else ""))
        if c == "{":
            save = self.i
            m = self._try_repeat_braces()
            if m is not None:
                text = s[save : self.i]
                raise RegexError("missing argument to repetition operator", text)
            self.i = save + 1
            return _Node("lit", cp=ord("{"), fold=False)
        if c == "\\":
            return self.escape_atom(flags)
        self.i += 1
        return _Node("lit", cp=ord(c), fold=bool(flags & FOLD))

    def escape_atom(self, flags: int) -> _Node | None:
        s = self.s
        if self.i + 1 >= self.n:
            raise RegexError("trailing backslash at end of expression", "")
        e = s[self.i + 1]
        if e == "A":
            self.i += 2
            return _Node("empty", op="bot")
        if e == "z":
            self.i += 2
            return _Node("empty", op="eot")
        if e == "b":
            self.i += 2
            return _Node("empty", op="wb")
        if e == "B":
            self.i += 2
            return _Node("empty", op="nwb")
        if e == "C":
            raise RegexError("invalid escape sequence", "\\C")
        if e == "Q":
            j = s.find("\\E", self.i + 2)
            lit = s[self.i + 2 :] if j < 0 else s[self.i + 2 : j]
            self.i = self.n if j < 0 else j + 2
            nodes = [_Node("lit", cp=ord(ch), fold=bool(flags & FOLD)) for ch in lit]
            if not nodes:
                return _Node("cat", subs=[])
            return _Node("cat", subs=nodes, op="Q") if len(nodes) > 1 else nodes[0]
        if e in "dDsSwW":
            self.i += 2
            r = _PERL[e.lower()]
            return _Node("cls", ranges=list(r), neg=e.isupper(), fold=False)
        if e in "pP":
            r2 = self.unicode_escape()
            assert r2 is not None
            ranges, neg = r2
            return _Node("cls", ranges=ranges, neg=neg, fold=bool(flags & FOLD))
        cp = self.parse_escape()
        return _Node("lit", cp=cp, fold=bool(flags & FOLD))

    def unicode_escape(self) -> tuple[Ranges, bool] | None:
        """Parse ``\\pX``, ``\\p{Name}``, ``\\PX``, ``\\p{^Name}`` at ``self.i``."""
        s = self.s
        start = self.i
        neg = s[self.i + 1] == "P"
        self.i += 2
        if self.i >= self.n:
            raise RegexError("invalid character class range", s[start:])
        if s[self.i] == "{":
            j = s.find("}", self.i)
            if j < 0:
                raise RegexError("invalid character class range", s[start:])
            name = s[self.i + 1 : j]
            self.i = j + 1
        else:
            name = s[self.i]
            self.i += 1
        if name.startswith("^"):
            neg = not neg
            name = name[1:]
        r = unicode_class(name)
        if r is None:
            raise RegexError("invalid character class range", s[start : self.i])
        return r, neg

    def parse_escape(self) -> int:
        """Parse a single-character escape at ``self.i`` (which points at the backslash)."""
        s = self.s
        start = self.i
        self.i += 1
        if self.i >= self.n:
            raise RegexError("trailing backslash at end of expression", "")
        c = s[self.i]
        self.i += 1
        if c in "1234567":
            if self.i >= self.n or s[self.i] not in "01234567":
                raise RegexError("invalid escape sequence", s[start : self.i])
            c = c  # falls through to octal handling
            r = ord(c) - 48
            for _ in range(2):
                if self.i < self.n and s[self.i] in "01234567":
                    r = r * 8 + ord(s[self.i]) - 48
                    self.i += 1
                else:
                    break
            return r
        if c == "0":
            r = 0
            for _ in range(2):
                if self.i < self.n and s[self.i] in "01234567":
                    r = r * 8 + ord(s[self.i]) - 48
                    self.i += 1
                else:
                    break
            return r
        if c == "x":
            if self.i >= self.n:
                raise RegexError("invalid escape sequence", s[start : self.i])
            if s[self.i] == "{":
                j = s.find("}", self.i)
                if j < 0:
                    raise RegexError("invalid escape sequence", s[start:])
                hexs = s[self.i + 1 : j]
                if not hexs or len(hexs) > 8 or not all(h in "0123456789abcdefABCDEF" for h in hexs):
                    raise RegexError("invalid escape sequence", s[start : j + 1])
                v = int(hexs, 16)
                if v > MAX_RUNE:
                    raise RegexError("invalid escape sequence", s[start : j + 1])
                self.i = j + 1
                return v
            hexs = s[self.i : self.i + 2]
            if len(hexs) != 2 or not all(h in "0123456789abcdefABCDEF" for h in hexs):
                raise RegexError("invalid escape sequence", s[start : self.i + len(hexs)])
            self.i += 2
            return int(hexs, 16)
        simple = {"a": 7, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11}
        if c in simple:
            return simple[c]
        if ord(c) < 0x80 and not c.isalnum():
            return ord(c)
        raise RegexError("invalid escape sequence", s[start : self.i])

    def group(self, flags: int) -> _Node | None:
        s = self.s
        start = self.i
        if s.startswith("(?", self.i):
            # named capture
            if s.startswith("(?P<", self.i) or s.startswith("(?<", self.i):
                begin = 4 if s.startswith("(?P<", self.i) else 3
                end = s.find(">", self.i)
                if end < 0:
                    raise RegexError("invalid named capture", s[self.i :])
                name = s[self.i + begin : end]
                if not name or not all(ch == "_" or ch.isalnum() for ch in name):
                    raise RegexError("invalid named capture", s[self.i : end + 1])
                self.i = end + 1
                return self.finish_group(flags, capture=True, name=name)
            if s.startswith("(?P", self.i):
                raise RegexError("invalid named capture", s[self.i :])
            # flags
            j = self.i + 2
            newflags = flags
            neg = False
            saw_flag = False
            while True:
                if j >= self.n:
                    raise RegexError("missing closing )", s)
                ch = s[j]
                j += 1
                if ch in "imsU":
                    saw_flag = True
                    bit = {"i": FOLD, "m": MULTI, "s": DOTALL, "U": UNGREEDY}[ch]
                    newflags = (newflags & ~bit) if neg else (newflags | bit)
                elif ch == "-":
                    if neg:
                        raise RegexError("invalid or unsupported Perl syntax", s[start:j])
                    neg = True
                    saw_flag = False
                elif ch in ":)":
                    if neg and not saw_flag:
                        raise RegexError("invalid or unsupported Perl syntax", s[start:j])
                    break
                else:
                    raise RegexError("invalid or unsupported Perl syntax", s[start:j])
            self.i = j
            if ch == ")":
                self._flags = newflags
                return None
            return self.finish_group(newflags, capture=False)
        self.i += 1
        return self.finish_group(flags, capture=True, name="")

    def finish_group(self, flags: int, capture: bool, name: str = "") -> _Node:
        idx = 0
        if capture:
            self.ncap += 1
            idx = self.ncap
            self.names.append(name)
        saved = self._flags
        inner = self.alternation(flags)
        if self.peek() != ")":
            raise RegexError("missing closing )", self.s)
        self.i += 1
        self._flags = saved
        if capture:
            return _Node("cap", subs=[inner], index=idx)
        # keep a wrapper so repetition applies to the whole group
        return _Node("cat", subs=[inner])

    def char_class(self, flags: int) -> _Node:
        s = self.s
        start = self.i
        self.i += 1
        neg = False
        if self.peek() == "^":
            neg = True
            self.i += 1
        ranges: Ranges = []
        first = True
        while True:
            if self.i >= self.n:
                raise RegexError("missing closing ]", s[start:])
            c = s[self.i]
            if c == "]" and not first:
                self.i += 1
                break
            first = False
            if c == "[" and s.startswith("[:", self.i):
                j = s.find(":]", self.i + 2)
                if j >= 0:
                    text = s[self.i : j + 2]
                    name = text[2:-2]
                    pneg = name.startswith("^")
                    if pneg:
                        name = name[1:]
                    if name not in _POSIX:
                        raise RegexError("invalid character class range", text)
                    r = _POSIX[name]
                    ranges.extend(_negate(r) if pneg else r)
                    self.i = j + 2
                    continue
            if c == "\\" and self.i + 1 < self.n:
                e = s[self.i + 1]
                if e in "dDsSwW":
                    r = _PERL[e.lower()]
                    ranges.extend(_negate(r) if e.isupper() else r)
                    self.i += 2
                    continue
                if e in "pP":
                    up = self.unicode_escape()
                    assert up is not None
                    r2, pneg2 = up
                    ranges.extend(_negate(r2) if pneg2 else r2)
                    continue
            item_start = self.i
            lo = self.class_char()
            hi = lo
            if self.i + 1 < self.n and s[self.i] == "-" and s[self.i + 1] != "]":
                self.i += 1
                hi = self.class_char()
                if hi < lo:
                    raise RegexError("invalid character class range", s[item_start : self.i])
            ranges.append((lo, hi))
        return _Node("cls", ranges=_norm(ranges), neg=neg, fold=bool(flags & FOLD))

    def class_char(self) -> int:
        s = self.s
        if self.i >= self.n:
            raise RegexError("missing closing ]", s)
        c = s[self.i]
        if c == "\\":
            return self.parse_escape()
        self.i += 1
        return ord(c)


# ---------------------------------------------------------------------------
# compiler
# ---------------------------------------------------------------------------

# opcodes
_CHAR, _SPLIT, _JMP, _SAVE, _EMPTY, _MATCH = range(6)


@dataclass
class _Inst:
    op: int
    x: int = 0
    y: int = 0
    ranges: Ranges | None = None
    neg: bool = False
    fold: bool = False
    empty: str = ""
    lit: int = -1
    starts: list[int] | None = None


class _Compiler:
    def __init__(self) -> None:
        self.prog: list[_Inst] = []

    def emit(self, inst: _Inst) -> int:
        if len(self.prog) > MAX_PROG:
            raise RegexError("expression too large", "")
        self.prog.append(inst)
        return len(self.prog) - 1

    def compile(self, node: _Node, ncap: int) -> list[_Inst]:
        self.emit(_Inst(_SAVE, x=0))
        self.node(node)
        self.emit(_Inst(_SAVE, x=1))
        self.emit(_Inst(_MATCH))
        for inst in self.prog:
            if inst.op == _CHAR and inst.ranges is not None:
                inst.starts = [lo for lo, _ in inst.ranges]
        return self.prog

    def node(self, n: _Node) -> None:
        k = n.kind
        if k == "lit":
            self.emit(_Inst(_CHAR, ranges=[(n.cp, n.cp)], fold=n.fold, lit=n.cp))
        elif k == "cls":
            assert n.ranges is not None
            self.emit(_Inst(_CHAR, ranges=_norm(n.ranges), neg=n.neg, fold=n.fold))
        elif k == "empty":
            self.emit(_Inst(_EMPTY, empty=n.op))
        elif k == "cat":
            assert n.subs is not None
            for s in n.subs:
                self.node(s)
        elif k == "alt":
            assert n.subs is not None
            self.alt(n.subs)
        elif k == "cap":
            assert n.subs is not None
            self.emit(_Inst(_SAVE, x=2 * n.index))
            self.node(n.subs[0])
            self.emit(_Inst(_SAVE, x=2 * n.index + 1))
        elif k == "rep":
            assert n.subs is not None
            self.rep(n.subs[0], n.lo, n.hi, n.greedy)
        else:
            raise AssertionError(k)

    def alt(self, subs: list[_Node]) -> None:
        jumps: list[int] = []
        for idx, s in enumerate(subs):
            if idx < len(subs) - 1:
                split = self.emit(_Inst(_SPLIT))
                self.prog[split].x = split + 1
                self.node(s)
                jumps.append(self.emit(_Inst(_JMP)))
                self.prog[split].y = len(self.prog)
            else:
                self.node(s)
        for j in jumps:
            self.prog[j].x = len(self.prog)

    def _split(self, greedy: bool, body_start: int, out_ref: list[int]) -> int:
        idx = self.emit(_Inst(_SPLIT))
        out_ref.append(idx)
        return idx

    def _set_split(self, idx: int, body: int, out: int, greedy: bool) -> None:
        if greedy:
            self.prog[idx].x, self.prog[idx].y = body, out
        else:
            self.prog[idx].x, self.prog[idx].y = out, body

    def star(self, sub: _Node, greedy: bool) -> None:
        if _nullable(sub):
            # (sub+)? keeps Go's priority order for nullable bodies
            idx = self.emit(_Inst(_SPLIT))
            body = len(self.prog)
            self.plus(sub, greedy)
            self._set_split(idx, body, len(self.prog), greedy)
            return
        idx = self.emit(_Inst(_SPLIT))
        body = len(self.prog)
        self.node(sub)
        self.emit(_Inst(_JMP, x=idx))
        self._set_split(idx, body, len(self.prog), greedy)

    def plus(self, sub: _Node, greedy: bool) -> None:
        body = len(self.prog)
        self.node(sub)
        idx = self.emit(_Inst(_SPLIT))
        self._set_split(idx, body, len(self.prog), greedy)

    def quest(self, sub: _Node, greedy: bool) -> None:
        idx = self.emit(_Inst(_SPLIT))
        body = len(self.prog)
        self.node(sub)
        self._set_split(idx, body, len(self.prog), greedy)

    def rep(self, sub: _Node, lo: int, hi: int, greedy: bool) -> None:
        if lo == 0 and hi == -1:
            self.star(sub, greedy)
        elif lo == 1 and hi == -1:
            self.plus(sub, greedy)
        elif lo == 0 and hi == 1:
            self.quest(sub, greedy)
        elif hi == -1:
            for _ in range(lo - 1):
                self.node(sub)
            self.plus(sub, greedy)
        elif lo == 0 and hi == 0:
            return
        else:
            for _ in range(lo):
                self.node(sub)
            # nested optional copies: (x(x(x)?)?)?
            splits: list[int] = []
            for _ in range(hi - lo):
                idx = self.emit(_Inst(_SPLIT))
                splits.append(idx)
                self.node(sub)
            end = len(self.prog)
            for idx in splits:
                self._set_split(idx, idx + 1, end, greedy)


def _nullable(n: _Node) -> bool:
    k = n.kind
    if k in ("lit", "cls"):
        return False
    if k == "empty":
        return True
    assert n.subs is not None or k in ()
    if k == "cat":
        return all(_nullable(s) for s in (n.subs or []))
    if k == "alt":
        return any(_nullable(s) for s in (n.subs or []))
    if k == "cap":
        return _nullable((n.subs or [])[0])
    if k == "rep":
        return n.lo == 0 or _nullable((n.subs or [])[0])
    return True


# ---------------------------------------------------------------------------
# matcher
# ---------------------------------------------------------------------------


def _is_word(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")


def _in_ranges(ranges: Ranges, starts: list[int], cp: int) -> bool:
    from bisect import bisect_right

    i = bisect_right(starts, cp) - 1
    return i >= 0 and cp <= ranges[i][1]


class Regex:
    """A compiled Go-style regular expression."""

    def __init__(self, pattern: str) -> None:
        p = _Parser(pattern)
        tree = p.parse()
        self.pattern = pattern
        self.num_groups = p.ncap
        self.group_names: list[str] = p.names
        self._prog = _Compiler().compile(tree, p.ncap)
        self._ncap = 2 * (p.ncap + 1)

    def _inst_matches(self, inst: _Inst, ch: str) -> bool:
        cp = ord(ch)
        assert inst.ranges is not None and inst.starts is not None
        hit = _in_ranges(inst.ranges, inst.starts, cp)
        if not hit and inst.fold:
            for o in fold_orbit(cp):
                if o != cp and _in_ranges(inst.ranges, inst.starts, o):
                    hit = True
                    break
        return hit != inst.neg

    def search(self, text: str, pos: int = 0) -> list[int] | None:
        """Leftmost-first match at or after ``pos``: ``[start0, end0, start1, end1, ...]``."""
        n = len(text)
        prog = self._prog
        visited: set[int] = set()
        width = n + 1
        caps = [-1] * self._ncap
        for start in range(pos, n + 1):
            stack: list[tuple[int, int, bool]] = [(0, start, False)]
            while stack:
                pc, p, restore = stack.pop()
                if restore:
                    caps[pc] = p
                    continue
                while True:
                    key = pc * width + p
                    if key in visited:
                        break
                    visited.add(key)
                    inst = prog[pc]
                    op = inst.op
                    if op == _CHAR:
                        if p < n:
                            ch = text[p]
                            if inst.lit >= 0 and not inst.fold:
                                ok = ord(ch) == inst.lit
                            else:
                                ok = self._inst_matches(inst, ch)
                            if ok:
                                p += 1
                                pc += 1
                                continue
                        break
                    if op == _SPLIT:
                        stack.append((inst.y, p, False))
                        pc = inst.x
                        continue
                    if op == _JMP:
                        pc = inst.x
                        continue
                    if op == _SAVE:
                        stack.append((inst.x, caps[inst.x], True))
                        caps[inst.x] = p
                        pc += 1
                        continue
                    if op == _EMPTY:
                        if self._empty_ok(inst.empty, text, p, n):
                            pc += 1
                            continue
                        break
                    if op == _MATCH:
                        return list(caps)
            for i in range(len(caps)):
                caps[i] = -1
        return None

    @staticmethod
    def _empty_ok(kind: str, text: str, p: int, n: int) -> bool:
        if kind == "bot":
            return p == 0
        if kind == "eot":
            return p == n
        if kind == "bol":
            return p == 0 or text[p - 1] == "\n"
        if kind == "eol":
            return p == n or text[p] == "\n"
        before = p > 0 and _is_word(text[p - 1])
        after = p < n and _is_word(text[p])
        if kind == "wb":
            return before != after
        if kind == "nwb":
            return before == after
        raise AssertionError(kind)

    def find_all(self, text: str) -> list[list[int]]:
        """All non-overlapping matches, with Go's rules for empty matches."""
        out: list[list[int]] = []
        pos = 0
        prev_end = -1
        n = len(text)
        while pos <= n:
            m = self.search(text, pos)
            if m is None:
                break
            accept = True
            if m[1] == pos:
                if m[0] == prev_end:
                    accept = False
                pos += 1
            else:
                pos = m[1]
            prev_end = m[1]
            if accept:
                out.append(m)
        return out


@lru_cache(maxsize=256)
def compile_regex(pattern: str) -> Regex:
    return Regex(pattern)


def expand(template: str, text: str, m: list[int], names: list[str]) -> str:
    """Go's ``Regexp.Expand`` for a ``$name`` / ``${name}`` / ``$1`` template."""
    out: list[str] = []
    t = template
    while t:
        j = t.find("$")
        if j < 0:
            break
        out.append(t[:j])
        t = t[j + 1 :]
        if t.startswith("$"):
            out.append("$")
            t = t[1:]
            continue
        name, num, rest, ok = _extract(t)
        if not ok:
            out.append("$")
            continue
        t = rest
        if num >= 0:
            if 2 * num + 1 < len(m) and m[2 * num] >= 0:
                out.append(text[m[2 * num] : m[2 * num + 1]])
        else:
            for i, nm in enumerate(names):
                if nm == name and 2 * i + 1 < len(m) and m[2 * i] >= 0:
                    out.append(text[m[2 * i] : m[2 * i + 1]])
                    break
    out.append(t)
    return "".join(out)


def _extract(s: str) -> tuple[str, int, str, bool]:
    if not s:
        return "", 0, "", False
    brace = False
    if s[0] == "{":
        brace = True
        s = s[1:]
    i = 0
    while i < len(s) and (s[i].isalpha() or s[i].isdigit() or s[i] == "_"):
        i += 1
    if i == 0:
        return "", 0, "", False
    name = s[:i]
    if brace:
        if i >= len(s) or s[i] != "}":
            return "", 0, "", False
        i += 1
    num = 0
    for ch in name:
        if ch < "0" or ch > "9" or num >= 100_000_000:
            num = -1
            break
        num = num * 10 + ord(ch) - 48
    if name[0] == "0" and len(name) > 1:
        num = -1
    return name, num, s[i:], True

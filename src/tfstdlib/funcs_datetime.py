"""Date and time functions: formatdate, timeadd, timecmp."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ArgumentError, FuncFail
from .numbers import Number
from .registry import Param, register
from .values import STRING, Value

S = STRING

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


# ---------------------------------------------------------------------------
# proleptic Gregorian calendar on plain integers (years outside datetime's range work)
# ---------------------------------------------------------------------------


def days_from_civil(y: int, m: int, d: int) -> int:
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z: int) -> tuple[int, int, int]:
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return y + (m <= 2), m, d


def _is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _days_in_month(y: int, m: int) -> int:
    return 29 if m == 2 and _is_leap(y) else [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


@dataclass
class Timestamp:
    """An instant plus the UTC offset it was written with."""

    seconds: int  # seconds since the Unix epoch (UTC)
    nanos: int  # 0 <= nanos < 1e9
    offset: int  # seconds east of UTC

    def local_fields(self) -> tuple[int, int, int, int, int, int, int]:
        local = self.seconds + self.offset
        days, rem = divmod(local, 86400)
        y, m, d = civil_from_days(days)
        return y, m, d, rem // 3600, (rem % 3600) // 60, rem % 60, (days + 4) % 7

    def rfc3339(self) -> str:
        y, mo, d, h, mi, s, _ = self.local_fields()
        if self.offset == 0:
            off = "Z"
        else:
            sign = "+" if self.offset > 0 else "-"
            a = abs(self.offset)
            off = f"{sign}{a // 3600:02d}:{(a % 3600) // 60:02d}"
        ys = f"{y:04d}" if y >= 0 else f"-{-y:04d}"
        return f"{ys}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}{off}"

    def key(self) -> tuple[int, int]:
        return (self.seconds, self.nanos)


_TS = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})")


def parse_rfc3339(s: str) -> Timestamp:
    m = _TS.fullmatch(s)
    if not m:
        raise ValueError("not a valid RFC3339 timestamp")
    y, mo, d, h, mi, sec = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or ""
    if not 1 <= mo <= 12:
        raise ValueError("month out of range")
    if not 1 <= d <= _days_in_month(y, mo):
        raise ValueError("day out of range")
    if h > 23:
        raise ValueError("hour must be between 0 and 23 inclusive")
    if mi > 59:
        raise ValueError("minute must have exactly two digits")
    if sec > 59:
        raise ValueError("second out of range")
    zone = m.group(8)
    if zone == "Z":
        off = 0
    else:
        oh, om = int(zone[1:3]), int(zone[4:6])
        if oh > 23 or om > 59:
            raise ValueError(f'cannot use "{zone}" as UTC offset')
        off = (oh * 3600 + om * 60) * (1 if zone[0] == "+" else -1)
    nanos = int((frac + "000000000")[:9]) if frac else 0
    secs = days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + sec - off
    return Timestamp(secs, nanos, off)


def _ts_err(param: str, exc: ValueError) -> ArgumentError:
    return ArgumentError(f'Invalid value for "{param}" parameter: not a valid RFC3339 timestamp: {exc}.')


# ---------------------------------------------------------------------------
# formatdate
# ---------------------------------------------------------------------------

_RUN_RULES: dict[str, tuple[set[int], str]] = {
    "Y": ({2, 4}, 'year must either be "YY" or "YYYY"'),
    "M": ({1, 2, 3, 4}, 'month must be "M", "MM", "MMM", or "MMMM"'),
    "D": ({1, 2}, 'day of month must either be "D" or "DD"'),
    "E": ({3, 4}, 'day of week must either be "EEE" or "EEEE"'),
    "h": ({1, 2}, 'hour must either be "h" or "hh"'),
    "H": ({1, 2}, 'hour must either be "H" or "HH"'),
    "m": ({1, 2}, 'minute must either be "m" or "mm"'),
    "s": ({1, 2}, 'second must either be "s" or "ss"'),
    "Z": ({1, 3, 4, 5}, "timezone must be Z, ZZZZ, or ZZZZZ"),
    "a": ({2}, 'must be "aa"'),
    "A": ({2}, 'must be "AA"'),
}


def _format_run(ch: str, n: int, ts: Timestamp) -> str:
    y, mo, d, h, mi, s, wd = ts.local_fields()
    if ch == "Y":
        return f"{y % 100:02d}" if n == 2 else (f"{y:04d}" if y >= 0 else f"-{-y:04d}")
    if ch == "M":
        return [str(mo), f"{mo:02d}", _MONTHS[mo - 1][:3], _MONTHS[mo - 1]][n - 1]
    if ch == "D":
        return str(d) if n == 1 else f"{d:02d}"
    if ch == "E":
        return _DAYS[wd][:3] if n == 3 else _DAYS[wd]
    if ch == "h":
        return str(h) if n == 1 else f"{h:02d}"
    if ch == "H":
        h12 = h % 12 or 12
        return str(h12) if n == 1 else f"{h12:02d}"
    if ch == "m":
        return str(mi) if n == 1 else f"{mi:02d}"
    if ch == "s":
        return str(s) if n == 1 else f"{s:02d}"
    if ch == "a":
        return "am" if h < 12 else "pm"
    if ch == "A":
        return "AM" if h < 12 else "PM"
    # Z
    off = ts.offset
    sign = "+" if off >= 0 else "-"
    a = abs(off)
    hh, mm = a // 3600, (a % 3600) // 60
    if n == 1:
        return "Z" if off == 0 else f"{sign}{hh:02d}:{mm:02d}"
    if n == 3:
        return "UTC" if off == 0 else f"{sign}{hh:02d}{mm:02d}"
    if n == 4:
        return f"{sign}{hh:02d}{mm:02d}"
    return f"{sign}{hh:02d}:{mm:02d}"


@register("formatdate", Param("format", S), Param("time", S))
def _formatdate(fmt: str, time: str) -> Value:
    try:
        ts = parse_rfc3339(time)
    except ValueError as exc:
        raise _ts_err("time", exc) from None
    out: list[str] = []
    i = 0
    n = len(fmt)
    while i < n:
        c = fmt[i]
        if c == "'":
            if i + 1 < n and fmt[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            i += 1
            lit: list[str] = []
            while True:
                if i >= n:
                    raise ArgumentError('Invalid value for "format" parameter: unterminated literal \'.')
                if fmt[i] == "'":
                    if i + 1 < n and fmt[i + 1] == "'":
                        lit.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                lit.append(fmt[i])
                i += 1
            out.append("".join(lit))
            continue
        if c.isascii() and c.isalpha():
            j = i
            while j < n and fmt[j] == c:
                j += 1
            run = j - i
            rule = _RUN_RULES.get(c)
            if rule is None:
                raise ArgumentError(f'Invalid value for "format" parameter: invalid date format verb "{fmt[i:j]}".')
            if run not in rule[0]:
                raise ArgumentError(f'Invalid value for "format" parameter: invalid date format verb "{fmt[i:j]}": {rule[1]}.')
            out.append(_format_run(c, run, ts))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# durations (Go's time.ParseDuration)
# ---------------------------------------------------------------------------

_UNITS = {"ns": 1, "us": 1000, "µs": 1000, "μs": 1000, "ms": 1_000_000, "s": 1_000_000_000, "m": 60_000_000_000, "h": 3_600_000_000_000}


def parse_duration(orig: str) -> int:
    """Return nanoseconds, raising ``ValueError`` with Go's message."""

    def q(x: str) -> str:
        return '"' + x + '"'

    def invalid() -> ValueError:
        return ValueError("time: invalid duration " + q(orig))

    s = orig
    neg = False
    if s and s[0] in "+-":
        neg = s[0] == "-"
        s = s[1:]
    if s == "0":
        return 0
    if s == "":
        raise invalid()
    d = 0
    lim = 1 << 63
    while s:
        if not (s[0] == "." or "0" <= s[0] <= "9"):
            raise invalid()
        # integer part
        i = 0
        v = 0
        while i < len(s) and "0" <= s[i] <= "9":
            v = v * 10 + ord(s[i]) - 48
            if v > lim:
                raise invalid()
            i += 1
        pre = i > 0
        s = s[i:]
        f = 0
        scale = 1.0
        post = False
        if s and s[0] == ".":
            s = s[1:]
            i = 0
            overflow = False
            while i < len(s) and "0" <= s[i] <= "9":
                if not overflow:
                    y = f * 10 + ord(s[i]) - 48
                    if y > lim:
                        overflow = True
                    else:
                        f = y
                        scale *= 10
                i += 1
            post = i > 0
            s = s[i:]
        if not pre and not post:
            raise invalid()
        i = 0
        while i < len(s) and not (s[i] == "." or "0" <= s[i] <= "9"):
            i += 1
        if i == 0:
            raise ValueError("time: missing unit in duration " + q(orig))
        u = s[:i]
        s = s[i:]
        unit = _UNITS.get(u)
        if unit is None:
            raise ValueError("time: unknown unit " + q(u) + " in duration " + q(orig))
        if v > lim // unit:
            raise invalid()
        v *= unit
        if f > 0:
            v += int(float(f) * (float(unit) / scale))
            if v > lim:
                raise invalid()
        d += v
        if d > lim:
            raise invalid()
    if neg:
        return -d
    if d > lim - 1:
        raise invalid()
    return d


@register("timeadd", Param("timestamp", S), Param("duration", S))
def _timeadd(timestamp: str, duration: str) -> Value:
    try:
        ts = parse_rfc3339(timestamp)
    except ValueError as exc:
        raise FuncFail(f"not a valid RFC3339 timestamp: {exc}") from None
    try:
        dur = parse_duration(duration)
    except ValueError as exc:
        raise FuncFail(str(exc)) from None
    total = ts.seconds * 1_000_000_000 + ts.nanos + dur
    secs, nanos = divmod(total, 1_000_000_000)
    return Timestamp(secs, nanos, ts.offset).rfc3339()


@register("timecmp", Param("timestamp_a", S), Param("timestamp_b", S))
def _timecmp(a: str, b: str) -> Value:
    try:
        ta = parse_rfc3339(a)
    except ValueError as exc:
        raise _ts_err("timestamp_a", exc) from None
    try:
        tb = parse_rfc3339(b)
    except ValueError as exc:
        raise _ts_err("timestamp_b", exc) from None
    ka, kb = ta.key(), tb.key()
    return Number.from_int((ka > kb) - (ka < kb))

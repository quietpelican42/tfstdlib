"""Arbitrary-precision binary floats that behave like the numbers in Terraform.

Terraform (through cty) stores every number as a Go ``big.Float``. Literals and
parsed strings carry 512 bits of mantissa, integers produced by functions such
as ``length`` carry 64 bits, and values that went through a float64 function
(``pow``, ``log``) carry 53 bits. Arithmetic rounds to nearest-even at the
larger of the operand precisions, and a number prints as the shortest decimal
string that reads back as the same value at its own precision.

This module reproduces those rules so that ``0.1 + 0.2`` is ``0.3``,
``1 / 3`` prints 155 digits, and ``pow(2, 1000)`` prints 17 digits followed by
zeros, exactly as ``terraform console`` does.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction

PREC_PARSE = 512
PREC_INT = 64
PREC_FLOAT = 53


class NumberError(ArithmeticError):
    """Raised for NaN-producing operations (0/0, inf-inf, 0*inf)."""


_DEC_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class Number:
    """An immutable big.Float-alike. Value is ``(-1)**neg * m * 2**e``."""

    __slots__ = ("_m", "_e", "_neg", "_prec", "_inf")

    def __init__(self, m: int, e: int, neg: bool, prec: int, inf: bool = False) -> None:
        self._m = m
        self._e = e
        self._neg = neg
        self._prec = prec
        self._inf = inf

    # ---- construction -------------------------------------------------

    @staticmethod
    def _round(fr: Fraction, neg: bool, prec: int) -> "Number":
        """Round a non-negative exact rational to ``prec`` bits, half to even."""
        if fr == 0:
            return Number(0, 0, neg, prec)
        n, d = fr.numerator, fr.denominator
        e = n.bit_length() - d.bit_length() - prec
        while True:
            if e >= 0:
                q, r = divmod(n, d << e)
                den = d << e
            else:
                q, r = divmod(n << -e, d)
                den = d
            if q.bit_length() > prec:
                e += 1
                continue
            if q.bit_length() < prec:
                e -= 1
                continue
            break
        twice = 2 * r
        if twice > den or (twice == den and (q & 1)):
            q += 1
            if q.bit_length() > prec:
                q >>= 1
                e += 1
        while q and not (q & 1):
            q >>= 1
            e += 1
        return Number(q, e, neg, prec)

    @classmethod
    def from_fraction(cls, fr: Fraction, prec: int = PREC_PARSE) -> "Number":
        neg = fr < 0
        return cls._round(abs(fr), neg, prec)

    @classmethod
    def from_int(cls, n: int, prec: int = PREC_INT) -> "Number":
        prec = max(prec, abs(n).bit_length())
        return cls._round(Fraction(abs(n)), n < 0, prec)

    @classmethod
    def from_float(cls, f: float) -> "Number":
        if math.isnan(f):
            raise NumberError("NaN")
        if math.isinf(f):
            return cls(0, 0, f < 0, PREC_FLOAT, True)
        neg = math.copysign(1.0, f) < 0
        return cls._round(Fraction(abs(f)), neg, PREC_FLOAT)

    @classmethod
    def infinity(cls, neg: bool = False) -> "Number":
        return cls(0, 0, neg, PREC_PARSE, True)

    @classmethod
    def parse(cls, s: str, prec: int = PREC_PARSE) -> "Number | None":
        """Parse a decimal string as ``big.ParseFloat(s, 10, 512, ToNearestEven)``."""
        t = s
        low = t.lower()
        if not _DEC_RE.fullmatch(t):
            return None
        mant, _, exp = low.lstrip("+-").partition("e")
        intp, _, frac = mant.partition(".")
        digits = (intp + frac) or "0"
        scale = -len(frac) + (int(exp) if exp else 0)
        n = int(digits)
        if abs(scale) > 10_000_000:
            return None
        fr = Fraction(n) * (Fraction(10) ** scale if scale >= 0 else Fraction(1, 10 ** -scale))
        return cls._round(fr, t.startswith("-"), prec)

    # ---- inspection ---------------------------------------------------

    @property
    def prec(self) -> int:
        return self._prec

    @property
    def is_inf(self) -> bool:
        return self._inf

    @property
    def is_zero(self) -> bool:
        return not self._inf and self._m == 0

    @property
    def negative(self) -> bool:
        return self._neg

    def to_fraction(self) -> Fraction:
        if self._inf:
            raise NumberError("infinity")
        v = Fraction(self._m << self._e) if self._e >= 0 else Fraction(self._m, 1 << -self._e)
        return -v if self._neg else v

    def is_int(self) -> bool:
        if self._inf:
            return False
        return self._m == 0 or self._e >= 0

    def to_int(self) -> int:
        """Truncate toward zero (only meaningful for finite numbers)."""
        v = self.to_fraction()
        return int(v)

    def to_float(self) -> float:
        if self._inf:
            return -math.inf if self._neg else math.inf
        try:
            return float(self.to_fraction())
        except OverflowError:
            return -math.inf if self._neg else math.inf

    # ---- comparison ---------------------------------------------------

    def cmp(self, other: "Number") -> int:
        if self._inf or other._inf:
            a = (-1 if self._neg else 1) if self._inf else 0
            b = (-1 if other._neg else 1) if other._inf else 0
            return (a > b) - (a < b)
        a_f, b_f = self.to_fraction(), other.to_fraction()
        return (a_f > b_f) - (a_f < b_f)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Number) and self.cmp(other) == 0

    def __lt__(self, other: "Number") -> bool:
        return self.cmp(other) < 0

    def __le__(self, other: "Number") -> bool:
        return self.cmp(other) <= 0

    def __gt__(self, other: "Number") -> bool:
        return self.cmp(other) > 0

    def __ge__(self, other: "Number") -> bool:
        return self.cmp(other) >= 0

    def __hash__(self) -> int:
        if self._inf:
            return hash(("inf", self._neg))
        return hash(self.to_fraction())

    # ---- arithmetic ---------------------------------------------------

    def _prec_with(self, other: "Number") -> int:
        return max(self._prec, other._prec)

    def neg(self) -> "Number":
        return Number(self._m, self._e, not self._neg, self._prec, self._inf)

    def abs(self) -> "Number":
        return Number(self._m, self._e, False, self._prec, self._inf)

    def add(self, other: "Number") -> "Number":
        p = self._prec_with(other)
        if self._inf or other._inf:
            if self._inf and other._inf:
                if self._neg != other._neg:
                    raise NumberError("can't add infinities with opposite signs")
                return Number(0, 0, self._neg, p, True)
            src = self if self._inf else other
            return Number(0, 0, src._neg, p, True)
        if self._m == 0 and other._m == 0:
            return Number(0, 0, self._neg and other._neg, p)
        total = self.to_fraction() + other.to_fraction()
        if total == 0:
            return Number(0, 0, False, p)
        return Number.from_fraction(total, p)

    def sub(self, other: "Number") -> "Number":
        return self.add(other.neg())

    def mul(self, other: "Number") -> "Number":
        p = self._prec_with(other)
        neg = self._neg != other._neg
        if self._inf or other._inf:
            if self.is_zero or other.is_zero:
                raise NumberError("can't multiply zero by infinity")
            return Number(0, 0, neg, p, True)
        if self._m == 0 or other._m == 0:
            return Number(0, 0, neg, p)
        return Number._round(abs(self.to_fraction() * other.to_fraction()), neg, p)

    def div(self, other: "Number") -> "Number":
        p = self._prec_with(other)
        neg = self._neg != other._neg
        if self._inf and other._inf:
            raise NumberError("can't divide zero by zero or infinity by infinity")
        if self._inf:
            return Number(0, 0, neg, p, True)
        if other._inf:
            return Number(0, 0, neg, p)
        if other._m == 0:
            if self._m == 0:
                raise NumberError("can't divide zero by zero or infinity by infinity")
            return Number(0, 0, neg, p, True)
        if self._m == 0:
            return Number(0, 0, neg, p)
        return Number._round(abs(self.to_fraction() / other.to_fraction()), neg, p)

    def mod(self, other: "Number") -> "Number":
        """``a - b * trunc(a / b)`` with each step rounded like cty."""
        if self._inf:
            raise NumberError("can't take the modulo of infinity")
        if other._inf:
            return self
        if other._m == 0:
            return self
        q = self.div(other)
        qi = Number.from_fraction(Fraction(int(q.to_fraction())), max(q._prec, 1)) if not q._inf else q
        return self.sub(qi.mul(other))

    # ---- text ---------------------------------------------------------

    def _digits_shortest(self) -> tuple[str, int]:
        """Shortest round-tripping digits ``d`` and decimal point ``dp`` (0.d * 10**dp)."""
        m, e, prec = self._m, self._e, self._prec
        length = m.bit_length()
        # fast path: exact integers below 2**(prec-1)
        if e >= 0 and length + e < prec - 1:
            s = str(m << e)
            stripped = s.rstrip("0")
            return stripped, len(s)
        shift = prec + 1 - length
        if shift >= 0:
            mant2 = m << shift
            exp2 = e - shift
        else:
            mant2 = m >> -shift
            exp2 = e - shift
        inclusive = length < prec or (m & 1) == 0
        x = Fraction(mant2) * (Fraction(2) ** exp2)
        lower = Fraction(mant2 - 1) * (Fraction(2) ** exp2)
        upper = Fraction(mant2 + 1) * (Fraction(2) ** exp2)
        # decimal exponent of x
        dp = _decimal_point(x)
        n = 1
        while True:
            scale = Fraction(10) ** (dp - n)
            q = x / scale
            down = q.numerator // q.denominator
            up = down + 1
            vd = down * scale
            vu = up * scale
            okdown = (vd >= lower) if inclusive else (vd > lower)
            okup = (vu <= upper) if inclusive else (vu < upper)
            if okdown and okup:
                dist_d, dist_u = x - vd, vu - x
                if dist_d < dist_u:
                    pick = down
                elif dist_d > dist_u:
                    pick = up
                else:
                    pick = up if down & 1 else down
            elif okdown:
                pick = down
            elif okup:
                pick = up
            else:
                n += 1
                continue
            s = str(pick)
            if len(s) > n:  # rounded up to a power of ten
                dp += 1
            s = s.rstrip("0") or "0"
            return s, dp

    def text(self) -> str:
        """``big.Float.Text('f', -1)``: shortest digits, no exponent."""
        if self._inf:
            return "-Inf" if self._neg else "+Inf"
        if self._m == 0:
            return "-0" if self._neg else "0"
        digits, dp = self._digits_shortest()
        return ("-" if self._neg else "") + _fmt_f(digits, dp, max(len(digits) - dp, 0))

    def format(self, verb: str, prec: int | None) -> str:
        """``big.Float.Text``-style rendering for verbs e E f g G (no width/flags)."""
        if self._inf:
            return "-Inf" if self._neg else "+Inf"
        sign = "-" if self._neg else ""
        shortest = prec is None
        if self._m == 0:
            digits, dp = "", 0
        elif shortest:
            digits, dp = self._digits_shortest()
        else:
            digits, dp = "", 0
        lv = verb.lower()
        if not shortest and self._m != 0:
            frac = abs(self.to_fraction())
            base_dp = _decimal_point(frac)
            assert prec is not None
            if lv == "e":
                digits, dp = _round_sig(frac, base_dp, prec + 1)
            elif lv == "f":
                digits, dp = _round_fixed(frac, prec)
            else:  # g with precision
                p = prec if prec > 0 else 1
                digits, dp = _round_sig(frac, base_dp, p)
        digits = digits.rstrip("0")
        if self._m == 0:
            digits, dp = "", 0
        nd = len(digits)
        if shortest:
            if lv == "e":
                prec = max(nd - 1, 0)
            elif lv == "f":
                prec = max(nd - dp, 0)
            else:
                prec = nd
        assert prec is not None
        if lv == "e":
            body = _fmt_e(digits, dp, prec, "e")
        elif lv == "f":
            body = _fmt_f(digits, dp, prec)
        else:
            eprec = prec
            if eprec > nd and nd >= dp:
                eprec = nd
            if shortest:
                eprec = 6
            exp = dp - 1
            if exp < -4 or exp >= eprec:
                p2 = prec
                if p2 > nd:
                    p2 = nd
                body = _fmt_e(digits, dp, max(p2 - 1, 0), "e")
            else:
                p2 = prec
                if p2 > dp:
                    p2 = nd
                body = _fmt_f(digits, dp, max(p2 - dp, 0))
        if verb.isupper():
            body = body.upper()
        return sign + body

    def __repr__(self) -> str:
        return f"Number({self.text()})"

    def __str__(self) -> str:
        return self.text()


def _decimal_point(x: Fraction) -> int:
    """dp such that 10**(dp-1) <= x < 10**dp."""
    if x == 0:
        return 0
    est = int(math.floor(math.log10(x.numerator) - math.log10(x.denominator))) + 1 if x.numerator < 1 << 1000 and x.denominator < 1 << 1000 else (len(str(x.numerator)) - len(str(x.denominator)) + 1)
    dp = est
    while x >= Fraction(10) ** dp:
        dp += 1
    while x < Fraction(10) ** (dp - 1):
        dp -= 1
    return dp


def _round_sig(x: Fraction, dp: int, n: int) -> tuple[str, int]:
    scale = Fraction(10) ** (dp - n)
    q = round(x / scale)  # banker's rounding on an exact rational
    s = str(q)
    if len(s) > n:
        dp += 1
    return s, dp


def _round_fixed(x: Fraction, prec: int) -> tuple[str, int]:
    q = round(x * (Fraction(10) ** prec))
    if q == 0:
        return "", 0
    s = str(q)
    return s, len(s) - prec


def _fmt_f(digits: str, dp: int, prec: int) -> str:
    out = []
    if dp > 0:
        m = min(len(digits), dp)
        out.append(digits[:m])
        out.append("0" * (dp - m))
    else:
        out.append("0")
    if prec > 0:
        out.append(".")
        for i in range(prec):
            j = dp + i
            out.append(digits[j] if 0 <= j < len(digits) else "0")
    return "".join(out)


def _fmt_e(digits: str, dp: int, prec: int, ch: str) -> str:
    first = digits[0] if digits else "0"
    out = [first]
    if prec > 0:
        out.append(".")
        i = 1
        m = min(len(digits), prec + 1)
        if i < m:
            out.append(digits[i:m])
            i = m
        out.append("0" * (prec + 1 - i))
    exp = 0
    if digits:
        exp = dp - 1
    out.append(ch)
    out.append("-" if exp < 0 else "+")
    exp = abs(exp)
    out.append(f"{exp:02d}")
    return "".join(out)

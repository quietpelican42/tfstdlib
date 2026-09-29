"""Numeric functions."""

from __future__ import annotations

import math
from fractions import Fraction

from .errors import ArgumentError, FuncFail
from .funcs_string import INT64_MAX, INT64_MIN
from .numbers import Number, NumberError
from .registry import Param, register
from .values import DYNAMIC, NUMBER, STRING, Value

N = NUMBER


def _from_float(f: float) -> Number:
    try:
        return Number.from_float(f)
    except NumberError:
        raise FuncFail("panic in function implementation: Float.SetFloat64(NaN)") from None


@register("abs", Param("num", N))
def _abs(x: Number) -> Value:
    return x.abs()


@register("ceil", Param("num", N))
def _ceil(x: Number) -> Value:
    if x.is_inf:
        return x
    return Number.from_int(math.ceil(x.to_fraction()))


@register("floor", Param("num", N))
def _floor(x: Number) -> Value:
    if x.is_inf:
        return x
    return Number.from_int(math.floor(x.to_fraction()))


@register("signum", Param("num", N))
def _signum(x: Number) -> Value:
    if x.is_inf or not x.is_int():
        raise FuncFail("value must be a whole number, between -9223372036854775808 and 9223372036854775807.")
    v = x.to_int()
    if v < INT64_MIN or v > INT64_MAX:
        raise FuncFail("value must be a whole number, between -9223372036854775808 and 9223372036854775807.")
    return Number.from_int((v > 0) - (v < 0))


_L = (6.666666666666735130e-01, 3.999999999940941908e-01, 2.857142874366239149e-01, 2.222219843214978396e-01, 1.818357216161805012e-01, 1.531383769920937332e-01, 1.479819860511658591e-01)
_LN2_HI = 6.93147180369123816490e-01
_LN2_LO = 1.90821492927058770002e-10


def _flog(x: float) -> float:
    """Natural log with the FreeBSD/fdlibm algorithm that Go's math.Log uses.

    The algorithm and constants are the public fdlibm ones (Sun Microsystems,
    "permission to use, copy, modify, and distribute this software is freely
    granted"); Python's C library log can differ from Go's in the last digit.
    """
    if x != x or x == math.inf:
        return x
    if x < 0:
        return math.nan
    if x == 0.0:
        return -math.inf
    f1, ki = math.frexp(x)
    if f1 < math.sqrt(2) / 2:
        f1 *= 2
        ki -= 1
    f = f1 - 1
    k = float(ki)
    s = f / (2 + f)
    s2 = s * s
    s4 = s2 * s2
    l1, l2, l3, l4, l5, l6, l7 = _L
    a = l1 + s4 * (l3 + s4 * (l5 + s4 * l7))
    b = l2 + s4 * (l4 + s4 * l6)
    r = s2 * a + s4 * b
    hfsq = 0.5 * f * f
    return k * _LN2_HI - ((hfsq - (s * (hfsq + r) + k * _LN2_LO)) - f)


def _fdiv(a: float, b: float) -> float:
    if b == 0.0:
        if a == 0.0 or a != a:
            return math.nan
        neg = (math.copysign(1.0, a) < 0) != (math.copysign(1.0, b) < 0)
        return -math.inf if neg else math.inf
    return a / b


@register("log", Param("num", N), Param("base", N))
def _log(num: Number, base: Number) -> Value:
    return _from_float(_fdiv(_flog(num.to_float()), _flog(base.to_float())))


def go_pow(x: float, y: float) -> float:
    """Go's ``math.Pow`` special cases and integer-power loop."""
    inf = math.inf
    if y == 0 or x == 1:
        return 1.0
    if y == 1:
        return x
    if x != x or y != y:
        return math.nan
    if x == 0:
        if y < 0:
            if math.copysign(1.0, x) < 0 and _is_odd_int(y):
                return -inf
            return inf
        if y > 0:
            if math.copysign(1.0, x) < 0 and _is_odd_int(y):
                return x
            return 0.0
    if math.isinf(y):
        if x == -1:
            return 1.0
        if (abs(x) < 1) == (y > 0):
            return 0.0
        return inf
    if math.isinf(x):
        if x < 0:
            return go_pow(1 / x, -y)
        return 0.0 if y < 0 else inf
    if y == 0.5:
        return math.sqrt(x) if x >= 0 else math.nan
    if y == -0.5:
        return 1 / math.sqrt(x) if x > 0 else math.nan
    yf, yi = math.modf(abs(y))
    if yf != 0 and x < 0:
        return math.nan
    if yi >= 2.0**63:
        if x == -1:
            return 1.0
        if (abs(x) < 1) == (y > 0):
            return 0.0
        return inf
    a1 = 1.0
    ae = 0
    if yf != 0:
        if yf > 0.5:
            yf -= 1
            yi += 1
        a1 = math.exp(yf * _flog(x))
    x1, xe = math.frexp(x)
    i = int(yi)
    while i != 0:
        if xe < -(1 << 12) or (1 << 12) < xe:
            ae += xe
            break
        if i & 1 == 1:
            a1 *= x1
            ae += xe
        x1 *= x1
        xe <<= 1
        if x1 < 0.5:
            x1 += x1
            xe -= 1
        i >>= 1
    if y < 0:
        a1 = 1 / a1
        ae = -ae
    try:
        return math.ldexp(a1, ae)
    except OverflowError:
        return inf if a1 > 0 else -inf


def _is_odd_int(y: float) -> bool:
    if math.isinf(y) or y != math.floor(y):
        return False
    return abs(y) < 2.0**53 and int(y) % 2 == 1


@register("pow", Param("num", N), Param("power", N))
def _pow(num: Number, power: Number) -> Value:
    return _from_float(go_pow(num.to_float(), power.to_float()))


@register("max", varargs=Param("numbers", N))
def _max(*nums: Number) -> Value:
    if not nums:
        raise FuncFail("must pass at least one number")
    best = nums[0]
    for n in nums[1:]:
        if n.cmp(best) > 0:
            best = n
    return best


@register("min", varargs=Param("numbers", N))
def _min(*nums: Number) -> Value:
    if not nums:
        raise FuncFail("must pass at least one number")
    best = nums[0]
    for n in nums[1:]:
        if n.cmp(best) < 0:
            best = n
    return best


_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@register("parseint", Param("number", DYNAMIC), Param("base", N))
def _parseint(value: Value, base: Number) -> Value:
    if not isinstance(value, str):
        kind = "number" if isinstance(value, Number) else "bool" if isinstance(value, bool) else "value"
        raise ArgumentError(f'Invalid value for "number" parameter: first argument must be a string, not {kind}.')
    if base.is_inf or not base.is_int():
        raise ArgumentError('Invalid value for "base" parameter: value must be a whole number, between -9223372036854775808 and 9223372036854775807.')
    b = base.to_int()
    if b < 2 or b > 62:
        raise ArgumentError('Invalid value for "base" parameter: base must be a whole number between 2 and 62 inclusive.')
    s = value
    neg = False
    body = s
    if body[:1] in ("+", "-"):
        neg = body[0] == "-"
        body = body[1:]
    if not body:
        raise ArgumentError(f'Invalid value for "number" parameter: cannot parse "{s}" as a base {b} integer.')
    total = 0
    for ch in body:
        if ch not in _DIGITS or not ch.isascii():
            raise ArgumentError(f'Invalid value for "number" parameter: cannot parse "{s}" as a base {b} integer.')
        idx = _DIGITS.index(ch)
        if b <= 36 and idx >= 36:
            idx -= 26
        if idx >= b:
            raise ArgumentError(f'Invalid value for "number" parameter: cannot parse "{s}" as a base {b} integer.')
        total = total * b + idx
    return Number.from_int(-total if neg else total)


__all__ = ["go_pow", "Fraction"]

"""CIDR functions: cidrhost, cidrnetmask, cidrsubnet, cidrsubnets."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from .errors import ArgumentError, FuncFail
from .funcs_string import INT64_MAX, INT64_MIN
from .numbers import Number
from .registry import Param, register
from .values import NUMBER, STRING, Value

S = STRING
N = NUMBER

_V4 = re.compile(r"([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})")


@dataclass
class _Net:
    base: int  # network address as an integer (host bits cleared)
    ones: int
    bits: int

    @property
    def is_v4(self) -> bool:
        return self.bits == 32


def _invalid(text: str) -> FuncFail:
    return FuncFail(f"invalid CIDR expression: invalid CIDR address: {text}")


def parse_cidr(text: str) -> _Net:
    """``net.ParseCIDR`` as Terraform's CIDR functions see it."""
    if "/" not in text:
        raise _invalid(text)
    addr, _, mask = text.partition("/")
    if not mask or not mask.isascii() or not mask.isdigit():
        raise _invalid(text)
    ones = int(mask)
    m = _V4.fullmatch(addr)
    if m:
        parts = [int(p) for p in m.groups()]
        if any(p > 255 for p in parts):
            raise _invalid(text)
        value = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
        bits = 32
    else:
        if "%" in addr or ":" not in addr:
            raise _invalid(text)
        try:
            v6 = ipaddress.IPv6Address(addr)
        except ValueError:
            raise _invalid(text) from None
        value = int(v6)
        bits = 128
    if ones > bits:
        raise _invalid(text)
    host_bits = bits - ones
    value = (value >> host_bits) << host_bits
    return _Net(value, ones, bits)


def _fmt_ip(value: int, bits: int) -> str:
    if value < 0:
        value = -value  # big.Int.Bytes() drops the sign
    if bits == 32:
        value &= 0xFFFFFFFF
        return ".".join(str((value >> s) & 0xFF) for s in (24, 16, 8, 0))
    return str(ipaddress.IPv6Address(value & ((1 << 128) - 1)))


def _fmt_net(value: int, ones: int, bits: int) -> str:
    return f"{_fmt_ip(value, bits)}/{ones}"


def _big_whole(n: Number) -> int:
    if n.is_inf or not n.is_int():
        raise FuncFail("value must be a whole number.")
    return n.to_int()


def _int64(n: Number) -> int:
    if n.is_inf or not n.is_int():
        raise FuncFail("value must be a whole number, between -9223372036854775808 and 9223372036854775807.")
    v = n.to_int()
    if v < INT64_MIN or v > INT64_MAX:
        raise FuncFail("value must be a whole number, between -9223372036854775808 and 9223372036854775807.")
    return v


@register("cidrhost", Param("prefix", S), Param("hostnum", N))
def _cidrhost(prefix: str, hostnum: Number) -> Value:
    net = parse_cidr(prefix)
    num = _big_whole(hostnum)
    size = 1 << (net.bits - net.ones)
    if num < 0:
        num = size + num
        if num < 0:
            raise FuncFail(f"prefix of {net.ones} does not accommodate a host numbered {num}")
    elif num <= INT64_MAX and num >= size:
        # go-cidr only range-checks numbers that fit in an int64
        raise FuncFail(f"prefix of {net.ones} does not accommodate a host numbered {num}")
    value = net.base | num
    if value.bit_length() > net.bits:
        raise FuncFail("panic in function implementation: index out of range")
    return _fmt_ip(value, net.bits)


@register("cidrnetmask", Param("prefix", S))
def _cidrnetmask(prefix: str) -> Value:
    net = parse_cidr(prefix)
    if not net.is_v4:
        raise FuncFail(f"IPv6 addresses cannot have a netmask: {prefix}")
    mask = ((1 << net.ones) - 1) << (32 - net.ones) if net.ones else 0
    return _fmt_ip(mask & 0xFFFFFFFF, 32)


_M64 = (1 << 64) - 1


@register("cidrsubnet", Param("prefix", S), Param("newbits", N), Param("netnum", N))
def _cidrsubnet(prefix: str, newbits: Number, netnum: Number) -> Value:
    net = parse_cidr(prefix)
    nb = _int64(newbits)
    nn = _big_whole(netnum)
    newlen = net.ones + nb
    if newlen > net.bits:
        raise FuncFail(f"insufficient address space to extend prefix of {net.ones} by {nb}")
    # go-cidr compares the low 64 bits of |netnum| with (1<<newbits)-1 in uint64 arithmetic
    max_num = ((1 << nb) - 1) if 0 <= nb < 64 else _M64
    if (abs(nn) & _M64) > max_num:
        raise FuncFail(f"prefix extension of {nb} does not accommodate a subnet numbered {nn}")
    if newlen < 0:
        raise FuncFail(f"insufficient address space to extend prefix of {net.ones} by {nb}")
    value = net.base | (nn << (net.bits - newlen))
    if abs(value).bit_length() > net.bits:
        raise FuncFail("panic in function implementation: index out of range")
    return _fmt_net(value, newlen, net.bits)


def _param_err(param: str, msg: str) -> ArgumentError:
    return ArgumentError(f'Invalid value for "{param}" parameter: {msg}.')


def _mask_to(value: int, length: int, bits: int) -> int:
    host = bits - length
    return (value >> host) << host


@register("cidrsubnets", Param("prefix", S), varargs=Param("newbits", N))
def _cidrsubnets(prefix: str, *newbits: Number) -> Value:
    try:
        net = parse_cidr(prefix)
    except FuncFail as exc:
        raise _param_err("prefix", exc.message) from None
    if not newbits:
        return []
    bits = net.bits
    full = (1 << bits) - 1
    net_end = net.base + (1 << (bits - net.ones)) - 1
    try:
        first_len = net.ones + _int64(newbits[0])
    except FuncFail:
        first_len = -1
    # go-cidr PreviousSubnet: the block of first_len that ends just before the network
    if 0 <= first_len <= bits:
        cur_base = _mask_to((net.base - 1) & full, first_len, bits)
        cur_len = first_len
    else:
        cur_base, cur_len = 0, 0
    out: list[str] = []
    for arg in newbits:
        try:
            nb = _int64(arg)
        except FuncFail as exc:
            raise _param_err("newbits", exc.message.rstrip(".")) from None
        if nb < 1:
            raise _param_err("newbits", "must extend prefix by at least one bit")
        if nb > 32:
            raise _param_err("newbits", "may not extend prefix by more than 32 bits")
        length = net.ones + nb
        if length > bits:
            fam = "IPv4" if net.is_v4 else "IPv6"
            raise _param_err("newbits", f"would extend prefix to {length} bits, which is too long for an {fam} address")
        # go-cidr NextSubnet
        last = cur_base | ((1 << (bits - cur_len)) - 1)
        sub_base = _mask_to(last, length, bits)
        sub_last = sub_base | ((1 << (bits - length)) - 1)
        nxt = (sub_last + 1) & full
        rollover = nxt == 0
        next_base = _mask_to(nxt, length, bits)
        if rollover or not (net.base <= next_base <= net_end):
            raise _param_err(
                "newbits",
                f"not enough remaining address space for a subnet with a prefix of {length} bits after {_fmt_net(cur_base, cur_len, bits)}",
            )
        cur_base, cur_len = next_base, length
        out.append(_fmt_net(cur_base, cur_len, bits))
    return out

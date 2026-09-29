"""Type conversion functions: tostring, tonumber, tobool, tolist, toset, tomap."""

from __future__ import annotations

from .errors import ArgumentError, ConversionError
from .registry import Param, register
from .values import (
    BOOL,
    DYNAMIC,
    NUMBER,
    STRING,
    ListT,
    MapT,
    Null,
    SetT,
    Type,
    Value,
    convert,
)

_P = Param("v", DYNAMIC, allow_null=True, allow_unknown=True)


def _make(name: str, target: Type) -> None:
    @register(name, _P)
    def _impl(v: Value) -> Value:
        if isinstance(v, Null):
            return Null(target)
        try:
            return convert(v, target)
        except ConversionError as exc:
            msg = exc.message
            if target == NUMBER and isinstance(v, str):
                msg = f'cannot convert "{v}" to number; given string must be a decimal representation of a number'
            elif target == BOOL and isinstance(v, str):
                msg = f'cannot convert "{v}" to bool; only the strings "true" or "false" are allowed'
            raise ArgumentError(f'Invalid value for "v" parameter: {msg}.') from None


_make("tostring", STRING)
_make("tonumber", NUMBER)
_make("tobool", BOOL)
_make("tolist", ListT(DYNAMIC))
_make("toset", SetT(DYNAMIC))
_make("tomap", MapT(DYNAMIC))

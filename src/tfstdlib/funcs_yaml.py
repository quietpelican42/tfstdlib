"""yamlencode and yamldecode."""

from __future__ import annotations

from .errors import FuncFail
from .registry import Param, register
from .values import DYNAMIC, STRING, Unknown, Value
from .yamlcore import YamlError, decode, encode


@register("yamlencode", Param("value", DYNAMIC, allow_null=True, allow_unknown=True))
def _yamlencode(v: Value) -> Value:
    if isinstance(v, Unknown):
        return Unknown()
    try:
        return encode(v)
    except YamlError as exc:
        raise FuncFail(str(exc)) from None


@register("yamldecode", Param("src", STRING))
def _yamldecode(src: str) -> Value:
    try:
        return decode(src)
    except YamlError as exc:
        raise FuncFail(str(exc)) from None

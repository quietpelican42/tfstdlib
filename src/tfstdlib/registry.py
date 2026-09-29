"""Function registry: signatures, argument checking and dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .errors import ArgumentError, FuncFail, FunctionCallError
from .values import (
    deep_nfc,
    DYNAMIC,
    Type,
    Unknown,
    Value,
    convert,
    is_null,
    is_unknown,
)
from .errors import ConversionError


@dataclass(frozen=True)
class Param:
    """One function parameter."""

    name: str
    type: Type = DYNAMIC
    allow_null: bool = False
    allow_unknown: bool = False


@dataclass
class Function:
    """A registered Terraform function."""

    name: str
    params: list[Param]
    impl: Callable[..., Value]
    varargs: Param | None = None
    #: functions that need the evaluation context (files, working directory)
    needs_context: bool = False
    doc: str = ""
    _extra: dict[str, object] = field(default_factory=dict)

    def check_and_convert(self, args: list[Value]) -> list[Value] | None:
        """Validate ``args``. Returns converted args, or ``None`` if the result is unknown."""
        n = len(self.params)
        if len(args) < n:
            missing = self.params[len(args)].name
            raise ArgumentError(
                f'Not enough arguments: Function "{self.name}" expects {n} argument(s). Missing value for "{missing}".'
            )
        if len(args) > n and self.varargs is None:
            raise ArgumentError(f'Too many arguments: Function "{self.name}" expects only {n} argument(s).')
        out: list[Value] = []
        unknown = False
        for i, a in enumerate(args):
            p = self.params[i] if i < n else self.varargs
            assert p is not None
            label = p.name
            if is_null(a) and not p.allow_null:
                raise ArgumentError(f'Invalid value for "{label}" parameter: argument must not be null.')
            if is_unknown(a):
                if not p.allow_unknown:
                    unknown = True
                out.append(a)
                continue
            try:
                out.append(convert(a, p.type))
            except ConversionError as exc:
                raise ArgumentError(f'Invalid value for "{label}" parameter: {exc.message}.') from None
        if unknown:
            return None
        return out

    def __call__(self, *args: Value, ctx: object | None = None) -> Value:
        conv = self.check_and_convert(list(args))
        if conv is None:
            return Unknown()
        try:
            if self.needs_context:
                return deep_nfc(self.impl(ctx, *conv))
            return deep_nfc(self.impl(*conv))
        except FuncFail as exc:
            raise FunctionCallError(self.name, exc.message) from None


FUNCTIONS: dict[str, Function] = {}


def register(
    name: str,
    *params: Param,
    varargs: Param | None = None,
    needs_context: bool = False,
) -> Callable[[Callable[..., Value]], Callable[..., Value]]:
    """Decorator registering ``impl`` under ``name``."""

    def deco(impl: Callable[..., Value]) -> Callable[..., Value]:
        FUNCTIONS[name] = Function(name, list(params), impl, varargs, needs_context)
        return impl

    return deco

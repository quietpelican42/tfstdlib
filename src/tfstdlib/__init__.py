"""Terraform's built-in functions in pure Python.

    >>> import tfstdlib
    >>> tfstdlib.call("cidrsubnet", "10.0.0.0/16", 8, 3)
    '10.0.3.0/24'
    >>> tfstdlib.evaluate('upper(join("-", ["a", "b"]))')
    'A-B'
"""

from __future__ import annotations

from typing import Any

from . import (  # noqa: F401  (imported for their registrations)
    funcs_collection,
    funcs_conversion,
    funcs_datetime,
    funcs_encoding,
    funcs_file,
    funcs_hash,
    funcs_network,
    funcs_numeric,
    funcs_string,
    funcs_text,
    funcs_yaml,
)
from .console import format_value
from .errors import (
    ArgumentError,
    ConversionError,
    EvalError,
    FunctionCallError,
    ParseError,
    TerraformError,
)
from .hcl import Context, evaluate_value, render_template
from .numbers import Number
from .registry import FUNCTIONS, Function, Param
from .values import (
    NULL,
    UNKNOWN,
    Map,
    Null,
    Object,
    TfSet,
    Unknown,
    Value,
    from_python,
    to_python,
    type_of,
)

__version__ = "0.1.0"

__all__ = [
    "ArgumentError",
    "Context",
    "ConversionError",
    "EvalError",
    "FUNCTIONS",
    "Function",
    "FunctionCallError",
    "Map",
    "NULL",
    "Null",
    "Number",
    "Object",
    "Param",
    "ParseError",
    "TerraformError",
    "TfSet",
    "UNKNOWN",
    "Unknown",
    "Value",
    "call",
    "call_value",
    "can",
    "evaluate",
    "evaluate_value",
    "format_value",
    "from_python",
    "function_names",
    "to_python",
    "try_",
    "type_of",
]


def function_names() -> list[str]:
    """The names of all implemented functions, sorted."""
    return sorted(FUNCTIONS)


def call_value(name: str, *args: Value, base_dir: str | None = None) -> Value:
    """Call a function with Terraform values and return a Terraform value.

    Raises :class:`TerraformError` where Terraform would report an error.
    """
    from .hcl import call_function

    return call_function(name, list(args), Context(base_dir=base_dir))


def call(name: str, *args: Any, base_dir: str | None = None) -> Any:
    """Call a function with native Python data and return native Python data.

    Arguments are converted with :func:`from_python` (``dict`` is an object,
    ``list`` a list, ``tuple`` a tuple, ``set`` a set, ``None`` null); the
    result is converted back with :func:`to_python` (whole numbers become
    ``int``, other numbers ``decimal.Decimal``, sets become sorted lists).
    ``base_dir`` is where the file functions and ``templatefile`` look for
    relative paths.
    """
    return to_python(call_value(name, *[from_python(a) for a in args], base_dir=base_dir))


def evaluate_expression_value(expr: str, variables: dict[str, Any] | None = None, base_dir: str | None = None) -> Value:
    ctx = Context(variables={k: from_python(v) for k, v in (variables or {}).items()}, base_dir=base_dir)
    return evaluate_value(expr, ctx)


def evaluate(expr: str, variables: dict[str, Any] | None = None, base_dir: str | None = None) -> Any:
    """Evaluate a Terraform expression such as ``upper("a")`` or ``[for x in xs : x * 2]``.

    ``variables`` supplies the root names the expression may reference, for
    example ``{"var": {"n": 3}}`` for ``var.n``.
    """
    return to_python(evaluate_expression_value(expr, variables, base_dir))


def can(expr: str, variables: dict[str, Any] | None = None, base_dir: str | None = None) -> bool:
    """Whether ``expr`` evaluates without error (the ``can`` function)."""
    try:
        evaluate_expression_value(expr, variables, base_dir)
    except TerraformError:
        return False
    return True


def try_(*exprs: str, variables: dict[str, Any] | None = None, base_dir: str | None = None) -> Any:
    """Evaluate each expression in turn and return the first that succeeds (the ``try`` function)."""
    errors: list[str] = []
    for e in exprs:
        try:
            return evaluate(e, variables, base_dir)
        except TerraformError as exc:
            errors.append(exc.message)
    raise EvalError("No results: all of the expressions failed: " + "; ".join(errors))

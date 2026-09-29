"""Exception types.

Every failure that Terraform would report as an error diagnostic raises a
subclass of :class:`TerraformError`. The message is modeled on Terraform's
own; the exact wording is not a compatibility promise, the error/no-error
outcome is.
"""

from __future__ import annotations


class TerraformError(Exception):
    """Base class for all errors raised by this package."""

    def __init__(self, message: str, summary: str = "Error") -> None:
        super().__init__(message)
        self.message = message
        self.summary = summary


class ConversionError(TerraformError):
    """A value cannot be converted to the required type."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "Invalid value")


class ArgumentError(TerraformError):
    """A function was called with the wrong number or kind of arguments."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "Invalid function argument")


class FunctionCallError(TerraformError):
    """A function implementation rejected its arguments."""

    def __init__(self, name: str, message: str) -> None:
        super().__init__(f'Call to function "{name}" failed: {message}', "Error in function call")
        self.function = name


class FuncFail(Exception):
    """Raised inside a function body; wrapped into :class:`FunctionCallError`."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EvalError(TerraformError):
    """An expression could not be evaluated (bad index, unknown name, ...)."""


class ParseError(TerraformError):
    """The expression or template text is not syntactically valid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "Invalid syntax")

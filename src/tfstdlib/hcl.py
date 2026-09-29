"""Just enough of HCL's expression and template language to run Terraform functions.

Supported: literals, tuples, objects, function calls (with ``...`` expansion and
``provider::`` / ``core::`` namespaces), operators, conditionals, traversals,
index and splat operators, ``for`` expressions, quoted templates and the
template directives ``%{ if }`` / ``%{ for }`` with ``~`` strip markers.

Not supported: heredocs inside expressions, resource references, the ``self``,
``each`` and ``count`` scopes (they are ordinary undefined names here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import unicodedata

from .errors import ConversionError, EvalError, ParseError, TerraformError
from .numbers import Number, NumberError
from .values import (
    BOOL,
    NULL,
    NUMBER,
    STRING,
    UNKNOWN,
    Map,
    Null,
    Object,
    TfSet,
    Type,
    Unknown,
    Value,
    convert,
    type_of,
    unify,
    values_equal,
)


class StaticError(EvalError):
    """A reference Terraform rejects before evaluation; ``try`` and ``can`` do not catch it."""


# ---------------------------------------------------------------------------
# evaluation context
# ---------------------------------------------------------------------------


@dataclass
class Context:
    """Everything an expression can see besides its own literals."""

    variables: dict[str, Value] = field(default_factory=dict)
    base_dir: str | None = None
    #: extra or overriding functions: name -> callable(ctx, *args)
    functions: dict[str, Callable[..., Value]] = field(default_factory=dict)
    #: False inside a template file (Terraform forbids nested templatefile)
    allow_template_functions: bool = True


class Scope:
    def __init__(self, ctx: Context, names: dict[str, Value] | None = None, parent: "Scope | None" = None) -> None:
        self.ctx = ctx
        self.names = names or {}
        self.parent = parent

    def child(self, names: dict[str, Value]) -> "Scope":
        return Scope(self.ctx, names, self)

    def lookup(self, name: str) -> Value:
        s: Scope | None = self
        while s is not None:
            if name in s.names:
                return s.names[name]
            s = s.parent
        if name in self.ctx.variables:
            return self.ctx.variables[name]
        raise StaticError(f'Reference to undeclared name "{name}".')


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


class Node:
    def eval(self, sc: Scope) -> Value:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class Lit(Node):
    value: Value

    def eval(self, sc: Scope) -> Value:
        return self.value


@dataclass
class Name(Node):
    name: str

    def eval(self, sc: Scope) -> Value:
        return sc.lookup(self.name)


@dataclass
class TupleCons(Node):
    items: list[Node]

    def eval(self, sc: Scope) -> Value:
        return tuple(i.eval(sc) for i in self.items)


@dataclass
class ObjectCons(Node):
    items: list[tuple[Node, Node, bool]]  # key expr, value expr, key is a bare name

    def eval(self, sc: Scope) -> Value:
        out: dict[str, Value] = {}
        for k, v, _bare in self.items:
            kv = k.eval(sc)
            if isinstance(kv, Null):
                raise EvalError("Null value as key: Can't use a null value as a key.")
            if isinstance(kv, Unknown):
                return UNKNOWN
            try:
                ks = convert(kv, STRING)
            except ConversionError as exc:
                raise EvalError(f"Incorrect key type: {exc.message}.") from None
            out[ks] = v.eval(sc)
        return Object(out)


@dataclass
class Unary(Node):
    op: str
    operand: Node

    def eval(self, sc: Scope) -> Value:
        v = self.operand.eval(sc)
        if isinstance(v, Unknown):
            return v
        if self.op == "-":
            n = _to_num(v, "operand")
            return n.neg()
        b = _to_bool(v, "operand")
        return not b


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node

    def eval(self, sc: Scope) -> Value:
        op = self.op
        if op in ("&&", "||"):
            lv = self.left.eval(sc)
            if isinstance(lv, Unknown):
                return lv
            lb = False if isinstance(lv, Null) else _to_bool(lv, "operand")
            if op == "&&" and not lb:
                self.right.eval(sc)
                return False
            if op == "||" and lb:
                self.right.eval(sc)
                return True
            rv = self.right.eval(sc)
            if isinstance(rv, Unknown):
                return rv
            return False if isinstance(rv, Null) else _to_bool(rv, "operand")
        lv = self.left.eval(sc)
        rv = self.right.eval(sc)
        if isinstance(lv, Unknown) or isinstance(rv, Unknown):
            return UNKNOWN
        if op == "==":
            return values_equal(lv, rv)
        if op == "!=":
            return not values_equal(lv, rv)
        a = _to_num(lv, "operand")
        b = _to_num(rv, "operand")
        try:
            if op == "+":
                return a.add(b)
            if op == "-":
                return a.sub(b)
            if op == "*":
                return a.mul(b)
            if op == "/":
                return a.div(b)
            if op == "%":
                return a.mod(b)
        except NumberError as exc:
            raise EvalError(f"Error during operation: {exc}.") from None
        c = a.cmp(b)
        if op == "<":
            return c < 0
        if op == "<=":
            return c <= 0
        if op == ">":
            return c > 0
        if op == ">=":
            return c >= 0
        raise EvalError(f"unknown operator {op}")


def _to_num(v: Value, what: str) -> Number:
    if isinstance(v, Null):
        raise EvalError(f"Invalid {what}: Unsuitable value: a number is required.")
    try:
        r = convert(v, NUMBER)
    except ConversionError as exc:
        raise EvalError(f"Invalid {what}: Unsuitable value: {exc.message}.") from None
    assert isinstance(r, Number)
    return r


def _to_bool(v: Value, what: str) -> bool:
    if isinstance(v, Null):
        raise EvalError(f"Invalid {what}: Unsuitable value: a bool is required.")
    try:
        r = convert(v, BOOL)
    except ConversionError as exc:
        raise EvalError(f"Invalid {what}: Unsuitable value: {exc.message}.") from None
    assert isinstance(r, bool)
    return r


@dataclass
class Conditional(Node):
    cond: Node
    then: Node
    other: Node

    def eval(self, sc: Scope) -> Value:
        c = self.cond.eval(sc)
        tv: Value = None
        fv: Value = None
        terr: TerraformError | None = None
        ferr: TerraformError | None = None
        try:
            tv = self.then.eval(sc)
        except TerraformError as exc:
            terr = exc
        try:
            fv = self.other.eval(sc)
        except TerraformError as exc:
            ferr = exc
        if isinstance(c, Null):
            raise EvalError("Invalid condition: The condition value is null. Conditions must either be true or false.")
        if isinstance(c, Unknown):
            return UNKNOWN
        try:
            cb = convert(c, BOOL)
        except ConversionError:
            raise EvalError("Incorrect condition type: The condition expression must be of type bool.") from None
        if cb and terr:
            raise terr
        if not cb and ferr:
            raise ferr
        chosen = tv if cb else fv
        if terr is None and ferr is None:
            ta, tb = type_of(tv), type_of(fv)
            u = unify([ta, tb], unsafe=True)
            if u is None:
                raise EvalError(
                    "Inconsistent conditional result types: The true and false result expressions must have consistent types. "
                    f"The 'true' value is {_kind_name(ta)}, but the 'false' value is {_kind_name(tb)}."
                )
            try:
                chosen = convert(chosen, u)
            except ConversionError as exc:
                raise EvalError(f"Inconsistent conditional result types: {exc.message}.") from None
        return chosen


def _kind_name(t: Type) -> str:
    return t.friendly()


@dataclass
class Attr(Node):
    source: Node
    name: str

    def eval(self, sc: Scope) -> Value:
        return get_attr(self.source.eval(sc), self.name)


@dataclass
class Index(Node):
    source: Node
    key: Node

    def eval(self, sc: Scope) -> Value:
        return get_index(self.source.eval(sc), self.key.eval(sc))


@dataclass
class LegacyIndex(Node):
    source: Node
    index: str

    def eval(self, sc: Scope) -> Value:
        return get_index(self.source.eval(sc), Number.parse(self.index) or NULL)


def get_attr(src: Value, name: str) -> Value:
    if isinstance(src, Unknown):
        return src
    if isinstance(src, Null):
        raise EvalError("Attempt to get attribute from null value: This value is null, so it does not have any attributes.")
    if isinstance(src, (Object, Map)):
        if name in src:
            return src[name]
        if isinstance(src, Map):
            raise EvalError(f'Invalid index: The given key does not identify an element in this collection value.')
        raise EvalError(f'Unsupported attribute: This object does not have an attribute named "{name}".')
    raise EvalError("Unsupported attribute: Can't access attributes on a primitive-typed value.")


def get_index(src: Value, key: Value) -> Value:
    if isinstance(src, Unknown) or isinstance(key, Unknown):
        return UNKNOWN
    if isinstance(src, Null):
        raise EvalError("Attempt to index null value: This value is null, so it does not have any indices.")
    if isinstance(key, Null):
        raise EvalError("Invalid index: Key must be a string or number, not null.")
    if isinstance(src, (list, tuple)):
        try:
            k = convert(key, NUMBER)
        except ConversionError:
            raise EvalError("Invalid index: The given key does not identify an element in this collection value: a number is required.") from None
        assert isinstance(k, Number)
        if not k.is_int() or k.is_inf:
            raise EvalError("Invalid index: The given key does not identify an element in this collection value: a whole number is required.")
        i = k.to_int()
        if i < 0 or i >= len(src):
            raise EvalError("Invalid index: The given key does not identify an element in this collection value.")
        return src[i]
    if isinstance(src, (Object, Map)):
        try:
            k2 = convert(key, STRING)
        except ConversionError:
            raise EvalError("Invalid index: The given key does not identify an element in this collection value: a string is required.") from None
        if k2 in src:
            return src[k2]
        raise EvalError("Invalid index: The given key does not identify an element in this collection value.")
    if isinstance(src, TfSet):
        raise EvalError("Invalid index: This value does not have any indices.")
    raise EvalError("Invalid index: This value does not have any indices.")


@dataclass
class Splat(Node):
    source: Node
    ops: list[tuple[str, Any]]  # ("attr", name) | ("index", Node) | ("legacy", str)

    def eval(self, sc: Scope) -> Value:
        src = self.source.eval(sc)
        if isinstance(src, Unknown):
            return src
        if isinstance(src, Null):
            return ()
        if isinstance(src, (list, tuple, TfSet)):
            items = list(src)
        else:
            items = [src]
        out = []
        for it in items:
            cur = it
            for kind, arg in self.ops:
                if kind == "attr":
                    cur = get_attr(cur, arg)
                elif kind == "index":
                    cur = get_index(cur, arg.eval(sc))
                else:
                    cur = get_index(cur, Number.parse(arg) or NULL)
            out.append(cur)
        if isinstance(src, (list, TfSet)) and out:
            u = unify([type_of(x) for x in out])
            if u is not None:
                return [convert(x, u) for x in out]
        if isinstance(src, (list, TfSet)):
            return []
        return tuple(out)


@dataclass
class Call(Node):
    name: str
    args: list[Node]
    expand_last: bool = False

    def eval(self, sc: Scope) -> Value:
        name = self.name
        if name.startswith("core::"):
            name = name[len("core::") :]
        if name in ("try", "can") and name not in sc.ctx.functions:
            if name == "can":
                if len(self.args) != 1 or self.expand_last:
                    raise EvalError('Invalid function arguments: Function "can" expects exactly one argument.')
                try:
                    v = self.args[0].eval(sc)
                except StaticError:
                    raise
                except TerraformError:
                    return False
                return True if not isinstance(v, Unknown) else UNKNOWN
            if not self.args:
                raise EvalError('Not enough arguments: Function "try" expects at least 1 argument(s).')
            errs: list[str] = []
            for a in self.args:
                try:
                    v = a.eval(sc)
                except StaticError:
                    raise
                except TerraformError as exc:
                    errs.append(exc.message)
                    continue
                return v
            raise EvalError("No results: all of the expressions failed: " + "; ".join(errs))
        args = [a.eval(sc) for a in self.args]
        if self.expand_last:
            last = args.pop()
            if isinstance(last, Unknown):
                return UNKNOWN
            if not isinstance(last, (list, tuple, TfSet)):
                raise EvalError("Invalid expanding argument value: The expanding argument (indicated by ...) must be of a tuple, list, or set type.")
            args.extend(list(last))
        return call_function(name, args, sc.ctx)


def call_function(name: str, args: list[Value], ctx: Context) -> Value:
    from .registry import FUNCTIONS

    override = ctx.functions.get(name)
    if override is not None:
        return override(ctx, *args)
    fn = FUNCTIONS.get(name)
    if fn is None:
        raise EvalError(f'Call to unknown function: There is no function named "{name}".')
    if fn.name in ("templatefile", "templatestring") and not ctx.allow_template_functions:
        raise EvalError(f'Call to unknown function: There is no function named "{name}".')
    return fn(*args, ctx=ctx)


@dataclass
class ForTuple(Node):
    kvar: str | None
    vvar: str
    coll: Node
    body: Node
    cond: Node | None

    def eval(self, sc: Scope) -> Value:
        out = []
        for names in _iterate(self.coll.eval(sc), self.kvar, self.vvar):
            inner = sc.child(names)
            if self.cond is not None:
                c = self.cond.eval(inner)
                if isinstance(c, Unknown):
                    return UNKNOWN
                if not _to_bool(c, "for condition"):
                    continue
            out.append(self.body.eval(inner))
        return tuple(out)


@dataclass
class ForObject(Node):
    kvar: str | None
    vvar: str
    coll: Node
    key: Node
    val: Node
    cond: Node | None
    group: bool

    def eval(self, sc: Scope) -> Value:
        out: dict[str, Value] = {}
        for names in _iterate(self.coll.eval(sc), self.kvar, self.vvar):
            inner = sc.child(names)
            if self.cond is not None:
                c = self.cond.eval(inner)
                if isinstance(c, Unknown):
                    return UNKNOWN
                if not _to_bool(c, "for condition"):
                    continue
            k = self.key.eval(inner)
            if isinstance(k, Null):
                raise EvalError("Invalid object key: Key expression in for expression must not be null.")
            if isinstance(k, Unknown):
                return UNKNOWN
            try:
                ks = convert(k, STRING)
            except ConversionError as exc:
                raise EvalError(f"Invalid object key: {exc.message}.") from None
            v = self.val.eval(inner)
            if self.group:
                out.setdefault(ks, []).append(v)
            else:
                if ks in out:
                    raise EvalError(f'Duplicate object key: Two different items produced the key "{ks}" in this \'for\' expression. If duplicates are expected, use the ellipsis (...) after the value expression to enable grouping by key.')
                out[ks] = v
        if self.group:
            return Object({k: tuple(v) for k, v in out.items()})
        return Object(out)


def _iterate(coll: Value, kvar: str | None, vvar: str) -> list[dict[str, Value]]:
    if isinstance(coll, Null):
        raise EvalError("Iteration over null value: A null value cannot be used as the collection in a 'for' expression.")
    if isinstance(coll, Unknown):
        raise EvalError("Iteration over unknown value")
    items: list[tuple[Value, Value]]
    if isinstance(coll, (list, tuple)):
        items = [(Number.from_int(i), v) for i, v in enumerate(coll)]
    elif isinstance(coll, TfSet):
        items = [(v, v) for v in coll]
    elif isinstance(coll, (Map, Object)):
        items = [(k, v) for k, v in coll.items()]
    else:
        raise EvalError("Iteration over non-iterable value: A value of type " + type_of(coll).friendly() + " cannot be used as the collection in a 'for' expression.")
    out = []
    for k, v in items:
        names = {vvar: v}
        if kvar is not None:
            names[kvar] = k
        out.append(names)
    return out


# --- templates ---------------------------------------------------------------


class TNode:
    pass


@dataclass
class TLit(TNode):
    text: str


@dataclass
class TInterp(TNode):
    expr: Node


@dataclass
class TIf(TNode):
    cond: Node
    then: list[TNode]
    other: list[TNode] | None


@dataclass
class TFor(TNode):
    kvar: str | None
    vvar: str
    coll: Node
    body: list[TNode]


@dataclass
class TemplateExpr(Node):
    parts: list[TNode]

    def eval(self, sc: Scope) -> Value:
        # A template that is exactly one interpolation yields the value unchanged.
        if len(self.parts) == 1 and isinstance(self.parts[0], TInterp):
            return self.parts[0].expr.eval(sc)
        return _render(self.parts, sc)


def nfc(s: str) -> str:
    return s if s.isascii() else unicodedata.normalize("NFC", s)


def _render(parts: list[TNode], sc: Scope) -> Value:
    r = _render_raw(parts, sc)
    return nfc(r) if isinstance(r, str) else r


def _render_raw(parts: list[TNode], sc: Scope) -> Value:
    out: list[str] = []
    for p in parts:
        if isinstance(p, TLit):
            out.append(p.text)
        elif isinstance(p, TInterp):
            v = p.expr.eval(sc)
            if isinstance(v, Unknown):
                return UNKNOWN
            out.append(_template_string(v))
        elif isinstance(p, TIf):
            c = p.cond.eval(sc)
            if isinstance(c, Unknown):
                return UNKNOWN
            if isinstance(c, Null):
                raise EvalError("Invalid template condition: The condition value is null. Conditions must either be true or false.")
            try:
                cb = convert(c, BOOL)
            except ConversionError:
                raise EvalError("Incorrect condition type: The condition expression must be of type bool.") from None
            branch = p.then if cb else (p.other or [])
            r = _render_raw(branch, sc)
            if isinstance(r, Unknown):
                return r
            out.append(r)
        elif isinstance(p, TFor):
            for names in _iterate(p.coll.eval(sc), p.kvar, p.vvar):
                r = _render_raw(p.body, sc.child(names))
                if isinstance(r, Unknown):
                    return r
                out.append(r)
    return "".join(out)


def _template_string(v: Value) -> str:
    if isinstance(v, Null):
        raise EvalError("Invalid template interpolation value: The expression result is null. Cannot include a null value in a string template.")
    try:
        r = convert(v, STRING)
    except ConversionError:
        raise EvalError(
            f"Invalid template interpolation value: Cannot include the given value in a string template: string required, but have {type_of(v).friendly()}."
        ) from None
    assert isinstance(r, str)
    return r


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

_KEYWORDS = {"true": True, "false": False}

_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def _is_ident_start(c: str) -> bool:
    return c.isalpha() or c == "_"


def _is_ident_part(c: str) -> bool:
    return c.isalnum() or c in "_-"


class Parser:
    def __init__(self, src: str) -> None:
        self.s = src
        self.i = 0
        self.n = len(src)

    # -- helpers --
    def err(self, msg: str) -> ParseError:
        return ParseError(f"{msg} (at offset {self.i})")

    def ws(self, newlines: bool = True) -> bool:
        """Skip whitespace and comments. Returns True if a newline was skipped."""
        saw_nl = False
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r":
                self.i += 1
            elif c == "\n":
                if not newlines:
                    break
                saw_nl = True
                self.i += 1
            elif c == "#" or s.startswith("//", self.i):
                while self.i < self.n and s[self.i] != "\n":
                    self.i += 1
            elif s.startswith("/*", self.i):
                j = s.find("*/", self.i + 2)
                if j < 0:
                    raise self.err("Unterminated comment")
                if "\n" in s[self.i : j]:
                    saw_nl = True
                self.i = j + 2
            else:
                break
        return saw_nl

    def peek(self) -> str:
        return self.s[self.i] if self.i < self.n else ""

    def starts(self, t: str) -> bool:
        return self.s.startswith(t, self.i)

    def expect(self, t: str) -> None:
        self.ws()
        if not self.starts(t):
            raise self.err(f"Expected {t!r}")
        self.i += len(t)

    # -- entry points --
    def parse_all(self) -> Node:
        self.ws()
        if self.i >= self.n:
            raise ParseError("Missing expression: Expected the start of an expression, but found the end of the file.")
        e = self.expression()
        self.ws()
        if self.i < self.n:
            raise self.err("Extra characters after expression")
        return e

    # -- expressions --
    def expression(self) -> Node:
        self.ws()
        cond = self.binary(0)
        self.ws()
        if self.peek() == "?":
            self.i += 1
            a = self.expression()
            self.expect(":")
            b = self.expression()
            return Conditional(cond, a, b)
        return cond

    _LEVELS: list[list[str]] = [["||"], ["&&"], ["==", "!="], ["<=", ">=", "<", ">"], ["+", "-"], ["*", "/", "%"]]

    def binary(self, level: int) -> Node:
        if level >= len(self._LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while True:
            self.ws()
            op = None
            for cand in self._LEVELS[level]:
                if self.starts(cand):
                    # avoid mis-lexing '=>' as '=' etc: only longer operators listed first
                    if cand in ("<", ">") and self.s.startswith(cand + "=", self.i):
                        continue
                    if cand == "|" or (cand == "&" ):
                        continue
                    op = cand
                    break
            if op is None:
                return left
            self.i += len(op)
            right = self.binary(level + 1)
            left = Binary(op, left, right)

    def unary(self) -> Node:
        self.ws()
        c = self.peek()
        if c == "-":
            self.i += 1
            operand = self.unary()
            if isinstance(operand, Lit) and isinstance(operand.value, Number):
                return Lit(operand.value.neg())
            return Unary("-", operand)
        if c == "!":
            self.i += 1
            return Unary("!", self.unary())
        return self.postfix(self.primary())

    def postfix(self, node: Node) -> Node:
        while True:
            # no whitespace skipping before '.' or '[' is required by HCL, but tolerate spaces
            save = self.i
            self.ws(newlines=False)
            c = self.peek()
            if c == ".":
                if self.starts("..."):
                    self.i = save
                    return node
                self.i += 1
                self.ws(newlines=False)
                if self.peek() == "*":
                    self.i += 1
                    return Splat(node, self.splat_ops())
                if self.peek().isdigit():
                    j = self.i
                    while j < self.n and self.s[j].isdigit():
                        j += 1
                    if j + 1 < self.n and self.s[j] == "." and self.s[j + 1].isdigit():
                        raise self.err("Invalid attribute name")
                    node = LegacyIndex(node, self.s[self.i : j])
                    self.i = j
                    continue
                name = self.ident()
                if name is None:
                    raise self.err("Invalid attribute name")
                node = Attr(node, name)
            elif c == "[":
                self.i += 1
                self.ws()
                if self.peek() == "*":
                    self.i += 1
                    self.expect("]")
                    return Splat(node, self.splat_ops())
                key = self.expression()
                self.expect("]")
                node = Index(node, key)
            else:
                self.i = save
                return node

    def splat_ops(self) -> list[tuple[str, Any]]:
        ops: list[tuple[str, Any]] = []
        while True:
            save = self.i
            self.ws(newlines=False)
            c = self.peek()
            if c == ".":
                if self.starts("..."):
                    self.i = save
                    return ops
                self.i += 1
                if self.peek().isdigit():
                    j = self.i
                    while j < self.n and self.s[j].isdigit():
                        j += 1
                    ops.append(("legacy", self.s[self.i : j]))
                    self.i = j
                    continue
                name = self.ident()
                if name is None:
                    raise self.err("Invalid attribute name")
                ops.append(("attr", name))
            elif c == "[":
                self.i += 1
                key = self.expression()
                self.expect("]")
                ops.append(("index", key))
            else:
                self.i = save
                return ops

    def ident(self) -> str | None:
        if self.i < self.n and _is_ident_start(self.s[self.i]):
            j = self.i + 1
            while j < self.n and _is_ident_part(self.s[j]):
                j += 1
            # a trailing dash is not part of an identifier
            while self.s[j - 1] == "-":
                j -= 1
            name = self.s[self.i : j]
            self.i = j
            return name
        return None

    def primary(self) -> Node:
        self.ws()
        c = self.peek()
        if c == "":
            raise ParseError("Missing expression: Expected the start of an expression, but found the end of the file.")
        if c.isdigit():
            return self.number()
        if c == '"':
            return self.quoted()
        if c == "(":
            self.i += 1
            e = self.expression()
            self.expect(")")
            return e
        if c == "[":
            return self.tuple_or_for()
        if c == "{":
            return self.object_or_for()
        if self.starts("<<"):
            raise self.err("Heredocs are not supported in expressions")
        if _is_ident_start(c):
            name = self.ident()
            assert name is not None
            # namespaced function: a::b::c(
            while self.starts("::"):
                self.i += 2
                part = self.ident()
                if part is None:
                    raise self.err("Invalid function name")
                name += "::" + part
            self.ws(newlines=False)
            if self.peek() == "(":
                return self.call(name)
            if "::" in name:
                raise self.err("Invalid function call")
            if name in _KEYWORDS:
                return Lit(_KEYWORDS[name])
            if name == "null":
                return Lit(NULL)
            return Name(name)
        raise self.err(f"Invalid character {c!r}")

    def number(self) -> Node:
        s = self.s
        j = self.i
        while j < self.n and s[j].isdigit():
            j += 1
        if j < self.n and s[j] == "." and j + 1 < self.n and s[j + 1].isdigit():
            j += 1
            while j < self.n and s[j].isdigit():
                j += 1
        if j < self.n and s[j] in "eE":
            k = j + 1
            if k < self.n and s[k] in "+-":
                k += 1
            if k < self.n and s[k].isdigit():
                while k < self.n and s[k].isdigit():
                    k += 1
                j = k
        text = s[self.i : j]
        if j < self.n and (s[j].isalpha() or s[j] == "_"):
            raise self.err("Invalid character in number")
        self.i = j
        n = Number.parse(text)
        if n is None:
            raise self.err("Invalid number")
        return Lit(n)

    def call(self, name: str) -> Node:
        self.expect("(")
        args: list[Node] = []
        expand = False
        while True:
            self.ws()
            if self.peek() == ")":
                self.i += 1
                break
            args.append(self.expression())
            self.ws()
            if self.starts("..."):
                self.i += 3
                expand = True
                self.ws()
                if self.peek() != ")":
                    raise self.err("Expanding argument must be last")
                self.i += 1
                break
            if self.peek() == ",":
                self.i += 1
                continue
            if self.peek() == ")":
                self.i += 1
                break
            raise self.err("Expected ',' or ')' in function call")
        return Call(name, args, expand)

    def tuple_or_for(self) -> Node:
        self.expect("[")
        self.ws()
        if self.starts_word("for"):
            self.i += 3
            kvar, vvar = self.for_vars()
            coll = self.expression()
            self.expect(":")
            body = self.expression()
            cond = self.for_cond()
            self.expect("]")
            return ForTuple(kvar, vvar, coll, body, cond)
        items: list[Node] = []
        while True:
            self.ws()
            if self.peek() == "]":
                self.i += 1
                break
            items.append(self.expression())
            self.ws()
            if self.peek() == ",":
                self.i += 1
                continue
            if self.peek() == "]":
                self.i += 1
                break
            raise self.err("Expected ',' or ']' in tuple")
        return TupleCons(items)

    def starts_word(self, w: str) -> bool:
        if not self.starts(w):
            return False
        j = self.i + len(w)
        return j >= self.n or not _is_ident_part(self.s[j])

    def for_vars(self) -> tuple[str | None, str]:
        self.ws()
        a = self.ident()
        if a is None:
            raise self.err("Expected a variable name in 'for'")
        self.ws()
        b = None
        if self.peek() == ",":
            self.i += 1
            self.ws()
            b = self.ident()
            if b is None:
                raise self.err("Expected a variable name in 'for'")
            self.ws()
        if not self.starts_word("in"):
            raise self.err("Expected 'in'")
        self.i += 2
        if b is None:
            return None, a
        return a, b

    def for_cond(self) -> Node | None:
        self.ws()
        if self.starts_word("if"):
            self.i += 2
            return self.expression()
        return None

    def object_or_for(self) -> Node:
        self.expect("{")
        self.ws()
        if self.starts_word("for"):
            self.i += 3
            kvar, vvar = self.for_vars()
            coll = self.expression()
            self.expect(":")
            key = self.expression()
            self.expect("=>")
            val = self.expression()
            group = False
            self.ws()
            if self.starts("..."):
                self.i += 3
                group = True
            cond = self.for_cond()
            self.expect("}")
            return ForObject(kvar, vvar, coll, key, val, cond, group)
        items: list[tuple[Node, Node, bool]] = []
        while True:
            self.ws()
            if self.peek() == "}":
                self.i += 1
                break
            key, bare = self.object_key()
            self.ws()
            if self.peek() in ("=", ":") and not self.starts("=="):
                self.i += 1
            else:
                raise self.err("Expected '=' or ':' after object key")
            val = self.expression()
            items.append((key, val, bare))
            # separator: comma or newline
            nl = self.ws()
            if self.peek() == ",":
                self.i += 1
                continue
            if self.peek() == "}":
                self.i += 1
                break
            if nl:
                continue
            raise self.err("Missing item separator: expected a comma or newline")
        return ObjectCons(items)

    def object_key(self) -> tuple[Node, bool]:
        self.ws()
        c = self.peek()
        if c == "(":
            self.i += 1
            e = self.expression()
            self.expect(")")
            return e, False
        if _is_ident_start(c):
            save = self.i
            name = self.ident()
            assert name is not None
            self.ws(newlines=False)
            if self.peek() in ("=", ":") and not self.starts("=="):
                if name in _KEYWORDS:
                    return Lit(_KEYWORDS[name]), False
                if name == "null":
                    return Lit(NULL), False
                return Lit(name), True
            self.i = save
        e = self.postfix(self.primary()) if c != "-" else self.unary()
        return e, False

    # -- quoted string / template --
    def quoted(self) -> Node:
        assert self.peek() == '"'
        self.i += 1
        items = _scan_template(self, quoted=True)
        parts = _build_template(items)
        # plain literals become string literals
        if not parts:
            return Lit("")
        if all(isinstance(p, TLit) for p in parts):
            return Lit(nfc("".join(p.text for p in parts if isinstance(p, TLit))))
        return TemplateExpr(parts)


# --- template scanning ---------------------------------------------------------


@dataclass
class _Tok:
    kind: str  # lit | interp | if | else | endif | for | endfor
    text: str = ""
    expr: Node | None = None
    kvar: str | None = None
    vvar: str = ""
    lstrip: bool = False
    rstrip: bool = False


def _scan_template(p: Parser, quoted: bool) -> list[_Tok]:
    s = p.s
    toks: list[_Tok] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            toks.append(_Tok("lit", "".join(buf)))
            buf.clear()

    while True:
        if p.i >= p.n:
            if quoted:
                raise ParseError("Unterminated template string: No closing quote found.")
            break
        c = s[p.i]
        if quoted and c == '"':
            p.i += 1
            break
        if quoted and c == "\n":
            raise ParseError("Invalid multi-line string: Quoted strings may not be split over multiple lines.")
        if c == "\\" and quoted:
            if p.i + 1 >= p.n:
                raise ParseError("Invalid escape sequence")
            e = s[p.i + 1]
            if e in _ESCAPES:
                buf.append(_ESCAPES[e])
                p.i += 2
            elif e in "uU":
                width = 4 if e == "u" else 8
                hexs = s[p.i + 2 : p.i + 2 + width]
                if len(hexs) != width or not all(h in "0123456789abcdefABCDEF" for h in hexs):
                    raise ParseError(f"Invalid escape sequence: This escape sequence is missing its hexadecimal digits.")
                cp = int(hexs, 16)
                if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
                    raise ParseError("Invalid escape sequence: invalid code point")
                buf.append(chr(cp))
                p.i += 2 + width
            else:
                raise ParseError(f'Invalid escape sequence: The symbol "{e}" is not a valid escape sequence selector.')
            continue
        if c in "$%" and s.startswith(c * 2 + "{", p.i):
            buf.append(c + "{")
            p.i += 3
            continue
        if c in "$%" and s.startswith("{", p.i + 1):
            flush()
            p.i += 2
            lstrip = False
            if p.peek() == "~":
                lstrip = True
                p.i += 1
            if c == "$":
                interp = p.expression()
                p.ws()
                rstrip = False
                if p.peek() == "~":
                    rstrip = True
                    p.i += 1
                if p.peek() != "}":
                    raise ParseError("Extra characters after interpolation expression: Expected a closing brace to end the interpolation expression, but found extra characters.")
                p.i += 1
                toks.append(_Tok("interp", expr=interp, lstrip=lstrip, rstrip=rstrip))
            else:
                p.ws()
                if p.starts_word("if"):
                    p.i += 2
                    tok = _Tok("if", expr=p.expression())
                elif p.starts_word("else"):
                    p.i += 4
                    tok = _Tok("else")
                elif p.starts_word("endif"):
                    p.i += 5
                    tok = _Tok("endif")
                elif p.starts_word("for"):
                    p.i += 3
                    kvar, vvar = p.for_vars()
                    tok = _Tok("for", expr=p.expression(), kvar=kvar, vvar=vvar)
                elif p.starts_word("endfor"):
                    p.i += 6
                    tok = _Tok("endfor")
                else:
                    raise ParseError("Invalid template directive: Expected an if or for directive.")
                p.ws()
                rstrip = False
                if p.peek() == "~":
                    rstrip = True
                    p.i += 1
                if p.peek() != "}":
                    raise ParseError("Extra characters after template directive: Expected a closing brace to end the sequence, but found extra characters.")
                p.i += 1
                tok.lstrip = lstrip
                tok.rstrip = rstrip
                toks.append(tok)
            continue
        buf.append(c)
        p.i += 1
    flush()
    return toks


def _build_template(toks: list[_Tok], chunked: bool = False) -> list[TNode]:
    # strip markers
    for idx, t in enumerate(toks):
        if t.kind == "lit":
            continue
        if t.lstrip and idx > 0 and toks[idx - 1].kind == "lit":
            toks[idx - 1].text = _rstrip_space(toks[idx - 1].text, chunked)
        if t.rstrip and idx + 1 < len(toks) and toks[idx + 1].kind == "lit":
            toks[idx + 1].text = _lstrip_space(toks[idx + 1].text, chunked)
    pos = 0

    def parse_seq(stop: set[str]) -> tuple[list[TNode], str | None]:
        nonlocal pos
        out: list[TNode] = []
        while pos < len(toks):
            t = toks[pos]
            if t.kind in stop:
                return out, t.kind
            pos += 1
            if t.kind == "lit":
                if t.text:
                    out.append(TLit(t.text))
            elif t.kind == "interp":
                assert t.expr is not None
                out.append(TInterp(t.expr))
            elif t.kind == "if":
                assert t.expr is not None
                then, end = parse_seq({"else", "endif"})
                other: list[TNode] | None = None
                if end == "else":
                    pos += 1
                    other, end = parse_seq({"endif"})
                if end != "endif":
                    raise ParseError("Unclosed template directive: There is no matching %{ endif } for this %{ if } directive.")
                pos += 1
                out.append(TIf(t.expr, then, other))
            elif t.kind == "for":
                assert t.expr is not None
                body, end = parse_seq({"endfor"})
                if end != "endfor":
                    raise ParseError("Unclosed template directive: There is no matching %{ endfor } for this %{ for } directive.")
                pos += 1
                out.append(TFor(t.kvar, t.vvar, t.expr, body))
            elif t.kind == "else":
                raise ParseError("Unexpected else directive: Unexpected %{ else } directive.")
            elif t.kind == "endif":
                raise ParseError("Unexpected endif directive: Unexpected %{ endif } directive.")
            elif t.kind == "endfor":
                raise ParseError("Unexpected endfor directive: Unexpected %{ endfor } directive.")
        return out, None

    parts, end = parse_seq(set())
    return parts


def _rstrip_space(s: str, chunked: bool = False) -> str:
    """Strip trailing whitespace; in a template file only the last line-sized chunk is affected."""
    if not chunked:
        return s.rstrip(_SPACE_CHARS)
    cut = s.rfind("\n", 0, max(len(s) - 1, 0)) + 1
    return s[:cut] + s[cut:].rstrip(_SPACE_CHARS)


def _lstrip_space(s: str, chunked: bool = False) -> str:
    if not chunked:
        return s.lstrip(_SPACE_CHARS)
    nl = s.find("\n")
    end = len(s) if nl < 0 else nl + 1
    return s[:end].lstrip(_SPACE_CHARS) + s[end:]


_SPACE_CHARS = " \t\n\r\f\v\x1c\x1d\x1e\x1f\x85\xa0                　"


def parse_expression(src: str) -> Node:
    """Parse ``src`` as a single HCL expression."""
    return Parser(src).parse_all()


def parse_template(text: str) -> list[TNode]:
    """Parse ``text`` as a bare template (the content of a template file)."""
    p = Parser(text)
    toks = _scan_template(p, quoted=False)
    return _build_template(toks, chunked=True)


def render_template(text: str, ctx: Context, variables: dict[str, Value] | None = None) -> Value:
    """Evaluate a bare template against ``variables``."""
    parts = parse_template(text)
    sc = Scope(ctx, dict(variables or {}))
    if not parts:
        return ""
    if len(parts) == 1 and isinstance(parts[0], TInterp):
        # a file template is always a string, even for a single interpolation
        v = parts[0].expr.eval(sc)
        if isinstance(v, Unknown):
            return v
        return _template_string(v)
    return _render(parts, sc)


def evaluate_value(expr: str, ctx: Context | None = None) -> Value:
    """Parse and evaluate ``expr``, returning a Terraform value."""
    c = ctx or Context()
    node = parse_expression(expr)
    return node.eval(Scope(c, builtin_scope(c)))


def builtin_scope(ctx: Context) -> dict[str, Value]:
    import os

    base = ctx.base_dir if ctx.base_dir is not None else os.getcwd()
    return {
        "path": Object({"module": ".", "root": ".", "cwd": os.path.abspath(base)}),
        "terraform": Object({"workspace": "default"}),
    }

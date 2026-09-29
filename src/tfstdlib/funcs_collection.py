"""Collection functions."""

from __future__ import annotations

from typing import Any

from .errors import ArgumentError, ConversionError, FuncFail
from .funcs_string import whole_int
from .graphemes import grapheme_count
from .numbers import Number
from .registry import Param, register
from .values import (
    elem_of,
    BOOL,
    DYNAMIC,
    NULL,
    NUMBER,
    STRING,
    UNKNOWN,
    ListT,
    Map,
    MapT,
    Null,
    Object,
    SetT,
    TfSet,
    Type,
    Unknown,
    Value,
    convert,
    type_of,
    unify,
    value_key,
    values_equal,
)

L_DYN = ListT(DYNAMIC)
S_DYN = SetT(DYNAMIC)


def _arg_err(param: str, msg: str) -> ArgumentError:
    return ArgumentError(f'Invalid value for "{param}" parameter: {msg}.')


def _seq(v: Value) -> list[Value]:
    return list(v)


# ---------------------------------------------------------------------------
# length, concat, contains, distinct, element, flatten, index
# ---------------------------------------------------------------------------


@register("length", Param("value", DYNAMIC))
def _length(v: Value) -> Value:
    if isinstance(v, str):
        return Number.from_int(grapheme_count(v))
    if isinstance(v, (list, tuple, TfSet, dict)):
        return Number.from_int(len(v))
    raise FuncFail("argument must be a string, a collection type, or a structural type")


@register("concat", varargs=Param("seqs", DYNAMIC))
def _concat(*seqs: Value) -> Value:
    if not seqs:
        raise FuncFail("at least one argument is required")
    for s in seqs:
        if not isinstance(s, (list, tuple)):
            raise _arg_err("seqs", f"all arguments must be lists or tuples; got {type_of(s).friendly()}")
    if any(isinstance(s, tuple) for s in seqs):
        out: list[Value] = []
        for s in seqs:
            out.extend(s)
        return tuple(out)
    ety = unify([elem_of(type_of(s)) for s in seqs])
    items: list[Value] = []
    for s in seqs:
        items.extend(s)
    if ety is None:
        return tuple(items)
    return [convert(x, ety) for x in items]


@register("contains", Param("list", DYNAMIC), Param("value", DYNAMIC, allow_null=True))
def _contains(lst: Value, value: Value) -> Value:
    if not isinstance(lst, (list, tuple, TfSet)):
        raise FuncFail("argument must be list, tuple, or set")
    if isinstance(value, Null):
        return UNKNOWN
    return any(values_equal(value, x) for x in lst)


@register("distinct", Param("list", L_DYN))
def _distinct(lst: list[Value]) -> Value:
    seen: set[Any] = set()
    out = []
    for x in lst:
        k = value_key(x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


@register("element", Param("list", DYNAMIC), Param("index", NUMBER))
def _element(lst: Value, index: Number) -> Value:
    if not isinstance(lst, (list, tuple)):
        raise FuncFail(f"cannot read elements from {type_of(lst).friendly()}")
    try:
        i = whole_int(index)
    except FuncFail as exc:
        raise FuncFail(f"invalid index: {exc.message}") from None
    if not lst:
        raise FuncFail("cannot use element function with an empty list")
    return lst[i % len(lst)]


@register("flatten", Param("list", DYNAMIC))
def _flatten(v: Value) -> Value:
    if not isinstance(v, (list, tuple, TfSet)):
        raise FuncFail("can only flatten lists, sets and tuples")
    out: list[Value] = []

    def walk(x: Value) -> None:
        if isinstance(x, (list, tuple, TfSet)):
            for y in x:
                walk(y)
        else:
            out.append(x)

    for e in v:
        walk(e)
    return tuple(out)


@register("index", Param("list", DYNAMIC), Param("value", DYNAMIC))
def _index(lst: Value, value: Value) -> Value:
    if not isinstance(lst, (list, tuple)):
        raise FuncFail("argument must be a list or tuple")
    if not lst:
        raise FuncFail("cannot search an empty list")
    for i, x in enumerate(lst):
        if values_equal(x, value):
            return Number.from_int(i)
    raise FuncFail("item not found")


# ---------------------------------------------------------------------------
# keys, values, lookup, merge
# ---------------------------------------------------------------------------


@register("keys", Param("inputMap", DYNAMIC))
def _keys(m: Value) -> Value:
    if not isinstance(m, dict):
        raise _arg_err("inputMap", "must have map or object type")
    ks = sorted(m)
    return ks if isinstance(m, Map) else tuple(ks)


@register("values", Param("mapping", DYNAMIC))
def _values(m: Value) -> Value:
    if not isinstance(m, dict):
        raise FuncFail("values() requires a map as the first argument")
    vs = [m[k] for k in sorted(m)]
    return vs if isinstance(m, Map) else tuple(vs)


def _lookup(m: Value, key: str, default: Value | None) -> Value:
    if not isinstance(m, dict):
        raise _arg_err("inputMap", "lookup() requires a map as the first argument")
    if key in m:
        return m[key]
    if default is None:
        if isinstance(m, Map):
            raise FuncFail(f'lookup failed to find key "{key}"')
        raise _arg_err("inputMap", f'the given object has no attribute "{key}"')
    if isinstance(m, Map):
        et = elem_of(type_of(m))
        try:
            return convert(default, et)
        except ConversionError:
            raise _arg_err("default", "the default value must have the same type as the map elements") from None
    return default


# lookup takes an optional third argument; register a variadic wrapper
from .registry import FUNCTIONS, Function  # noqa: E402


def _lookup_impl(m: Value, key: str, *rest: Value) -> Value:
    if len(rest) > 1:
        raise ArgumentError('Too many arguments: Function "lookup" expects only 3 argument(s).')
    return _lookup(m, key, rest[0] if rest else None)


FUNCTIONS["lookup"] = Function(
    "lookup",
    [Param("inputMap", DYNAMIC), Param("key", STRING)],
    _lookup_impl,
    varargs=Param("default", DYNAMIC, allow_null=True, allow_unknown=True),
)


@register("merge", varargs=Param("maps", DYNAMIC, allow_null=True))
def _merge(*maps: Value) -> Value:
    out: dict[str, Value] = {}
    kinds: list[Type] = []
    for m in maps:
        if isinstance(m, Null):
            continue
        if not isinstance(m, dict):
            raise FuncFail(f'arguments must be maps or objects, got "{_kind_name(m)}"')
        kinds.append(type_of(m))
        out.update(m)
    if kinds and all(isinstance(k, MapT) for k in kinds) and all(k == kinds[0] for k in kinds):
        return Map(out)
    return Object(out)


def _kind_name(v: Value) -> str:
    t = type_of(v)
    if isinstance(v, (str,)):
        return "string"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, Number):
        return "number"
    if isinstance(v, tuple):
        return "tuple"
    if isinstance(v, list):
        return "list"
    if isinstance(v, TfSet):
        return "set"
    return t.friendly()


# ---------------------------------------------------------------------------
# range, reverse, slice, sort
# ---------------------------------------------------------------------------


@register("range", varargs=Param("params", NUMBER))
def _range(*params: Number) -> Value:
    if not 1 <= len(params) <= 3:
        raise ArgumentError("Invalid value for \"params\" parameter: must have one, two, or three arguments.")
    zero = Number.from_int(0)
    one = Number.from_int(1)
    minus_one = Number.from_int(-1)
    if len(params) == 1:
        start, end = zero, params[0]
        step = minus_one if end.cmp(zero) < 0 else one
    elif len(params) == 2:
        start, end = params[0], params[1]
        step = minus_one if end.cmp(start) < 0 else one
    else:
        start, end, step = params
    pos = step.cmp(zero) > 0
    neg = step.cmp(zero) < 0
    if pos and end.cmp(start) < 0:
        raise _arg_err("params", "end must be greater than start when step is positive")
    if neg and end.cmp(start) > 0:
        raise _arg_err("params", "end must be less than start when step is negative")
    out: list[Value] = []
    cur = start
    while True:
        if pos and cur.cmp(end) >= 0:
            break
        if neg and cur.cmp(end) <= 0:
            break
        if not pos and not neg and cur.cmp(end) == 0:
            break
        if len(out) >= 1024:
            raise FuncFail(
                "more than 1024 values were generated; either decrease the difference between start and end or use a smaller step"
            )
        out.append(cur)
        cur = cur.add(step)
    return out


@register("reverse", Param("list", DYNAMIC))
def _reverse(v: Value) -> Value:
    if isinstance(v, TfSet):
        return list(reversed(list(v)))
    if isinstance(v, list):
        return list(reversed(v))
    if isinstance(v, tuple):
        return tuple(reversed(v))
    raise _arg_err("list", f"can only reverse list or tuple values, not {_kind_name(v)}")


@register("slice", Param("list", DYNAMIC), Param("start_index", NUMBER), Param("end_index", NUMBER))
def _slice(v: Value, start: Number, end: Number) -> Value:
    if isinstance(v, TfSet):
        raise _arg_err(
            "list",
            "cannot slice a set, because its elements do not have indices; explicitly convert to a list if the ordering of the result is not important",
        )
    if not isinstance(v, (list, tuple)):
        raise _arg_err("list", "must be a list or tuple value")
    try:
        s = whole_int(start)
    except FuncFail as exc:
        raise _arg_err("start_index", f"invalid start index: {exc.message.rstrip('.')}") from None
    try:
        e = whole_int(end)
    except FuncFail as exc:
        raise _arg_err("end_index", f"invalid end index: {exc.message.rstrip('.')}") from None
    if s < 0:
        raise _arg_err("start_index", "start index must not be less than zero")
    if e < 0:
        raise _arg_err("end_index", "end index must not be less than zero")
    if s > len(v):
        raise _arg_err("start_index", "start index must not be greater than the length of the list")
    if e > len(v):
        raise _arg_err("end_index", "end index must not be greater than the length of the list")
    if s > e:
        raise _arg_err("start_index", "start index must not be greater than end index")
    return v[s:e]


@register("sort", Param("list", ListT(STRING)))
def _sort(lst: list[Value]) -> Value:
    for i, x in enumerate(lst):
        if isinstance(x, Null):
            raise FuncFail(f"given list element {i} is null; a null string cannot be sorted")
    return sorted(lst)


# ---------------------------------------------------------------------------
# sets
# ---------------------------------------------------------------------------


def _set_args(sets: list[TfSet]) -> tuple[Type, list[list[Value]]]:
    ety = unify([elem_of(type_of(s)) for s in sets])
    if ety is None:
        raise FuncFail("given sets must all have compatible element types")
    return ety, [[convert(x, ety) for x in s] for s in sets]


@register("setunion", Param("first_set", S_DYN), varargs=Param("other_sets", S_DYN))
def _setunion(first: TfSet, *others: TfSet) -> Value:
    _, lists = _set_args([first, *others])
    return TfSet(x for lst in lists for x in lst)


@register("setintersection", Param("first_set", S_DYN), varargs=Param("other_sets", S_DYN))
def _setintersection(first: TfSet, *others: TfSet) -> Value:
    _, lists = _set_args([first, *others])
    keysets = [{value_key(x) for x in lst} for lst in lists[1:]]
    return TfSet(x for x in lists[0] if all(value_key(x) in ks for ks in keysets))


@register("setsubtract", Param("a", S_DYN), Param("b", S_DYN))
def _setsubtract(a: TfSet, b: TfSet) -> Value:
    _, (la, lb) = _set_args([a, b])
    kb = {value_key(x) for x in lb}
    return TfSet(x for x in la if value_key(x) not in kb)


@register("setproduct", varargs=Param("sets", DYNAMIC))
def _setproduct(*sets: Value) -> Value:
    if len(sets) < 2:
        raise FuncFail("at least two arguments are required")
    for s in sets:
        if not isinstance(s, (list, tuple, TfSet)):
            raise _arg_err("sets", "a set or a list is required")
    any_set = any(isinstance(s, TfSet) for s in sets)
    lists: list[list[Value]] = []
    for s in sets:
        items = list(s)
        ts = [type_of(x) for x in items]
        if isinstance(s, tuple) and ts:
            u = unify(ts)
            if u is None:
                raise FuncFail("all elements of each argument must have compatible types")
            items = [convert(x, u) for x in items]
        lists.append(items)
    combos: list[tuple[Value, ...]] = [()]
    for lst in lists:
        combos = [c + (x,) for c in combos for x in lst]
    if any_set:
        return TfSet(combos)
    return list(combos)


@register("zipmap", Param("keys", ListT(STRING)), Param("values", DYNAMIC))
def _zipmap(keys: list[Value], values: Value) -> Value:
    if not isinstance(values, (list, tuple)):
        raise FuncFail("values argument must be a list or tuple value")
    if len(keys) != len(values):
        raise FuncFail(f"number of keys ({len(keys)}) does not match number of values ({len(values)})")
    out: dict[str, Value] = {}
    for i, (k, v) in enumerate(zip(keys, values)):
        if isinstance(k, Null):
            raise FuncFail(f"keys list has null value at index {i}")
        out[k] = v
    return Map(out) if isinstance(values, list) else Object(out)


# ---------------------------------------------------------------------------
# coalesce & friends
# ---------------------------------------------------------------------------


@register("coalesce", varargs=Param("vals", DYNAMIC, allow_null=True, allow_unknown=True))
def _coalesce(*vals: Value) -> Value:
    ty = unify([type_of(v) for v in vals], unsafe=True)
    if ty is None:
        raise FuncFail("all arguments must have the same type")
    for v in vals:
        if isinstance(v, Null):
            continue
        if isinstance(v, str) and v == "":
            continue
        return convert(v, ty)
    raise FuncFail("no non-null, non-empty-string arguments")


@register("coalescelist", varargs=Param("vals", DYNAMIC, allow_null=True))
def _coalescelist(*vals: Value) -> Value:
    if not vals:
        raise FuncFail("at least one argument is required")
    for v in vals:
        if not isinstance(v, (list, tuple)):
            raise FuncFail("coalescelist arguments must be lists or tuples")
    for v in vals:
        if len(v) > 0:
            return v
    raise FuncFail("no non-null arguments")


@register("compact", Param("list", ListT(STRING)))
def _compact(lst: list[Value]) -> Value:
    return [x for x in lst if not isinstance(x, Null) and x != ""]


@register("one", Param("list", DYNAMIC))
def _one(v: Value) -> Value:
    if not isinstance(v, (list, tuple, TfSet)) or len(v) > 1:
        raise _arg_err("list", "must be a list, set, or tuple value with either zero or one elements")
    items = list(v)
    return items[0] if items else NULL


@register("sum", Param("list", DYNAMIC))
def _sum(v: Value) -> Value:
    if isinstance(v, dict):
        raise _arg_err("list", f"argument must be list, set, or tuple. Received {type_of(v).friendly()}")
    if not isinstance(v, (list, tuple, TfSet)):
        raise _arg_err("list", "cannot sum noniterable")
    items = list(v)
    if not items:
        raise _arg_err("list", "cannot sum an empty list")
    total: Number | None = None
    for x in items:
        if isinstance(x, Null):
            raise _arg_err("list", "argument must be list, set, or tuple of number values")
        try:
            n = convert(x, NUMBER)
        except ConversionError:
            raise _arg_err("list", "argument must be list, set, or tuple of number values") from None
        total = n if total is None else total.add(n)
    assert total is not None
    return total


@register("alltrue", Param("list", ListT(BOOL)))
def _alltrue(lst: list[Value]) -> Value:
    return all(x is True for x in lst)


@register("anytrue", Param("list", ListT(BOOL)))
def _anytrue(lst: list[Value]) -> Value:
    return any(x is True for x in lst)


@register("chunklist", Param("list", L_DYN), Param("size", NUMBER))
def _chunklist(lst: list[Value], size: Number) -> Value:
    try:
        n = whole_int(size)
    except FuncFail as exc:
        raise FuncFail(f"invalid size: {exc.message}") from None
    if n < 0:
        raise FuncFail("the size argument must be positive")
    if not lst:
        return []
    if n == 0:
        return [list(lst)]
    return [list(lst[i : i + n]) for i in range(0, len(lst), n)]


@register("transpose", Param("values", MapT(ListT(STRING))))
def _transpose(m: Map) -> Value:
    out: dict[str, list[Value]] = {}
    for k in sorted(m):
        lst = m[k]
        if isinstance(lst, Null):
            raise FuncFail("input must not contain null list")
        for s in lst:
            if isinstance(s, Null):
                raise FuncFail("input list must not contain null string")
            out.setdefault(s, []).append(k)
    return Map(out)


@register("matchkeys", Param("values", L_DYN), Param("keys", L_DYN), Param("searchset", L_DYN))
def _matchkeys(values: list[Value], keys: list[Value], search: list[Value]) -> Value:
    if len(keys) != len(values):
        raise FuncFail("length of keys and values should be equal")
    ety = unify([elem_of(type_of(keys)), elem_of(type_of(search))])
    if ety is None:
        raise FuncFail("keys and searchset must be of the same type")
    ks = [convert(x, ety) for x in keys]
    ss = {value_key(convert(x, ety)) for x in search}
    return [v for v, k in zip(values, ks) if value_key(k) in ss]


__all__ = ["Unknown"]

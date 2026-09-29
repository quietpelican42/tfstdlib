"""A cty-like value model: types, values, conversion and unification.

Values are plain Python objects:

=================  ==========================================================
Terraform          Python
=================  ==========================================================
string             ``str``
number             :class:`~tfstdlib.numbers.Number`
bool               ``bool``
list               ``list`` (every element has the same type)
tuple              ``tuple``
set                :class:`TfSet` (unique, in cty iteration order)
map                :class:`Map` (a ``dict`` subclass, one element type)
object             :class:`Object` (a ``dict`` subclass, one type per key)
null               :class:`Null` (remembers its type; :data:`NULL` is untyped)
unknown            :data:`UNKNOWN`
=================  ==========================================================
"""

from __future__ import annotations

import functools
from fractions import Fraction
from typing import Any, Iterable, Iterator, TypeAlias

from .errors import ConversionError
from .numbers import Number

Value: TypeAlias = Any


# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------


class Type:
    """Base class of all types."""

    def friendly(self) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.friendly()}>"


class PrimT(Type):
    def __init__(self, name: str) -> None:
        self.name = name

    def friendly(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PrimT) and other.name == self.name

    def __hash__(self) -> int:
        return hash(self.name)


class DynamicT(Type):
    def friendly(self) -> str:
        return "dynamic"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DynamicT)

    def __hash__(self) -> int:
        return 1


class ListT(Type):
    def __init__(self, elem: Type) -> None:
        self.elem = elem

    def friendly(self) -> str:
        return f"list of {self.elem.friendly()}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ListT) and other.elem == self.elem

    def __hash__(self) -> int:
        return hash(("list", self.elem))


class SetT(Type):
    def __init__(self, elem: Type) -> None:
        self.elem = elem

    def friendly(self) -> str:
        return f"set of {self.elem.friendly()}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SetT) and other.elem == self.elem

    def __hash__(self) -> int:
        return hash(("set", self.elem))


class MapT(Type):
    def __init__(self, elem: Type) -> None:
        self.elem = elem

    def friendly(self) -> str:
        return f"map of {self.elem.friendly()}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MapT) and other.elem == self.elem

    def __hash__(self) -> int:
        return hash(("map", self.elem))


class TupleT(Type):
    def __init__(self, elems: Iterable[Type]) -> None:
        self.elems = tuple(elems)

    def friendly(self) -> str:
        return "tuple"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TupleT) and other.elems == self.elems

    def __hash__(self) -> int:
        return hash(("tuple", self.elems))


class ObjectT(Type):
    def __init__(self, attrs: dict[str, Type]) -> None:
        self.attrs = dict(attrs)

    def friendly(self) -> str:
        return "object"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ObjectT) and other.attrs == self.attrs

    def __hash__(self) -> int:
        return hash(("object", tuple(sorted(self.attrs.items(), key=lambda kv: kv[0]))))


STRING = PrimT("string")
NUMBER = PrimT("number")
BOOL = PrimT("bool")
DYNAMIC = DynamicT()


# ---------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------


class Null:
    """A null value. ``type`` is the type it was converted to (dynamic if none)."""

    __slots__ = ("type",)

    def __init__(self, type_: Type = DYNAMIC) -> None:
        self.type = type_

    def __repr__(self) -> str:
        return "NULL" if isinstance(self.type, DynamicT) else f"Null({self.type.friendly()})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Null)

    def __hash__(self) -> int:
        return 7


class Unknown:
    """The unknown value (``(known after apply)``)."""

    _inst: "Unknown | None" = None

    def __new__(cls) -> "Unknown":
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:
        return "UNKNOWN"


NULL = Null()
UNKNOWN = Unknown()


class Map(dict[str, Any]):
    """A Terraform map: string keys, all values of one type. Keys iterate sorted."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(sorted(dict(*args, **kwargs).items()))


class Object(dict[str, Any]):
    """A Terraform object: string keys, each value has its own type. Keys iterate sorted."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(sorted(dict(*args, **kwargs).items()))


class TfSet:
    """A Terraform set. Iteration order follows cty: primitives sort naturally."""

    __slots__ = ("_items",)

    def __init__(self, items: Iterable[Value] = ()) -> None:
        seen: dict[Any, Value] = {}
        for it in items:
            k = value_key(it)
            if k not in seen:
                seen[k] = it
        self._items: tuple[Value, ...] = tuple(sorted(seen.values(), key=functools.cmp_to_key(_set_less_cmp)))

    def __iter__(self) -> Iterator[Value]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, item: object) -> bool:
        k = value_key(item)
        return any(value_key(x) == k for x in self._items)

    def __repr__(self) -> str:
        return f"TfSet({list(self._items)!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TfSet) and value_key(self) == value_key(other)

    def __hash__(self) -> int:
        return hash(value_key(self))


def deep_nfc(v: Value) -> Value:
    """Normalize every string in ``v`` (and every map key) to NFC, as cty does."""
    import unicodedata

    if isinstance(v, str):
        return v if v.isascii() else unicodedata.normalize("NFC", v)
    if isinstance(v, list):
        return [deep_nfc(x) for x in v]
    if isinstance(v, tuple):
        return tuple(deep_nfc(x) for x in v)
    if isinstance(v, TfSet):
        return TfSet(deep_nfc(x) for x in v)
    if isinstance(v, Map):
        return Map({deep_nfc(k): deep_nfc(x) for k, x in v.items()})
    if isinstance(v, dict):
        return Object({deep_nfc(k): deep_nfc(x) for k, x in v.items()})
    return v


def is_null(v: Value) -> bool:
    return isinstance(v, Null)


def is_unknown(v: Value) -> bool:
    return isinstance(v, Unknown)


def is_number(v: Value) -> bool:
    return isinstance(v, Number)


def is_string(v: Value) -> bool:
    return isinstance(v, str)


def is_bool(v: Value) -> bool:
    return isinstance(v, bool)


def is_collection(v: Value) -> bool:
    return isinstance(v, (list, tuple, TfSet, Map, Object))


def is_sequence(v: Value) -> bool:
    return isinstance(v, (list, tuple, TfSet))


def is_mapping(v: Value) -> bool:
    return isinstance(v, (Map, Object))


def num(x: int | str) -> Number:
    """Shorthand constructor: ``num(3)`` or ``num("0.5")``."""
    if isinstance(x, int):
        return Number.from_int(x)
    n = Number.parse(x)
    if n is None:
        raise ValueError(x)
    return n


def value_key(v: Value) -> Any:
    """A hashable key such that two values are equal iff their keys are equal."""
    if isinstance(v, bool):
        return ("b", v)
    if isinstance(v, str):
        return ("s", v)
    if isinstance(v, Number):
        return ("n", ("inf", v.negative) if v.is_inf else v.to_fraction())
    if isinstance(v, Null):
        return ("z",)
    if isinstance(v, Unknown):
        return ("?",)
    if isinstance(v, list):
        return ("l", tuple(value_key(x) for x in v))
    if isinstance(v, tuple):
        return ("t", tuple(value_key(x) for x in v))
    if isinstance(v, TfSet):
        return ("S", frozenset(value_key(x) for x in v))
    if isinstance(v, Map):
        return ("m", frozenset((k, value_key(x)) for k, x in v.items()))
    if isinstance(v, dict):
        return ("o", frozenset((k, value_key(x)) for k, x in v.items()))
    raise TypeError(f"not a Terraform value: {v!r}")


def _hash_bytes(v: Value) -> bytes:
    """cty's set-hash serialization, used only to order non-primitive elements."""
    if isinstance(v, Unknown):
        return b"?"
    if isinstance(v, Null):
        return b"null"
    if isinstance(v, bool):
        return b"true" if v else b"false"
    if isinstance(v, str):
        return b"\xc2\xab" + v.encode("utf-8") + b"\xc2\xbb"
    if isinstance(v, Number):
        return v.text().encode()
    if isinstance(v, Map):
        parts = [b"{"]
        for k in sorted(v):
            parts += [_hash_bytes(k), b":", _hash_bytes(v[k]), b";"]
        parts.append(b"}")
        return b"".join(parts)
    if isinstance(v, (list, TfSet)):
        parts = [b"["]
        for x in v:
            parts += [_hash_bytes(x), b";"]
        parts.append(b"]")
        return b"".join(parts)
    if isinstance(v, tuple):
        parts = [b"<"]
        for x in v:
            parts += [_hash_bytes(x), b";"]
        parts.append(b">")
        return b"".join(parts)
    if isinstance(v, dict):
        parts = [b"<"]
        for k in sorted(v):
            parts += [_hash_bytes(k), b":", _hash_bytes(v[k]), b";"]
        parts.append(b">")
        return b"".join(parts)
    raise TypeError(f"not a Terraform value: {v!r}")


def _set_less_cmp(a: Value, b: Value) -> int:
    an, bn = isinstance(a, Null), isinstance(b, Null)
    if an or bn:
        return 0 if an and bn else (1 if an else -1)
    if isinstance(a, str) and isinstance(b, str):
        return (a > b) - (a < b)
    if isinstance(a, Number) and isinstance(b, Number):
        return a.cmp(b)
    if isinstance(a, bool) and isinstance(b, bool):
        return (a > b) - (a < b)
    ha, hb = _hash_bytes(a), _hash_bytes(b)
    return (ha > hb) - (ha < hb)


# ---------------------------------------------------------------------------
# type inference, unification, conversion
# ---------------------------------------------------------------------------


def type_of(v: Value) -> Type:
    if isinstance(v, bool):
        return BOOL
    if isinstance(v, str):
        return STRING
    if isinstance(v, Number):
        return NUMBER
    if isinstance(v, Null):
        return v.type
    if isinstance(v, Unknown):
        return DYNAMIC
    if isinstance(v, list):
        return ListT(_elem_type(v))
    if isinstance(v, tuple):
        return TupleT(type_of(x) for x in v)
    if isinstance(v, TfSet):
        return SetT(_elem_type(list(v)))
    if isinstance(v, Map):
        return MapT(_elem_type(list(v.values())))
    if isinstance(v, dict):
        return ObjectT({k: type_of(x) for k, x in v.items()})
    raise TypeError(f"not a Terraform value: {v!r}")


def elem_of(t: Type) -> Type:
    """Element type of a list, set or map type (dynamic for anything else)."""
    if isinstance(t, (ListT, SetT, MapT)):
        return t.elem
    return DYNAMIC


def _elem_type(items: list[Value]) -> Type:
    if not items:
        return DYNAMIC
    ts = [type_of(x) for x in items]
    first = ts[0]
    if all(t == first for t in ts):
        return first
    u = unify(ts)
    return u if u is not None else DYNAMIC


def _is_prim(t: Type) -> bool:
    return isinstance(t, PrimT)


def convertible(src: Type, dst: Type, unsafe: bool) -> bool:
    """Whether a value of type ``src`` can be converted to ``dst``."""
    if src == dst or isinstance(src, DynamicT) or isinstance(dst, DynamicT):
        return True
    if isinstance(src, PrimT) and isinstance(dst, PrimT):
        if dst == STRING:
            return True
        return unsafe and src == STRING
    if isinstance(src, (ListT, SetT, MapT)) and type(dst) is type(src):
        return convertible(src.elem, dst.elem, unsafe)
    if isinstance(src, (ListT, SetT)) and isinstance(dst, (ListT, SetT)):
        return convertible(src.elem, dst.elem, unsafe)
    if isinstance(src, TupleT) and isinstance(dst, TupleT):
        return len(src.elems) == len(dst.elems) and all(convertible(a, b, unsafe) for a, b in zip(src.elems, dst.elems))
    if isinstance(src, ObjectT) and isinstance(dst, ObjectT):
        return set(src.attrs) == set(dst.attrs) and all(convertible(src.attrs[k], dst.attrs[k], unsafe) for k in src.attrs)
    return False


def unify(types: list[Type], unsafe: bool = False) -> Type | None:
    """The single type every type in ``types`` converts to, or ``None``."""
    if not types:
        return None
    first = types[0]
    if all(t == first for t in types):
        return first
    n = len(types)
    maps = [t for t in types if isinstance(t, MapT)]
    lists = [t for t in types if isinstance(t, ListT)]
    sets = [t for t in types if isinstance(t, SetT)]
    objs = [t for t in types if isinstance(t, ObjectT)]
    tups = [t for t in types if isinstance(t, TupleT)]
    if maps and len(maps) + len(objs) == n:
        elems: list[Type] = [m.elem for m in maps]
        for o in objs:
            elems += list(o.attrs.values())
        u = unify(elems, unsafe)
        return MapT(u) if u is not None else None
    if lists and len(lists) + len(tups) + len(sets) == n:
        elems = [t.elem for t in lists] + [t.elem for t in sets]
        for tp in tups:
            elems += list(tp.elems)
        u = unify(elems, unsafe)
        return ListT(u) if u is not None else None
    if sets and len(sets) + len(tups) == n:
        elems = [t.elem for t in sets]
        for tp in tups:
            elems += list(tp.elems)
        u = unify(elems, unsafe)
        return SetT(u) if u is not None else None
    if objs and len(objs) == n:
        keysets = {frozenset(o.attrs) for o in objs}
        if len(keysets) == 1:
            attrs: dict[str, Type] = {}
            for k in objs[0].attrs:
                u = unify([o.attrs[k] for o in objs], unsafe)
                if u is None:
                    return None
                attrs[k] = u
            return ObjectT(attrs)
        elems = [a for o in objs for a in o.attrs.values()]
        u = unify(elems, unsafe)
        return MapT(u) if u is not None else None
    if tups and len(tups) == n:
        lens = {len(t.elems) for t in tups}
        if len(lens) == 1:
            out: list[Type] = []
            for i in range(lens.pop()):
                u = unify([t.elems[i] for t in tups], unsafe)
                if u is None:
                    return None
                out.append(u)
            return TupleT(out)
        elems = [a for t in tups for a in t.elems]
        if not elems:
            return ListT(DYNAMIC)
        u = unify(elems, unsafe)
        return ListT(u) if u is not None else None
    if objs and tups:
        return None
    # candidate loop: prefer string, then number, then bool, then the given order
    order: list[Type] = [t for t in (STRING, NUMBER, BOOL) if t in types]
    order += [t for t in types if t not in order]
    for cand in order:
        if isinstance(cand, DynamicT):
            continue
        if all(convertible(t, cand, unsafe) for t in types):
            return cand
    if all(isinstance(t, DynamicT) for t in types):
        return DYNAMIC
    return None


def _cannot(v: Value, what: str) -> ConversionError:
    return ConversionError(f"cannot convert {type_of(v).friendly() if not isinstance(v, (list, tuple, TfSet, Map, Object)) else _kind(v)} to {what}")


def _kind(v: Value) -> str:
    t = type_of(v)
    return t.friendly()


def convert(v: Value, target: Type) -> Value:
    """Convert ``v`` to ``target`` the way Terraform converts function arguments."""
    if isinstance(target, DynamicT) or isinstance(v, Unknown):
        return v
    if isinstance(v, Null):
        return v if v.type == target else Null(target)
    if isinstance(target, PrimT):
        return _convert_prim(v, target)
    if isinstance(target, (ListT, SetT)):
        if not isinstance(v, (list, tuple, TfSet)):
            raise ConversionError(f"cannot convert {type_of(v).friendly()} to {'list' if isinstance(target, ListT) else 'set'} of any single type" if isinstance(target.elem, DynamicT) else f"{('list' if isinstance(target, ListT) else 'set')} required, but have {type_of(v).friendly()}")
        items = list(v)
        elem_t = target.elem
        if isinstance(elem_t, DynamicT):
            if items:
                ts = [type_of(x) for x in items]
                u = unify(ts)
                if u is None:
                    raise ConversionError(f"cannot convert {type_of(v).friendly() if isinstance(v, tuple) else type_of(v).friendly()} to {'list' if isinstance(target, ListT) else 'set'} of any single type")
                elem_t = u
        out = [convert(x, elem_t) for x in items]
        return out if isinstance(target, ListT) else TfSet(out)
    if isinstance(target, MapT):
        if not isinstance(v, (Map, Object)):
            raise ConversionError(f"cannot convert {type_of(v).friendly()} to map of any single type" if isinstance(target.elem, DynamicT) else f"map required, but have {type_of(v).friendly()}")
        elem_t = target.elem
        if isinstance(elem_t, DynamicT) and v:
            u = unify([type_of(x) for x in v.values()])
            if u is None:
                raise ConversionError(f"cannot convert {type_of(v).friendly()} to map of any single type")
            elem_t = u
        return Map({k: convert(x, elem_t) for k, x in v.items()})
    if isinstance(target, TupleT):
        if not isinstance(v, (list, tuple)) or len(v) != len(target.elems):
            raise ConversionError(f"tuple required, but have {type_of(v).friendly()}")
        return tuple(convert(x, t) for x, t in zip(v, target.elems))
    if isinstance(target, ObjectT):
        if not isinstance(v, (Map, Object)) or set(v) != set(target.attrs):
            raise ConversionError(f"object required, but have {type_of(v).friendly()}")
        return Object({k: convert(v[k], t) for k, t in target.attrs.items()})
    raise ConversionError(f"cannot convert to {target.friendly()}")


def _convert_prim(v: Value, target: PrimT) -> Value:
    if target == STRING:
        if isinstance(v, str):
            return v
        if isinstance(v, Number):
            return v.text()
        if isinstance(v, bool):
            return "true" if v else "false"
        raise ConversionError(f"string required, but have {type_of(v).friendly()}")
    if target == NUMBER:
        if isinstance(v, Number):
            return v
        if isinstance(v, str):
            n = Number.parse(v)
            if n is None:
                raise ConversionError("a number is required")
            return n
        raise ConversionError(f"number required, but have {type_of(v).friendly()}")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v in ("true", "1"):
            return True
        if v in ("false", "0"):
            return False
        raise ConversionError("a bool is required")
    raise ConversionError(f"bool required, but have {type_of(v).friendly()}")


def values_equal(a: Value, b: Value) -> bool:
    """The ``==`` operator: structural equality including the type."""
    if isinstance(a, Unknown) or isinstance(b, Unknown):
        return False
    if isinstance(a, Null) or isinstance(b, Null):
        return isinstance(a, Null) and isinstance(b, Null)
    if type(a) is not type(b) and not (isinstance(a, (Map, Object)) and type(a) is type(b)):
        return False
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, TfSet):
        return bool(value_key(a) == value_key(b))
    if isinstance(a, dict):
        return set(a) == set(b) and all(values_equal(a[k], b[k]) for k in a)
    return bool(value_key(a) == value_key(b))


def _to_fraction_num(x: Number) -> Fraction:
    return x.to_fraction()


# ---------------------------------------------------------------------------
# Python interop
# ---------------------------------------------------------------------------


def from_python(obj: Any) -> Value:
    """Convert native Python data to a Terraform value.

    ``dict`` becomes an object, ``list`` a list (a tuple when its elements do
    not share a type), ``tuple`` a tuple, ``set``/``frozenset`` a set.
    """
    from decimal import Decimal

    if obj is None:
        return NULL
    if isinstance(obj, (Null, Unknown, Number, TfSet, Map, Object)):
        return obj
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, str):
        return deep_nfc(obj)
    if isinstance(obj, int):
        return Number.from_int(obj, 512)
    if isinstance(obj, float):
        if obj != obj:
            raise ConversionError("NaN is not a Terraform number")
        n = Number.parse(repr(obj))
        if n is None:
            return Number.from_float(obj)
        return n
    if isinstance(obj, Decimal):
        n = Number.parse(str(obj))
        if n is None:
            raise ConversionError(f"cannot convert {obj!r} to a number")
        return n
    if isinstance(obj, Fraction):
        return Number.from_fraction(obj)
    if isinstance(obj, tuple):
        return tuple(from_python(x) for x in obj)
    if isinstance(obj, list):
        items = [from_python(x) for x in obj]
        if not items:
            return []
        u = unify([type_of(x) for x in items])
        if u is None:
            return tuple(items)
        return [convert(x, u) for x in items]
    if isinstance(obj, (set, frozenset)):
        items = [from_python(x) for x in obj]
        if items:
            u = unify([type_of(x) for x in items])
            if u is None:
                raise ConversionError("set elements must share a type")
            items = [convert(x, u) for x in items]
        return TfSet(items)
    if isinstance(obj, dict):
        return Object({str(k): from_python(x) for k, x in obj.items()})
    raise ConversionError(f"cannot convert {type(obj).__name__} to a Terraform value")


def to_python(v: Value) -> Any:
    """Convert a Terraform value to native Python data.

    Numbers become ``int`` when whole, else ``decimal.Decimal``; sets become
    lists in cty order; maps and objects become ``dict``; null becomes ``None``.
    """
    from decimal import Decimal

    if isinstance(v, Null):
        return None
    if isinstance(v, Unknown):
        return v
    if isinstance(v, (bool, str)):
        return v
    if isinstance(v, Number):
        if v.is_inf:
            return float("-inf") if v.negative else float("inf")
        if v.is_int():
            return v.to_int()
        return Decimal(v.text())
    if isinstance(v, (list, tuple, TfSet)):
        return [to_python(x) for x in v]
    if isinstance(v, dict):
        return {k: to_python(x) for k, x in v.items()}
    raise TypeError(f"not a Terraform value: {v!r}")

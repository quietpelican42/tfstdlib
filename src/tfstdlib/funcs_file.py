"""Filesystem, path and template functions."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from typing import Any

from .errors import ArgumentError, EvalError, FuncFail, ParseError, TerraformError
from .hcl import Context, render_template
from .registry import Param, register
from .values import DYNAMIC, STRING, Map, Object, TfSet, Value, convert, type_of

S = STRING

_NO_FILE_HINT = (
    'no file exists at "{p}"; this function works only with files that are distributed as part of the configuration '
    "source code, so if this file will be created by a resource in this configuration you must instead obtain this "
    "result from an attribute of that resource"
)


def _base(ctx: Any) -> str:
    base = getattr(ctx, "base_dir", None)
    return base if base else os.getcwd()


def _resolve(ctx: Any, path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(_base(ctx), path)


def _read_bytes(ctx: Any, path: str) -> bytes:
    full = _resolve(ctx, path)
    if os.path.isdir(full):
        raise ArgumentError(f'Invalid value for "path" parameter: failed to read file: read {path}: is a directory.')
    try:
        with open(full, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        raise ArgumentError(f'Invalid value for "path" parameter: {_NO_FILE_HINT.format(p=path)}.') from None
    except OSError as exc:
        raise ArgumentError(f'Invalid value for "path" parameter: failed to read file: {exc.strerror}.') from None


def _read_text(ctx: Any, path: str) -> str:
    data = _read_bytes(ctx, path)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise FuncFail(
            f'contents of "{path}" are not valid UTF-8; use the filebase64 function to obtain the Base64 encoded contents or the other file functions (e.g. filemd5, filesha256) to obtain file hashes'
        ) from None


@register("file", Param("path", S), needs_context=True)
def _file(ctx: Any, path: str) -> Value:
    return _read_text(ctx, path)


@register("fileexists", Param("path", S), needs_context=True)
def _fileexists(ctx: Any, path: str) -> Value:
    full = _resolve(ctx, path) if path else _base(ctx)
    if os.path.isdir(full):
        shown = path if path else "."
        raise FuncFail(f'"{shown}" is a directory, not a file')
    return os.path.exists(full)


@register("filebase64", Param("path", S), needs_context=True)
def _filebase64(ctx: Any, path: str) -> Value:
    return base64.b64encode(_read_bytes(ctx, path)).decode("ascii")


def _file_hash(fname: str, algo: str, b64: bool) -> None:
    @register(fname, Param("path", S), needs_context=True)
    def _impl(ctx: Any, path: str) -> Value:
        full = _resolve(ctx, path)
        try:
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise FuncFail(f"open {path}: {(exc.strerror or 'error').lower()}") from None
        h = hashlib.new(algo, data)
        return base64.b64encode(h.digest()).decode("ascii") if b64 else h.hexdigest()


_file_hash("filemd5", "md5", False)
_file_hash("filesha1", "sha1", False)
_file_hash("filesha256", "sha256", False)
_file_hash("filesha512", "sha512", False)
_file_hash("filebase64sha256", "sha256", True)
_file_hash("filebase64sha512", "sha512", True)


# --- glob (doublestar-style) -----------------------------------------------------


def _glob_segment(seg: str) -> str:
    out: list[str] = []
    i = 0
    n = len(seg)
    depth = 0
    while i < n:
        c = seg[i]
        if c == "\\":
            if i + 1 >= n:
                raise ValueError("syntax error in pattern")
            out.append(re.escape(seg[i + 1]))
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            neg = False
            if j < n and seg[j] in "^!":
                neg = True
                j += 1
            items: list[str] = []
            first = True
            while True:
                if j >= n:
                    raise ValueError("syntax error in pattern")
                if seg[j] == "]" and not first:
                    break
                first = False
                if seg[j] == "\\" and j + 1 < n:
                    j += 1
                lo = seg[j]
                j += 1
                if j + 1 < n and seg[j] == "-" and seg[j + 1] != "]":
                    hi = seg[j + 1]
                    j += 2
                    if hi == "\\" and j < n:
                        hi = seg[j]
                        j += 1
                    items.append(f"{re.escape(lo)}-{re.escape(hi)}")
                else:
                    items.append(re.escape(lo))
            out.append("[" + ("^" if neg else "") + "".join(items) + "]")
            i = j + 1
        elif c == "{":
            depth += 1
            out.append("(?:")
            i += 1
        elif c == "}" and depth > 0:
            depth -= 1
            out.append(")")
            i += 1
        elif c == "," and depth > 0:
            out.append("|")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    if depth:
        raise ValueError("syntax error in pattern")
    return "".join(out)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    segs = [s for s in pattern.split("/") if s != ""]
    parts: list[str] = []
    for idx, seg in enumerate(segs):
        last = idx == len(segs) - 1
        if seg == "**":
            parts.append(".*" if last else "(?:.*/)?")
        else:
            parts.append(_glob_segment(seg) + ("" if last else "/"))
    return re.compile("".join(parts))


@register("fileset", Param("path", S), Param("pattern", S), needs_context=True)
def _fileset(ctx: Any, path: str, pattern: str) -> Value:
    root = _resolve(ctx, path) if path else _base(ctx)
    try:
        rx = glob_to_regex(pattern)
    except ValueError:
        raise FuncFail(f'failed to glob pattern "{os.path.join(path, pattern)}": syntax error in pattern') from None
    if not pattern:
        return TfSet([])
    found: list[str] = []
    # pattern segments may climb out of the directory ("../*")
    n_up = 0
    segs = [s for s in pattern.split("/") if s]
    while segs and segs[0] == "..":
        n_up += 1
        segs.pop(0)
    if n_up:
        base_root = os.path.normpath(os.path.join(root, *[".."] * n_up))
        rx = glob_to_regex("/".join(segs))
        prefix = "../" * n_up
        for rel in _walk(base_root):
            if rx.fullmatch(rel):
                found.append(prefix + rel)
        return TfSet(found)
    for rel in _walk(root):
        if rx.fullmatch(rel):
            found.append(rel)
    return TfSet(found)


def _walk(root: str) -> list[str]:
    out: list[str] = []
    if not os.path.isdir(root):
        return out
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            out.append(rel.replace(os.sep, "/"))
    return out


# --- path helpers (Go's path/filepath on Unix) ------------------------------------


def go_clean(path: str) -> str:
    if path == "":
        return "."
    rooted = path.startswith("/")
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            elif not rooted:
                parts.append("..")
            continue
        parts.append(seg)
    out = "/".join(parts)
    if rooted:
        return "/" + out
    return out or "."


@register("dirname", Param("path", S))
def _dirname(path: str) -> Value:
    i = path.rfind("/")
    d = path[: i + 1]
    return go_clean(d) if d != "" else "."


@register("basename", Param("path", S))
def _basename(path: str) -> Value:
    if path == "":
        return "."
    p = path.rstrip("/")
    if p == "":
        return "/"
    return p[p.rfind("/") + 1 :]


@register("abspath", Param("path", S), needs_context=True)
def _abspath(ctx: Any, path: str) -> Value:
    if path.startswith("/"):
        return go_clean(path)
    return go_clean(os.path.join(_base(ctx), path))


@register("pathexpand", Param("path", S))
def _pathexpand(path: str) -> Value:
    if not path or path[0] != "~":
        return path
    if len(path) > 1 and path[1] != "/":
        raise FuncFail("cannot expand user-specific home dir")
    return os.path.expanduser("~") + path[1:]


# --- templates -----------------------------------------------------------------------


def _vars_from(value: Value) -> dict[str, Value]:
    if not isinstance(value, (Map, Object)):
        raise ArgumentError('Invalid value for "vars" parameter: invalid vars value: must be a map.')
    return dict(value)


@register("templatefile", Param("path", S), Param("vars", DYNAMIC), needs_context=True)
def _templatefile(ctx: Any, path: str, vars_: Value) -> Value:
    variables = _vars_from(vars_)
    text = _read_text(ctx, path)
    inner = Context(variables={}, base_dir=getattr(ctx, "base_dir", None), functions=dict(getattr(ctx, "functions", {})), allow_template_functions=False)
    try:
        return render_template(text, inner, variables)
    except TerraformError as exc:
        if isinstance(exc, ParseError | EvalError):
            raise FuncFail(f"{path}: {exc.message}") from None
        raise


@register("templatestring", Param("template", S), Param("vars", DYNAMIC), needs_context=True)
def _templatestring(ctx: Any, template: str, vars_: Value) -> Value:
    variables = _vars_from(vars_)
    inner = Context(variables={}, base_dir=getattr(ctx, "base_dir", None), functions=dict(getattr(ctx, "functions", {})), allow_template_functions=False)
    try:
        return render_template(template, inner, variables)
    except TerraformError as exc:
        raise FuncFail(exc.message) from None


@register("ephemeralasnull", Param("value", DYNAMIC, allow_null=True, allow_unknown=True))
def _ephemeralasnull(v: Value) -> Value:
    return v


__all__ = ["type_of", "convert"]


@register("sensitive", Param("value", DYNAMIC, allow_null=True, allow_unknown=True))
def _sensitive(v: Value) -> Value:
    return v  # marks are not tracked: the value passes through unchanged


@register("nonsensitive", Param("value", DYNAMIC, allow_null=True, allow_unknown=True))
def _nonsensitive(v: Value) -> Value:
    return v

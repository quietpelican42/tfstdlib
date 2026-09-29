"""CSV and text-encoding functions."""

from __future__ import annotations

import base64

from .errors import ArgumentError, FuncFail
from .funcs_encoding import _b64_decode
from .registry import Param, register
from .values import STRING, Object, Value

S = STRING

# ---------------------------------------------------------------------------
# csvdecode (Go encoding/csv semantics)
# ---------------------------------------------------------------------------


class _CsvError(Exception):
    pass


def _csv_records(text: str) -> list[tuple[int, list[str]]]:
    """Parse ``text`` like Go's csv.Reader with default settings."""
    # split into lines keeping terminators; normalize \r\n to \n
    lines: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find("\n", i)
        if j < 0:
            lines.append(text[i:])
            break
        lines.append(text[i : j + 1])
        i = j + 1
    lines = [ln[:-2] + "\n" if ln.endswith("\r\n") else ln for ln in lines]
    records: list[tuple[int, list[str]]] = []
    idx = 0
    num_field = -1
    while idx < len(lines):
        line = lines[idx]
        idx += 1
        if line in ("\n", ""):
            continue  # skip empty lines
        rec_line = idx
        fields: list[str] = []
        while True:
            if not line or line[0] != '"':
                k = line.find(",")
                field = line if k < 0 else line[:k]
                if k < 0 and field.endswith("\n"):
                    field = field[:-1]
                if '"' in field:
                    raise _CsvError(f"CSV parse error on line {idx}: bare \" in non-quoted-field")
                fields.append(field)
                if k >= 0:
                    line = line[k + 1 :]
                    continue
                break
            buf: list[str] = []
            line = line[1:]
            while True:
                k = line.find('"')
                if k >= 0:
                    buf.append(line[:k])
                    line = line[k + 1 :]
                    if line.startswith('"'):
                        buf.append('"')
                        line = line[1:]
                    elif line.startswith(","):
                        line = line[1:]
                        fields.append("".join(buf))
                        break
                    elif line in ("\n", ""):
                        fields.append("".join(buf))
                        line = ""
                        break
                    else:
                        raise _CsvError(f"CSV parse error on line {idx}: extraneous or missing \" in quoted-field")
                elif line:
                    buf.append(line)
                    if idx >= len(lines):
                        raise _CsvError(f"CSV parse error on line {idx}: extraneous or missing \" in quoted-field")
                    line = lines[idx]
                    idx += 1
                else:
                    raise _CsvError(f"CSV parse error on line {idx}: extraneous or missing \" in quoted-field")
            if line == "":
                break
        if num_field < 0:
            num_field = len(fields)
        elif len(fields) != num_field:
            raise _CsvError(f"CSV parse error on line {rec_line}: wrong number of fields")
        records.append((rec_line, fields))
    return records


@register("csvdecode", Param("str", S))
def _csvdecode(s: str) -> Value:
    try:
        recs = _csv_records(s)
    except _CsvError as exc:
        raise FuncFail(str(exc)) from None
    if not recs:
        raise FuncFail("missing header line")
    header = recs[0][1]
    seen: set[str] = set()
    for h in header:
        if h in seen:
            raise FuncFail(f'duplicate column name "{h}"')
        seen.add(h)
    return [Object(dict(zip(header, row))) for _, row in recs[1:]]


# ---------------------------------------------------------------------------
# textencodebase64 / textdecodebase64
# ---------------------------------------------------------------------------

# canonical IANA name -> (python codec, aliases)
_ENCODINGS: dict[str, tuple[str, tuple[str, ...]]] = {
    "UTF-8": ("utf-8", ()),
    "UTF-16": ("utf-16", ()),
    "UTF-16LE": ("utf-16-le", ()),
    "UTF-16BE": ("utf-16-be", ()),
    "US-ASCII": ("ascii", ("ANSI_X3.4-1968", "iso-ir-6", "ANSI_X3.4-1986", "ISO_646.irv:1991", "ISO646-US", "us", "IBM367", "cp367", "csASCII")),
    "ISO_8859-1:1987": ("latin-1", ("ISO-8859-1", "iso-ir-100", "ISO_8859-1", "latin1", "l1", "IBM819", "CP819", "csISOLatin1")),
    "ISO_8859-2:1987": ("iso8859-2", ("ISO-8859-2", "iso-ir-101", "ISO_8859-2", "latin2", "l2", "csISOLatin2")),
    "ISO_8859-3:1988": ("iso8859-3", ("ISO-8859-3", "iso-ir-109", "ISO_8859-3", "latin3", "l3", "csISOLatin3")),
    "ISO_8859-4:1988": ("iso8859-4", ("ISO-8859-4", "iso-ir-110", "ISO_8859-4", "latin4", "l4", "csISOLatin4")),
    "ISO_8859-5:1988": ("iso8859-5", ("ISO-8859-5", "iso-ir-144", "ISO_8859-5", "cyrillic", "csISOLatinCyrillic")),
    "ISO_8859-6:1987": ("iso8859-6", ("ISO-8859-6", "iso-ir-127", "ISO_8859-6", "ECMA-114", "ASMO-708", "arabic", "csISOLatinArabic")),
    "ISO_8859-7:1987": ("iso8859-7", ("ISO-8859-7", "iso-ir-126", "ISO_8859-7", "ELOT_928", "ECMA-118", "greek", "greek8", "csISOLatinGreek")),
    "ISO_8859-8:1988": ("iso8859-8", ("ISO-8859-8", "iso-ir-138", "ISO_8859-8", "hebrew", "csISOLatinHebrew")),
    "ISO_8859-9:1989": ("iso8859-9", ("ISO-8859-9", "iso-ir-148", "ISO_8859-9", "latin5", "l5", "csISOLatin5")),
    "ISO-8859-10": ("iso8859-10", ("iso-ir-157", "l6", "ISO_8859-10:1992", "csISOLatin6", "latin6")),
    "ISO-8859-13": ("iso8859-13", ()),
    "ISO-8859-14": ("iso8859-14", ("iso-ir-199", "ISO_8859-14:1998", "ISO_8859-14", "latin8", "iso-celtic", "l8")),
    "ISO-8859-15": ("iso8859-15", ("ISO_8859-15", "Latin-9")),
    "ISO-8859-16": ("iso8859-16", ("iso-ir-226", "ISO_8859-16:2001", "ISO_8859-16", "latin10", "l10")),
    "windows-1250": ("cp1250", ("cswindows1250",)),
    "windows-1251": ("cp1251", ("cswindows1251",)),
    "windows-1252": ("cp1252", ("cswindows1252",)),
    "windows-1253": ("cp1253", ("cswindows1253",)),
    "windows-1254": ("cp1254", ("cswindows1254",)),
    "windows-1255": ("cp1255", ("cswindows1255",)),
    "windows-1256": ("cp1256", ("cswindows1256",)),
    "windows-1257": ("cp1257", ("cswindows1257",)),
    "windows-1258": ("cp1258", ("cswindows1258",)),
    "KOI8-R": ("koi8-r", ("csKOI8R",)),
    "KOI8-U": ("koi8-u", ()),
    "Shift_JIS": ("shift_jis", ("MS_Kanji", "csShiftJIS")),
    "EUC-JP": ("euc-jp", ("Extended_UNIX_Code_Packed_Format_for_Japanese", "csEUCPkdFmtJapanese")),
    "ISO-2022-JP": ("iso2022-jp", ("csISO2022JP",)),
    "EUC-KR": ("euc-kr", ("csEUCKR",)),
    "GBK": ("gbk", ("CP936", "MS936", "windows-936")),
    "GB18030": ("gb18030", ()),
    "Big5": ("big5", ("csBig5",)),
    "macintosh": ("mac-roman", ("mac", "csMacintosh")),
    "IBM437": ("cp437", ("cp437", "437", "csPC8CodePage437")),
    "IBM850": ("cp850", ("cp850", "850", "csPC850Multilingual")),
    "IBM866": ("cp866", ("cp866", "866", "csIBM866")),
}

_LOOKUP: dict[str, str] = {}
for _canon, (_codec, _aliases) in _ENCODINGS.items():
    for _n in (_canon, *_aliases):
        _LOOKUP[_n.lower()] = _canon


def _encoding(name: str) -> tuple[str, str]:
    canon = _LOOKUP.get(name.lower())
    if canon is None:
        raise ArgumentError(f'Invalid value for "encoding" parameter: "{name}" is not a supported IANA encoding name or alias in this Terraform version.')
    return canon, _ENCODINGS[canon][0]


@register("textencodebase64", Param("string", S), Param("encoding", S))
def _textencode(s: str, encoding: str) -> Value:
    canon, codec = _encoding(encoding)
    try:
        if canon == "UTF-16":
            raw = b"\xfe\xff" + s.encode("utf-16-be")
        else:
            raw = s.encode(codec)
    except UnicodeEncodeError:
        raise ArgumentError(f'Invalid value for "string" parameter: the given string contains characters that cannot be represented in {canon}.') from None
    return base64.b64encode(raw).decode("ascii")


@register("textdecodebase64", Param("source", S), Param("encoding", S))
def _textdecode(source: str, encoding: str) -> Value:
    canon, codec = _encoding(encoding)
    raw = _b64_decode(source)
    if raw is None:
        bad = 0
        for i, ch in enumerate(source):
            if ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n":
                bad = i
                break
        raise ArgumentError(f'Invalid value for "source" parameter: the given value has an invalid base64 symbol at offset {bad}.')
    try:
        if canon == "UTF-16":
            if raw[:2] == b"\xff\xfe":
                return raw[2:].decode("utf-16-le")
            if raw[:2] == b"\xfe\xff":
                return raw[2:].decode("utf-16-be")
            return raw.decode("utf-16-be")
        return raw.decode(codec)
    except UnicodeDecodeError:
        raise ArgumentError(f'Invalid value for "source" parameter: the given string contains symbols that are not defined for {canon.split(":")[0] if canon.startswith("ISO_") else canon}.') from None


__all__ = ["FuncFail"]

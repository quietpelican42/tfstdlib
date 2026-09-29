from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

import tfstdlib
from tfstdlib import TerraformError, call, evaluate
from tfstdlib.numbers import Number
from tfstdlib.re2 import RegexError, compile_regex
from tfstdlib.values import TfSet, from_python, to_python

DATA = Path(__file__).resolve().parent / "data"


def test_call_native_values() -> None:
    assert call("cidrsubnet", "10.0.0.0/16", 8, 3) == "10.0.3.0/24"
    assert call("split", ",", "a,b,,c") == ["a", "b", "", "c"]
    assert call("trimprefix", "aaab", "a") == "aab"
    assert call("substr", "hello", -3, -1) == "llo"
    assert call("indent", 2, "a\nb") == "a\n  b"
    assert call("jsonencode", {"b": 1, "a": [True, None]}) == '{"a":[true,null],"b":1}'
    assert call("merge", {"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_numbers_are_exact() -> None:
    assert evaluate("0.1 + 0.2") == Decimal("0.3")
    assert evaluate("-7 % 3") == -1
    assert call("sum", [Decimal("0.1"), Decimal("0.2")]) == Decimal("0.3")
    assert evaluate("1/3") == Decimal("0." + "3" * 154 + "5")
    assert Number.parse("1e400") is not None


def test_regex_semantics_differ_from_python_re() -> None:
    assert call("regexall", "x*", "abxd") == ["", "", "x", ""]  # Python re would also match after the "x"
    with pytest.raises(TerraformError):
        call("regex", "^b", "abc")  # unanchored search, but ^ still anchors: no match is an error
    assert call("regex", "b", "abc") == "b"
    assert evaluate('regexall("\\\\d", "٣")') == []  # \d is ASCII in RE2, Unicode in re
    with pytest.raises(TerraformError):
        call("regex", "(?=a)", "a")  # look-ahead is unsupported in RE2
    assert compile_regex("(a*)*").search("abc") == [0, 1, 0, 1]


def test_regex_errors_carry_go_messages() -> None:
    with pytest.raises(RegexError) as info:
        compile_regex("a**")
    assert info.value.code == "invalid nested repetition operator"


def test_sets_follow_cty_order() -> None:
    assert to_python(from_python({3, 1, 2})) == [1, 2, 3]
    assert isinstance(from_python({"b", "a"}), TfSet)
    assert call("toset", ["b", "a", "b"]) == ["a", "b"]
    assert call("setunion", [1], ["a"]) == ["1", "a"]


def test_errors_match_terraform_outcome() -> None:
    for expr in ['tonumber("a")', "[1][5]", 'regex("a", "b")', "1/0 == 1/0 ? cidrhost(1, 1) : 1"]:
        with pytest.raises(TerraformError):
            evaluate(expr)
    assert tfstdlib.can('tonumber("1")') is True
    assert tfstdlib.can('tonumber("a")') is False
    assert evaluate('try(tonumber("a"), "fallback")') == "fallback"


def test_templates() -> None:
    assert evaluate('"%{ for x in [1,2,3] }${x},%{ endfor }"') == "1,2,3,"
    assert evaluate('"a  %{~ if true ~}  b  %{~ endif ~}  c"') == "abc"
    out = call("templatefile", "templates/list.tftpl", {"items": ["a", "b"]}, base_dir=str(DATA))
    assert out == "- a\n- b\n"


def test_yaml_roundtrip_and_yaml_11_scalars() -> None:
    assert call("yamlencode", {"a": (1, "x")}) == '"a":\n- 1\n- "x"\n'
    assert call("yamldecode", "a: yes\nb: 0x10\nc: 2001-01-01") == {"a": True, "b": 16, "c": "2001-01-01T00:00:00Z"}
    assert call("yamldecode", call("yamlencode", {"k": "line1\nline2\n"})) == {"k": "line1\nline2\n"}
    with pytest.raises(TerraformError):
        call("yamldecode", "a: 1\n---\nb: 2")


def test_grapheme_aware_strings() -> None:
    assert call("length", "🇺🇸🇫🇷") == 2
    assert call("strrev", "áb") == "bá"
    assert call("substr", "👨‍👩‍👧x", 1, 1) == "x"


def test_format_verbs() -> None:
    assert call("format", "%05.1f|%-5d|%x|%q", 3.14159, 42, 255, "a\tb") == '003.1|42   |ff|"a\\tb"'
    assert call("format", "%v", 10_000_000_000) == "1e+10"
    with pytest.raises(TerraformError):
        call("format", "%d", 1.5)


def test_time_functions_beyond_datetime_range() -> None:
    assert call("timeadd", "9999-12-31T23:59:59Z", "1s") == "10000-01-01T00:00:00Z"
    assert call("formatdate", "YYYY-MM-DD hh:mm ZZZ", "2024-05-17T13:04:05Z") == "2024-05-17 13:04 UTC"


def test_function_registry_lists_the_documented_functions() -> None:
    names = set(tfstdlib.function_names())
    for n in "format formatlist join split replace regex regexall substr indent chomp strrev cidrsubnets range setproduct jsonencode yamldecode base64encode sha256 uuidv5 formatdate timeadd templatefile".split():
        assert n in names
    assert len(names) >= 100

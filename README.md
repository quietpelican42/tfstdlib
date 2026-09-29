# tfstdlib

Terraform's built-in functions in pure Python, checked against `terraform console`.

```python
import tfstdlib

tfstdlib.call("cidrsubnet", "10.0.0.0/16", 8, 3)      # '10.0.3.0/24'
tfstdlib.call("split", ",", "a,b,,c")                  # ['a', 'b', '', 'c']
tfstdlib.call("trimprefix", "aaab", "a")               # 'aab'
tfstdlib.evaluate('{for k, v in {a = 1} : upper(k) => v * 10}')   # {'A': 10}
```

## Why

Python tools that read Terraform (scanners, linters, cost estimators) need the
value of expressions such as `cidrsubnet(var.cidr, 8, 3)` or `split(",", s)`.
They usually carry a hand-written subset. Subtle differences accumulate: `split`
keeps empty items, `trimprefix` removes one prefix, `substr` accepts negative
offsets, `regex` is an unanchored RE2 search, numbers are arbitrary precision
(`0.1 + 0.2` is `0.3`), and `indent`, `jsonencode`, `cidr*`, `format` verbs,
`formatdate` and `yamlencode` all have exact output rules.

The gold corpus in `tests/data/gold.jsonl` holds 5,108 expressions evaluated by
Terraform 1.16.2 (`terraform console`, stdin from a file): 3,443 values and
1,665 errors. Each record keeps the console rendering (so list/tuple/set/map/object
types and typed nulls are compared, not only the JSON), the `jsonencode` text and
the error text. `tfstdlib` reproduces all 5,108 (values, types and error or no
error). The only checked incumbents that evaluate functions are checkov and
pyhcl2. No PyPI package matching `terraform-func*`, `tf-func*`, `hcl*-func*`
or `pyterraform*` evaluates functions (`pyterraform` and `pyterraformer` wrap the
CLI or manipulate files; `hcl2-eval` has no function library).

Measured: `python bench/prepare.py`, then `bench/run_checkov.py` and
`bench/run_pyhcl2.py` in their own virtualenvs, then `python bench/score.py`.
An answer counts as correct when its value equals Terraform's, or when Terraform
errors and the tool also raises.

```
                          research corpus (221)   gold corpus (5,108)
checkov 3.3.20 safe_eval        91 (41.2%)          1,200 (23.5%)
pyhcl2 2.0.1                    37 (16.7%)          1,793 (35.1%)
tfstdlib 0.1.0                 221 (100%)           5,108 (100%)
```

The pyhcl2 share on the large corpus is mostly expected-error cases, because it
ships no functions and raises on every call. Known wrong values from checkov on
the research corpus: `split` drops empty items, `regex` is anchored, `trimprefix`
loops, negative `substr` offsets return an empty string, `indent` is a no-op,
`jsonencode` is the identity.

## Installation

```sh
pip install tfstdlib
```

Python 3.11 or newer. No runtime dependencies (see Limitations for YAML).

## Usage

### Call a function

`call(name, *args)` takes and returns native Python data. `dict` is an object,
`list` a list, `tuple` a tuple, `set` a set, `None` null. Whole numbers come back as
`int`, other numbers as `decimal.Decimal`, sets as sorted lists.

```python
tfstdlib.call("jsonencode", {"b": 1, "a": [True, None]})   # '{"a":[true,null],"b":1}'
tfstdlib.call("format", "%05.1f|%-5d|%x", 3.14159, 42, 255) # '003.1|42   |ff'
tfstdlib.call("formatdate", "YYYY-MM-DD hh:mm ZZZ", "2024-05-17T13:04:05Z")
```

Errors raise `tfstdlib.TerraformError` subclasses with a message modeled on
Terraform's. Where Terraform reports an error, this library raises.

### Evaluate an expression

```python
tfstdlib.evaluate('[for x in range(3) : x * 2]')             # [0, 2, 4]
tfstdlib.evaluate('var.n > 2 ? "big" : "small"', {"var": {"n": 3}})
tfstdlib.can('tonumber("a")')                                 # False
tfstdlib.evaluate('try(tonumber("a"), 0)')                    # 0
```

### Typed values

`call_value` and `evaluate_value` work on the cty-like model in `tfstdlib.values`
and keep the distinction between list, tuple, set, map and object, typed nulls and
exact numbers. `format_value(v)` renders a value the way `terraform console` does.

### Files and templates

```python
tfstdlib.call("templatefile", "tpl/nginx.tftpl", {"port": 80}, base_dir=".")
tfstdlib.call("fileset", "modules", "**/*.tf", base_dir=".")
```

## Reference

Functions (113 registered, plus `can` and `try` in the evaluator):

| Group | Functions |
| --- | --- |
| Strings | `chomp` `endswith` `format` `formatlist` `indent` `join` `lower` `regex` `regexall` `replace` `split` `startswith` `strcontains` `strrev` `substr` `title` `trim` `trimprefix` `trimspace` `trimsuffix` `upper` |
| Collections | `alltrue` `anytrue` `chunklist` `coalesce` `coalescelist` `compact` `concat` `contains` `distinct` `element` `flatten` `index` `keys` `length` `lookup` `matchkeys` `merge` `one` `range` `reverse` `setintersection` `setproduct` `setsubtract` `setunion` `slice` `sort` `sum` `transpose` `values` `zipmap` |
| Encoding | `base64decode` `base64encode` `base64gzip` `csvdecode` `jsondecode` `jsonencode` `textdecodebase64` `textencodebase64` `urlencode` `yamldecode` `yamlencode` |
| Hashing | `base64sha256` `base64sha512` `md5` `sha1` `sha256` `sha512` `uuid` `uuidv5` and the `file*` hash variants |
| Network | `cidrhost` `cidrnetmask` `cidrsubnet` `cidrsubnets` |
| Numeric | `abs` `ceil` `floor` `log` `max` `min` `parseint` `pow` `signum` |
| Conversion | `tobool` `tolist` `tomap` `tonumber` `toset` `tostring` |
| Time | `formatdate` `timeadd` `timecmp` `timestamp` `plantimestamp` |
| Marks (pass-through) | `sensitive` `nonsensitive` |
| Files, paths, templates | `abspath` `basename` `dirname` `file` `filebase64` `fileexists` `fileset` `pathexpand` `templatefile` `templatestring` |

Module API:

| Name | Description |
| --- | --- |
| `call(name, *args, base_dir=None)` | Call with native data, return native data. |
| `call_value(name, *values, base_dir=None)` | Call with cty-like values, return a cty-like value. |
| `evaluate(expr, variables=None, base_dir=None)` | Evaluate an HCL expression, return native data. |
| `evaluate_value(expr, ctx)` | Same, on values, with a `Context`. |
| `can(expr, ...)`, `try_(*exprs, ...)` | The `can` and `try` semantics. |
| `function_names()` | Sorted registered function names. |
| `from_python(obj)`, `to_python(value)` | Convert between native data and values. |
| `format_value(value)` | `terraform console` rendering. |

## How it works

- Numbers are binary floats with Terraform's rules: 512-bit mantissa for literals,
  64-bit for integers from functions, 53-bit for `pow` and `log` (which go through
  float64), rounding to nearest even, and shortest round-trip printing at the
  value's own precision. `1/3` prints 155 digits, `pow(2, 1000)` prints 17 digits
  and zeros.
- Sets are ordered as cty orders them: strings bytewise, numbers ascending, bools
  false first, nulls last, other values by cty's hash-string comparison.
- Function arguments are converted with cty's unification rules (`[1, "a"]` becomes
  `["1", "a"]`, `[1, true]` does not unify, objects with different keys unify to a map).
- All strings are normalized to NFC, as cty does.
- `regex`, `regexall` and `replace` run on `tfstdlib.re2`, a parser and backtracking
  matcher for Go's regexp syntax (visited-state memoization, so matching is linear in
  pattern times text). Python's `re` differs in `\d`, `$`, empty-match handling and
  nested empty loops.
- `length`, `substr` and `strrev` count extended grapheme clusters
  (`tfstdlib.graphemes`, UAX #29 without Indic conjunct rules).
- `tfstdlib.hcl` parses and evaluates expressions and templates: operators,
  conditionals, `for`, splat, `%{ if }`, `%{ for }` and `~` strip markers (a template
  file strips only the adjacent line-sized chunk, a quoted string strips all
  whitespace, both as Terraform does).
- YAML: `tfstdlib.yamlcore` implements Terraform's resolution rules (`yes`, `no`,
  `on`, `off`, `y`, `n`, `0o17`, `0x1f`, dates become RFC 3339 strings, merge keys,
  anchors) and its emitter (every string double-quoted, literal blocks for
  multi-line strings, folding at 80 columns). PyYAML is not used: its YAML 1.1
  resolver, quoting and folding differ from Terraform's output, so an exact own
  implementation was preferred over an optional dependency.
- CIDR functions reproduce go-cidr's edge cases (negative `netnum` wrapping,
  the int64 range checks, `cidrsubnets` on prefixes that start at zero).

## Limitations

- Not implemented: `bcrypt` and `rsadecrypt` (need bcrypt and RSA), `issensitive`,
  `provider::` functions, the console-only `type`, and
  heredocs inside expressions. `sensitive` and `nonsensitive` return their argument
  because marks are not tracked. Unknown values are supported only in the simple
  "unknown in, unknown out" sense.
- Functions whose result varies (`uuid`, `timestamp`, `plantimestamp`) are
  implemented but are not in the gold corpus.
- `templatestring` renders the given text. Terraform requires its argument to be a
  reference to a string elsewhere in the configuration, which a function cannot check.
  It is not in the gold corpus.
- Unicode scripts in `\p{Greek}`, `\p{Han}` and the like use a built-in table of
  about twenty scripts by block range. General categories come from Python's
  `unicodedata` (Unicode 16 on Python 3.14), Terraform's Go uses an older table.
- Grapheme clusters follow Unicode 13-era rules with approximate emoji data.
- `base64gzip` output decodes to the same bytes but is byte-identical to Go's
  only where zlib and Go's compressor make the same choices (checked for short
  inputs).
- `log` uses a port of the fdlibm algorithm Go uses; `pow` reproduces Go's
  algorithm with C `exp` for fractional exponents. Results were identical on every
  corpus case, but a last-digit difference on other inputs is possible (Go on arm64
  fuses multiply-add, which is not modeled).
- `textencodebase64` and `textdecodebase64` support about fifty IANA encodings.
- YAML: multi-document streams, complex keys and the exotic tags (`!!set`,
  `!!omap`) are rejected, as Terraform rejects them, but error messages differ.
- Terraform's error wording is approximated. Only the error or no-error outcome
  is verified.
- The gold corpus comes from Terraform 1.16.2 only.

## Compatibility

Run here: Python 3.14.7 on macOS (arm64), Terraform 1.16.2. The CI workflow runs
the suite on 3.11, 3.12, 3.13 and 3.14 (untested locally except 3.14). The
project uses `math.fma` nowhere and no 3.12+ syntax, but 3.11 to 3.13 were not run
by the author.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy src tests tools --strict
```

Regenerate the gold corpus (needs `terraform` on PATH; it works in a temporary
directory and deletes it):

```sh
python tools/make_gold.py
python tools/compare.py          # summary and every mismatch, optional prefix filters
```

The live tests in `tests/test_live.py` re-run a sample against your installed
Terraform and skip with an explanatory message when it is missing.

## License

MIT, see [LICENSE](LICENSE).

Terraform itself is BUSL-1.1 and none of its source was read or copied. Behavior
comes from the public function documentation and from running `terraform console`.
The function library underneath it, `zclconf/go-cty` (`function/stdlib`), is MIT;
its semantics were reimplemented from observed behavior and its license is shipped
as [LICENSE-go-cty](LICENSE-go-cty). `hashicorp/go-cty-funcs` (MPL-2.0) was not
read or ported. The `log` function uses the public fdlibm algorithm and constants.
`tests/data/gold.jsonl` and the corpus generators are original data and code.

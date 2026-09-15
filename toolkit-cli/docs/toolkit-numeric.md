# Toolkit integer conversion

`toolkit_numeric.parse_toolkit_integer()` implements a bounded, independent
numeric conversion for Toolkit 1.18.0. It does not consult the host locale or access the registry. The preferences
store and controls can select this conversion with an explicit `numeric_locale`;
the CLI exposes `--numeric-locale dot|comma` for `preferences controls`, `plan`,
and `registry-load`. Canonical behavior remains the default. The separately
accepted [preferences integration](toolkit-preferences.md) passes 63 tests on
each supported Python version, including 13 native Windows registry cases.

```python
from cbus_toolkit.toolkit_numeric import parse_toolkit_integer

result = parse_toolkit_integer('1.234,56')
assert result.value == 1234
assert result.normalized_text == '1234.56'
assert result.separators_swapped
```

Inputs must be strings of at most 64 ASCII characters, without NUL. The only
supported locale pairs are decimal `.` / thousands `,`, or decimal `,` /
thousands `.`. They are explicit fixtures, independent of the machine locale.
Other character sets, separator pairs and longer strings raise
`UnsupportedToolkitNumericInput`.

The original JCL routine first examines prefix signs and punctuation. Prefix
minus signs toggle the sign; spaces, `(` and `+` are skipped. It can exchange
decimal and thousands separators, then retains digits and the decimal
separator. For example, `6A4` becomes 64, `1e3` becomes 13, `(64)` becomes 64 and
`--64` becomes 64. These are intentional original semantics. Multiple decimal
separators left after filtering raise `ToolkitNumericConversionError`, matching
the original floating parser's error path.

The executable multiplies and adds each digit with 64 significant bits of x87
extended precision, rounding each operation to nearest/even. Decimal scaling
uses the original two-stage powers of ten. The Python implementation uses exact
integer ratios and rounds at these same instruction boundaries; it does not
approximate this with Python `float` or a final decimal truncation.

The original truncates to a signed 64-bit integer and returns its low 32 bits.
The immutable result reports both `truncated_integer` and final `value`, plus
`int32_wrapped`, `normalized_text`, prefix `negative`,
`separators_swapped` and the stored `extended80_hex`. Negative zero is retained
in that floating representation. `as_dict()` returns a detached export.

Signed64-bit truncation overflow is explicitly unsupported. The Unicorn
execution returned zero for these observations even when supplied the original
unmasked control word. That does not establish actual Windows exception
delivery, so zero is not implemented as an overflow result. There is no GUI
validation, registry fallback or preference overwrite in this module.

## Independent evidence

The hash-pinned executable is `CBusToolkit.exe` SHA256
`9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`.
`research/toolkit_numeric_original.py` executes its original x86 instructions
without importing the Python converter. Managed strings, locale globals and
ASCII classification are explicit runtime fixtures. Optional original UI
validation also uses fixture text reads and error dialogs; it is not an actual
GUI binding or Windows locale-initialization test.

The source ledger is:

| Original address | Behavior |
| --- | --- |
| `0x78299c` | JCL sign scan, separator exchange, filtering and floating conversion |
| `0x782c2c` | JCL integer conversion, low 32 return |
| `0x61ced4` | Original per-digit floating parser, saved/restored control word |
| `0x605dc8` | Original decimal scaling |
| `0x604edc` | Truncation toward zero into signed 64 |
| `0x13a2698` | Parser control word `0x133f` |
| `0x13a1024` | Original default control word `0x1332` |

The frozen original vectors contain 316 direct cases: 272 supported conversions,
four conversion-error cases and 40 explicitly unsupported overflow observations.
All 33 relevant original power constants are independently compared with the
exact generated values. The 66 historical original UI-validator cases are
preserved and re-executed separately.

Run the nine focused tests with the exact executable supplied explicitly:

```sh
CBUS_TOOLKIT_EXE=/owned/path/CBusToolkit.exe PYTHONPATH=src \
  python -m unittest tests.test_toolkit_numeric -v
```

Without the executable, the seven pure tests still compare the implementation
with the frozen original vectors; the two executable tests skip. The original
probe requires the pinned research dependencies `pefile` and `unicorn`. Full
run provenance and limitations are recorded in
`research/fixtures/toolkit-numeric-acceptance.json`.

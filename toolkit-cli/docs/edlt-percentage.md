# eDLT percentage arithmetic

`cbus_toolkit.edlt_percentage` exposes the arithmetic of the original Toolkit 1.18.0.2754 `NumUpDownPercentage` property, using the default 0–100 percentage and 0–255 byte domain:

```python
from cbus_toolkit.edlt_percentage import byte_to_percentage, percentage_to_byte

byte_to_percentage(3)                       # '1.1764705882352941176470588235'
percentage_to_byte('1.1764705882352941176470588235')  # 2
percentage_to_byte('50')                    # 127
percentage_to_byte('100')                   # 255
```

`byte_to_percentage` accepts an exact Python `int` from 0 through 255, excluding booleans and subclasses. It returns exact, shortest fixed-point decimal text. `percentage_to_byte` accepts an exact Python `str` matching `[0-9]{1,3}(?:\.[0-9]{1,28})?`, at most 32 ASCII characters, with numeric value from 0 through 100. Leading zeros are accepted within the three-digit limit. Trailing fractional zeros are accepted and removed before checking exact .NET Decimal representability. Thus `050.000` and `100.0000000000000000000000000000` are valid.

Input must have a representation with an unsigned 96-bit coefficient and scale from 0 through 28. Values requiring rounding merely to enter that representation are rejected, including `79.228162514264337593543950336`. Signs, whitespace, exponent notation, decimal commas, non-ASCII digits, floats and `Decimal` objects are rejected. No locale or Python `decimal` context participates.

The original setter converts an integer to Decimal, multiplies by 100 and divides by 255. Within this byte domain, the first multiplication is exact. The getter multiplies the percentage by 255, rounds that result as .NET Decimal, divides by 100 with a separate Decimal rounding, then truncates to an integer. Each arithmetic rounding uses the largest fitting scale up to 28 and rounds midpoint ties to even. Combining these operations into a single rational conversion changes some results. For example, the captured original getter returns 20 for `7.84313725490196078431372549`.

A byte-to-percentage-to-byte roundtrip loses one for 37 of the 256 original byte values. The helper preserves those outcomes; it does not automatically roundtrip a caller's existing raw level.

## Evidence and limits

[The portable vectors](../research/fixtures/edlt-percentage-vectors.json) retain 290 original rows that matched on Windows .NET and owned macOS Mono. They contain all 256 byte roundtrips, ten getter inputs and 24 setter/bound combinations. The public API covers 270 rows; twenty custom-bound or non-byte setter rows remain outside its domain. A further 6,214 getter cases construct original Decimal values directly from the 96-bit coefficient and scale, covering byte thresholds, scale boundaries and coefficient limits. That supplement was executed on Mono only.

The original `eDLT.dll` SHA-256 is `75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3`. The probe copies the original getter and setter IL, redirecting only six NumericUpDown property-call occurrences to four decimal-field accessors. A separate verifier rereads the written executable and checks all 44 instructions, three branch targets and method calls. The executed probe prints its own executable hash and the actual loaded Decimal assembly path, identity, hash and process bitness. Historical Windows and Mono captures executed the same `98e72bdd…dcb2` artifact with identical 290 value outcomes.

The actual loaded Mono 64-bit `mscorlib.dll` hash is `86364b7803c92d8c88b590031f015f80b10b00641e9d067e07a529a131d815e4`; Windows Framework64 is `5bffb20e1217bad314143d7e5c4c809bf9f522e8a0a063c8e7e9b25113de26eb`. Historical captures, including earlier provenance-limited and preflight-failure attempts, remain under `research/runtime/edlt-percentage-research`. Exact source, input and output hashes are linked in the portable fixture.

[The original probe helper](../research/edlt_percentage_original.py) compiles a fresh field fixture, copies and verifies the original IL, and checks all 6,504 rows. It requires the pinned original DLL and owned Mono toolchain. The package conversion module needs only Python's standard library and no original files.

This is arithmetic parity for the declared domain. The field fixture does not execute WinForms control construction, NumericUpDown range validation, decimal-place display formatting, text parsing, linked controls, bindings, notifications or GUI events. It establishes no automatic editor roundtrip or physical-device behavior.

### Separate actual-control observations

[The control observation fixture](../research/fixtures/edlt-percentage-control-observations.json) records a 12-case pilot and 528 cases using the actual original standalone control on Windows x86 .NET Framework. It pins the source, inputs, raw reports, compiled probes and actual loaded assemblies. All cases were captured and disposed; the 528-case matrix includes thirteen original `ArgumentOutOfRangeException` operations, recorded separately from capture failures. All 256 default byte outcomes match the arithmetic helper, including the 37 roundtrip losses. The observer preserved all 14,148 compared numeric/Boolean state pairs in the matrix.

Displayed text and editing behavior remain separate from the arithmetic API. For byte 3, the control retains the exact internal percentage above, returns byte 2 and displays `1` at its default zero decimal places. Text entry varies by culture and input surface; direct out-of-range `Value` assignments raise while numeric text can clamp. The six targeted click/mouse-up cases recorded no corresponding action event, so they do not establish execution of the constructor-wired click handlers. These are standalone control observations, without whole-form bindings or a new public control API.

## Focused checks

```sh
PYTHONPATH=src:. python -m unittest tests.test_edlt_percentage -v
```

Nine portable tests run without original binaries. The tenth test additionally requires `CBUS_TOOLKIT_EXE` and `CBUS_MONO_MACOS_ROOT`, and executes only the local arithmetic fixture. Set `CBUS_PERCENTAGE_REPORT_DIR` to an existing owned output directory to retain its report and compiled probe artifacts in a fresh `original` subdirectory. No VM, C-Gate, registry or physical network is involved.

[The focused acceptance fixture](../research/fixtures/edlt-percentage-acceptance.json) records both Python runs, the archived exact inputs, fresh written-IL audit and actual loaded Decimal runtime. CLI integration and full-wheel checkpoints have separate acceptance.

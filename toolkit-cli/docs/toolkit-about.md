# Toolkit About information

`toolkit-about` reads an explicitly supplied PE executable and formats Toolkit's About information without executing the file, discovering an installation, connecting to C-Gate or reading the registry.

```sh
cbus-toolkit toolkit-about /path/to/CBusToolkit.exe
cbus-toolkit toolkit-about /path/to/CBusToolkit.exe --year 2026
cbus-toolkit toolkit-about /path/to/CBusToolkit.exe --context captured-context.json
```

The default copyright year is the current local calendar year, matching the original menu's `CurrentYear` call. `--year` supplies a deterministic override. The result identifies the source and whether the clock was read. The pure Python helper always requires an explicit year.

PE reading uses the existing optional dependency:

```sh
python -m pip install 'cbus-toolkit-cli[research]'
```

## What each field means

| Field | Source and behavior |
| --- | --- |
| Version and build | Four unsigned words from `VS_FIXEDFILEINFO.FileVersionMS/FileVersionLS`. Product-version numbers and textual FileVersion/ProductVersion do not select the displayed version. |
| Beta suffix | FileFlags bit `0x02` gives ` Public Beta`; when `0x08` is also set it gives ` Beta`. Bit `0x08` alone gives no suffix. |
| Special-build suffix | FileFlags bit `0x20` gives ` Special Build`. The original reader ignores FileFlagsMask. |
| Product/display name | The explicit EXE's ProductName string is supplied to the original text formula. This is a declared substitution: the original menu obtains its name from a live application-name provider, which this command does not observe. If the string is absent, the report identifies its `C-Bus Toolkit` profile fallback. |
| Copyright | Original Toolkit 1.18 company literal plus the chosen year. It does not use the EXE's LegalCopyright year. |
| C-Gate/Java/memory | Optional caller-supplied context, explicitly unverified. Values are neither queried nor checked against a live service. |

`resource_product_name`, `executable_resource`, `provenance`, input SHA-256 and the original-provider-observed flag keep these origins visible. A matching pinned EXE hash reports byte identity with the researched file; it does not authenticate arbitrary executables or certify their publisher.

Exact original text spacing is retained, including the trailing space in `Version 1.18.0 (build 2754) ` and the two spaces before `Special Build`. An absent VERSION resource produces `Version (unknown) (build unknown) `. Malformed or ambiguous resources produce an input error instead of silently selecting a value. These are diagnostics: a completed report with an unknown version still exits 0; input or read failures exit 1, and KeyboardInterrupt follows the existing exit 130 path.

## Captured context

When supplied, the JSON object must contain exactly these five fields:

```json
{
  "version": "3.3.2",
  "build": "2039",
  "max_memory_mb": 512,
  "used_memory_mb": 42,
  "java_version": "11.0.32"
}
```

Memory values represent the already-returned integer values passed to the original About menu. The command appends the original `MB` labels and performs no byte-to-MB conversion. Signed Int64 values, including negative caller-supplied values, remain visible. Strings retain spaces and Unicode; NUL and unpaired surrogates are outside the supported domain. With no context, the original `(Installation not selected)` text appears and the memory/Java labels are empty. A supplied empty Java string also leaves that label empty.

The context file is limited to 16 KiB with duplicate-key, integer-token, nesting and exact-field checks. EXEs are limited to 64 MiB. Only regular files are opened; directories, symlinks and FIFOs are rejected. Unix no-follow/nonblocking flags and a descriptor check cover ordinary replacement races. The first read interruption is retained even when descriptor cleanup raises a second interruption.

The resource reader supports one numeric VERSION resource named 1, one language and one string table. Resource data is limited to 65,536 bytes with bounded blocks, lengths and nesting; duplicate fields and unsupported signatures or shapes are rejected. It uses PE header/address readers and reads resource bytes directly. It does not claim Windows language-selection, MUI merging or arbitrary malformed-resource behavior.

The pinned EXE uses type-0 empty containers for StringFileInfo and its string table. The reader accepts bounded empty type-0/type-1 containers; individual string values must still be terminated text leaves.

## Python and original evidence

```python
from cbus_toolkit.toolkit_about import inspect_executable, format_about

report = inspect_executable(exe_bytes, year=2026, context=None)
print(report.as_dict())

# Pure formula; all values below are explicit caller inputs.
print(format_about((1, 18, 0, 2754), flags=0, year=2026).as_dict())
```

[toolkit-about-vectors.json](../research/fixtures/toolkit-about-vectors.json) contains 51 original instruction cases. The probe executes the unchanged menu, GetApplicationVersion, original version-field readers, About field setters, initialization and text assembly. It covers all relevant flag combinations, ignored flag masks/high bits, version-word extremes, three OS version-query failures, Unicode/empty/signed-Int64 context, years and product-name inputs.

Allocation, strings, integer-to-text conversion, OS version queries, the clock, C-Gate getters and controls are explicit probe fixtures. No original form constructor, modal window, image loader, error-test key handler, network or registry operation executes. The test observes text passed to control methods, not a rendered dialog or a real Windows version API call. The pinned EXE's actual resource bytes are tested independently through the offline reader. All 16 focused tests passed on Python 3.13 and 3.10 without skips, with 51 fresh original cases in each run. Results, exact input archives and preserved development failures are recorded in [toolkit-about-acceptance.json](../research/fixtures/toolkit-about-acceptance.json).

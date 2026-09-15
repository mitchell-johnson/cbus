# Read-only eDLT firmware diagnostics

`firmware_diagnostics.py` identifies an eDLT through its USB diagnostic serial
interface, reads current/embedded NCC versions, and inspects firmware package
directory metadata. The supported serial requests are exactly `id\r` and
`nv\r`. Firmware extraction, DFU upload, flash erasing, NCC update, restart,
USB enumeration and physical hardware operation remain unimplemented or
unverified in this workflow. See [firmware-research.md](firmware-research.md)
for the separate updater investigation.

## CLI and Python API

Install the optional `serial` extra, pinned to pyserial 3.5, when opening a
serial port. Pure parsing and ZIP metadata inspection use the standard library.

```sh
cbus-toolkit firmware identify --port COM7
cbus-toolkit firmware ncc-versions --port COM7
cbus-toolkit firmware identify --port COM7 --package eDLTFirmware_1.7.0.zip
cbus-toolkit firmware parse-id captured-identification.txt
cbus-toolkit firmware parse-ncc captured-ncc.txt
cbus-toolkit firmware classify-hardware '3.0 (Tiva + NCC)'
cbus-toolkit firmware inspect-package eDLTFirmware_1.7.0.zip
```

Use the explicit diagnostic port for the intended unit; the helper does not
guess a port from USB identifiers or attach to C-Gate. A serial query opens
the named port at 9600 baud, eight data bits, no parity, one stop bit and no
handshake. It sends one request and closes the port after a result or error.
Timeout defaults to ten seconds and is bounded at sixty seconds. Failed or
partial queries are not retried.

`SerialDiagnostics(port, timeout=10).identify()` returns an `Identification`;
`.ncc_versions()` returns `NCCVersions`. Both provide `as_dict()`.
`parse_identification(bytes)` and `parse_ncc_versions(bytes)` parse captured
CRLF responses. `DiagnosticParser('id' | 'nv').feed(bytes)` supports chunks.
`classify_hardware(text)`, `inspect_package(path)` and
`compare_package(identification, metadata)` cover the offline comparisons.

`DiagnosticError.details` retains partial fields/messages. If closing the
port also fails, `close_error` supplements the primary error. A complete ID
response means that an original native field set is present; `usable_identity`
additionally rejects blank identity fields, an unknown hardware variant and
conflicting data. Package comparison requires usable identification. Reported
versions do not establish firmware image contents.

## Native parsing behavior

The original `EdltSerialInterface` incrementally splits CRLF lines. ID lines
split at the first equals sign and trim the key and value. NCC lines split at
the first colon and trim only the value. A line without its separator becomes
a key with an empty value. Duplicate keys overwrite earlier values; this
implementation additionally marks changed duplicates as ambiguous.

The three exact accepted identification field sets are:

| Native schema | Required keys |
| --- | --- |
| Firmware 1 | Manufacturer, Model, Serial Number, Version, Authors, Cpu_Speed, Unit Address |
| Firmware 2 | Manufacturer, Product, Serial Number, HW Version, FW Version, Authors, Cpu_Speed, Unit Address |
| Firmware 3 | Manufacturer, Product, Serial Number, HW Version, FW Version, CPU Speed, Unit Address |

Hardware version is empty for the legacy schema. When both Version and
FW Version are present, the original prefers Version; conflicting values
remain explicitly ambiguous here. NCC versions use the exact keys
`NCC current version` and `NCC embedded version`. The original returns true
with empty versions for `COMMAND NOT VALID`; the typed result instead reports
`supported=false`, `complete=false` and retains that response. Two version
keys accompanied by that error are ambiguous. Empty or invalid version values
are incomplete version identification, even when both keys are present.

NCC comparison follows the original `System.Version`: two to four nonnegative
Int32 components, with missing build/revision represented by -1. Thus `1.0`
sorts before `1.0.0`. Signed positive components and ASCII component whitespace
are supported as in the original runtime. Unicode whitespace accepted by
`String.IsNullOrWhiteSpace` is separately matched for hardware classification.

Default parser bounds are 64 KiB per response, 4096 characters per line and
256 fields. Non-ASCII wire data and unverified control characters are rejected.
These limits and ambiguity reporting are deliberate additions to the original
unbounded parser. They are not claimed as Toolkit GUI behavior.

## Hardware and archive metadata

`EdltFirmwareUpgradeArgs.HardwareVersion` maps empty/whitespace text,
`1 (Stellaris)` and `1.0 (Stellaris + PCI)` to Stellaris/PCI. It recognizes
`2 (Tiva)` without regard to case, but requires exact case for
`2.0 (Tiva + PCI)` and `3.0 (Tiva + NCC)`. Other text remains Unknown.

Package version is the filename without its extension, followed by the text
after its first underscore. Archive inspection reads only directory records
and hashes the archive. No password is supplied, no entry stream is opened,
and no firmware data is extracted. The package may remain encrypted.

Original main-image selection uses case-sensitive substrings `main` and
`hwv1`, `hwv2` or `hwv3`, in that order; font selection uses `font`. Later
matching entries replace earlier matches. The metadata result preserves all
candidates, reports the original last selection, and marks multiple candidates
as ambiguous. Entries which the original ZIP reader considers non-files are
reported as invalid. Metadata inspection is bounded to 512 MiB and 1024 entries.
Presence of matching directory names is not image compatibility or authenticity
verification, and the comparison never authorizes or performs an update.

## Acceptance evidence

Fifteen focused tests pass with all prerequisites enabled. The unchanged
`FirmwareUpdater.exe` assembly, version 1.16.3.0, runs under a pinned Mono image
for these comparisons:

- 15 hardware classification vectors, five package-name vectors and 14
  `System.Version` cases.
- Both original private serial response handlers reading actual Linux PTYs
  through `System.IO.Ports.SerialPort`, including split CRLF, separators,
  whitespace and duplicate updates; all three native completion predicates.
- Original ZIP directory reading for all four bundled firmware archives and
  their eleven entries, without entry extraction.

An independent Python PTY peer accepts only the literal expected request and
supplies three ID responses, one NCC version response and one unsupported NCC
response to pyserial. Other tests cover bounds, partial timeout, transport
failure, port close failure, ambiguity and package selection.

The original serial handlers are invoked directly after fixture bytes arrive;
the original updater's polling/event lifecycle, complete GUI workflow, Windows
driver and real USB device are not exercised. The package role-selection
branches are grounded in original decompiled code; the original extraction
workflow is not executed.

Source hashes and compact counts are recorded in
[firmware-diagnostics-acceptance-summary.json](firmware-diagnostics-acceptance-summary.json).
To reproduce from `toolkit-cli` with the serial extra and Docker available:

```sh
CBUS_FIRMWARE_UPDATER=research/vendor/toolkit/app/FirmwareUpdater.exe \
CBUS_FIRMWARE_DIAGNOSTIC_REPORT=research/runtime/firmware-diagnostics-acceptance.json \
.venv/bin/python -m unittest discover -s tests -p test_firmware_diagnostics.py -v
```

The native test requires the matching original updater and all four original
archive files. Missing explicit native/serial prerequisites are reported as
skips and do not count as acceptance passes.

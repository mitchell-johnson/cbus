# Toolkit unit template XML

The CLI exports, inspects and applies Toolkit `UnitTemplate` XML for three
exact profiles, all at **firmware 1.2.67**, using the user's original unit
specifications:

| Unit type | Catalogue number | Specification |
| --- | --- | --- |
| KEY1 | 5031N | KEY1.xml |
| KEY2 | 5032N | KEY2.xml |
| KEY4 | 5034N | KEY4.xml |

This transfers the 26 native parameters selected by the original Toolkit
template attribute list. It preserves destination address, project, serial
metadata and parameters excluded from that list. `UnitName` is included and
is therefore copied.

This is a bounded template workflow. It does not establish template support
for other profiles, cross-model conversion, physical device transfer or full
GUI parity. The existing JSON PP snapshots have a separate format and scope.

## Usage

```sh
cbus-toolkit unit-templates --spec-dir /path/to/unitspec export key4-parameters.json key4-template.xml
cbus-toolkit unit-templates inspect key4-template.xml

cbus-toolkit cgate --host 127.0.0.1 unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/230 template-export key4-template.xml \
  --spec-dir /path/to/unitspec

cbus-toolkit cgate --host 127.0.0.1 unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/231 --dry-run template-import key4-template.xml \
  --spec-dir /path/to/unitspec
```

Removing `--dry-run` applies and saves the destination database unit. Native
template import through the CLI is restricted to database destinations. File
exports refuse to overwrite an existing output. The offline export accepts
a matching PP snapshot or a parameter mapping; a mapping's origin cannot be
independently established from its values alone.

The Python API is `UnitTemplates(spec).export(session)`,
`UnitTemplate.from_xml(document)`, `template.to_xml()`, and
`UnitTemplates(spec).apply(session, template)`. The apply method validates
the complete desired data and native schema before writes, reads back every
included parameter, and leaves saving to the caller. It stops after the first
write or transport failure and returns partial-attempt details through
`UnitTemplateApplyError`; it does not retry or perform automatic rollback.
`UnitTemplates(spec, firmware='1.2.67', catalog_number=None)` infers the tested
catalogue number from the specification and rejects other firmware/catalogue
combinations. `PROFILES` exposes the three exact profiles; the existing
`PROFILE` constant remains KEY4. A template's identity must match the selected
profile exactly. These tests do not establish cross-type conversion.

CLI exports/imports default to KEY4. Pass `--profile KEY1` or `--profile KEY2`
to the relevant export/import command for those profiles; offline snapshot
identity is checked against that selection.

## Exact format and source evidence

Source locations below are virtual addresses in the locally supplied Toolkit
1.18 EXE, not distributable vendor code. Source hashes and acceptance counts
are in [unit-template-acceptance-summary.json](unit-template-acceptance-summary.json).

| Original routine | Evidence used |
| --- | --- |
| `TCBusUnitCGateAgent.SaveTemplate`, `0xCC3A6C` | XML declaration, root, blank Description, explicit UnitType/FirmwareVersion, decimal CRC, then selected attributes |
| Key-input constructor chain, `0x1215B0C`, `0xCC6D18`, `0xCC643C`, `0xCC5AA0`, `0xCB524C` | Exact attribute creation order and template flag `+0x6C` |
| Agent registrations, `0x1397528`, `0x1397540`, `0x1397558` | TKey1, TKey2 and TKey4 use the same TCBusKeyInputCGateAgent |
| `TFlashAttribute.Create`, `0x7EC504` | Persistent flag `+0x30` defaults to one; template inclusion is a separate flag |
| `CalcTemplateCRC`, `0xCBCECC` | Ordered trimmed attribute values, leading `0x` array conversion, concatenation and open-array argument |
| `CIS_Maths.CalculateCRC`, `0x7F1FDC` | Seed `0xFEED`, polynomial `0x1021`, low input bit first, final input byte omitted |
| `GetAttributeValue`, `0xCC4DE8` | First matching line/tag extraction used by the template reader |
| `LoadAttribute`, `0xCC4C1C` | Extract text, decode XML entities with `0xC1B11C`, then call the attribute setter |
| String attribute XML conversion, `0x7F39F8`, `0x7DF174` | Escape double quotes, ampersands and angle brackets |

The exact 30 selected attributes, in order, are:

```text
Application FirmwareVersion UnitName UnitType LearnAnyApp LearnMode
AreaGroupAddress StatusReportInterval GroupAddress DebounceTime
IndicatorBrightness LongPressTime EEPROMLevelStore LightIndex LightLevel
LightLevelStore1 LightLevelStore2 RampRate InfraRedBank JPCommand SRCommand
LPCommand LRCommand BlockAllocation IndicatorBlockAssignment
IndicatorFunction TimerHighByte TimerLowByte TimerExpiryCommand GAVBroadcastFlag
```

Toolkit explicitly writes identity before its CRC and includes the matching
identity attributes again in the subsequent list. The exporter preserves
these duplicate UnitType and FirmwareVersion elements. The parser accepts
one or two matching copies and rejects conflicts. Project, SerialNo, State,
UnitAddress and LearnedFlag are excluded by the original template flags.

UnitType and FirmwareVersion are validated metadata. InfraRedBank and
GAVBroadcastFlag are agent properties absent from these profiles' native
parameter schema; this workflow supports only their default zero values.
The remaining 26 attributes are native PP parameters. Scalar integers and
booleans serialize as decimal text. Arrays serialize as decimal values
separated by spaces. Import checks the original CRC before canonicalizing
array whitespace, because Toolkit retains interior decimal whitespace while
calculating its checksum.

Files use UTF-8 and CRLF lines. The supported data is ASCII, with canonical
uppercase sixbit UnitName text and no ambiguous `?` character. Quotes,
ampersands and angle brackets in UnitName are tested through original
encoding/decoding and native PP save/reload. Numeric XML character references,
declarations, processing instructions, comments, unknown elements and nested elements are rejected.
Non-ASCII file I/O is unverified. Description is optional CLI metadata,
excluded from the checksum and never programmed; original SaveTemplate writes
an empty Description. The CLI can preserve a nonempty single-line Description.

`PP LOAD_FROM_FILE` is not an XML-template import command. The native command
handler `lD.java` expects a **unit specification file**. Toolkit reads template
XML locally and applies its attributes through the unit agent. This helper
follows that distinction.

## Validation and limits

Fifteen focused tests pass with the original EXE, native C-Gate 3.4.0 build
2001 and original unit specifications supplied. They include:

- Literal format/CRC vectors, original constructor flag/order checks, and
  original registrations of all three concrete unit classes.
- Execution of the original checksum, line-reader and XML encoding/decoding
  routines using Unicorn 2.1.4 and pefile 2024.8.26.
- Three native closed-database transfers, each covering all 26 included
  parameters, 28 independently specified raw bytes, XML-special UnitName
  characters, destination identity preservation, and a complete save/reload.
  The totals are 78 parameter transfers, 84 raw bytes and three save/reloads.
- Corrupt checksums, incompatible profiles/schemas, bounds, duplicate fields
  and partial-write behavior.

The executable probes run unmodified routine instructions in an x86 CPU
emulator. Memory, Delphi string allocation and text-file runtime primitives
are isolated test fixtures. The complete Toolkit GUI process is not executed;
GUI import/export and physical hardware remain unverified. Research dependencies
belong to the optional `research` extra, not the production template module.

Reproduce from `toolkit-cli` after installing the research extra:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_UNIT_TEMPLATE_REPORT=research/runtime/unit-template-acceptance.json \
.venv/bin/python -m unittest discover -s tests -p test_unit_templates.py -v
```

The native test creates and deletes a unique temporary project and uses only
closed `/db` unit sources. Missing native/EXE prerequisites are explicit test
skips, never counted as acceptance passes. The recorded run used CPython 3.13;
Python 3.10 executable-probe acceptance is tracked separately by the installed
wheel harness.

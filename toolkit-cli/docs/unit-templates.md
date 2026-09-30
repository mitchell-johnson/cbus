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
metadata and, for the verified database transaction, the stable excluded
values listed below when the C-Gate schema exposes them. `UnitName` is
included and is therefore copied.

This is a bounded template workflow. It does not establish template support
for other profiles, cross-model conversion, physical device transfer or full
GUI parity. The existing JSON PP snapshots have a separate format and scope.

## NeoPro key-input profiles

The Python API also covers the 30 NeoPro-agent key-input types admitted by
`research/fixtures/key-preset-family-equivalence.json`, at **firmware
2.5.00**. They are KEYA1/3/6/8, KEYAV2/4, KEYB2/4/6, KEYC1/2/4, KEYCIR4,
KEYDV1–4, KEYH1–4, KEYM2/4/8, KEYP2/4/6 and KEYV1–3. `NEO_PROFILES` gives
each type's default catalogue number. `NEO_CATALOGS` lists every catalogue
number that selects the specification at that firmware, and
`UnitTemplates(spec, catalog_number=...)` accepts any of them. KEYE1 has a
different agent and remains unsupported.

The attribute list is the `TCBusNeoProInputCGateAgent` constructor order,
restricted to template-flagged attributes, with 58 names in
`NEO_ATTRIBUTE_ORDER`. It follows the shared key-input order, except that
the Neo agent renames `InfraRedBank` to `IRBank` and `GAVBroadcastFlag` is
absent. It then adds the Neo, NeoPro and corridor/join attributes, ending
with `NightlightColour`. The same five classic names are excluded: Project,
SerialNo, State, UnitAddress and LearnedFlag. `PatchEnable` is
template-flagged and is therefore copied. All 56 non-identity names are
native PP parameters, so the list has no virtual attributes. The checksum
normalizes the NeoPro integer and boolean attribute classes, as it does for
classic templates.

Owned native C-Gate 3.4.0.2001 acceptance
(`tests/test_unit_templates_neo.py`) ran all 30 profiles. Each source
database unit received non-default values for all 56 parameters. The test
exported and parsed the XML, applied it to a second unit, saved it with PP
SAVE_TO_SOURCE, re-exported and checked identity preservation. All 30
targets were identical after project save, close and load. The template CLI
commands and the database copy/default-reset transaction remain classic-only;
`NativeTemplateTransaction` refuses NeoPro templates because it preserves
PatchEnable. Toolkit's `SaveTemplate` first runs the agent's
`BeforeSaveProgrammingInformation`. This export assumes that step leaves
loaded PP values unchanged, and it does not model any normalization that
step may perform.

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

cbus-toolkit cgate --host 127.0.0.1 unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/230 --destination /db//TEST/254/p/231 \
  --dry-run template-copy --profile KEY4 --spec-dir /path/to/unitspec

cbus-toolkit cgate --host 127.0.0.1 unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/231 --dry-run template-reset-defaults \
  --profile KEY4 --spec-dir /path/to/unitspec
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

## Verified database copy and template-default reset

`template-copy` performs a complete bounded transfer without creating an
intermediate file. Both `--source` and `--destination` must be distinct
database units under the exact `--lock-address`, and both must match the
selected KEY1, KEY2 or KEY4 profile. The operation reads the source template,
opens a separate destination PP session, validates all 26 values and the
native schema, stages only changed fields, and confirms the staged template.
Without `--dry-run` it issues one destination `PP SAVE`, closes the session,
opens the destination again and compares every selected field with the source.

`template-reset-defaults` follows the same staging, save and fresh-reload
sequence, using the selected decoded unit specification's defaults as its
template. It resets only the 26 original template-selected parameters. It is
deliberately different from the broad native `reset-defaults` command and does
not claim a device factory reset.

Both operations compare every stable template-excluded value present from
this list before staging and after reload:

```text
CUSTYPE EEPROMChecksumActive EEPROMLevelRecall LearnedFlag NetworkAddress
PatchEnable Project SerialNo State UnitAddress
```

C-Gate schemas can omit some names, so the result records the exact
`preserved_parameters` intersection it checked. The calculated EEPROM checksum
and checksum alarm are not preservation candidates. A dry run closes the PP
session without saving. A confirmed run returns
`cbus-native-unit-template-transaction-v1` evidence including changed fields,
CRC, save and reload state. A lost or interrupted save reply sets
`save_outcome_uncertain=true`; the CLI never retries or opens a verification
session after that uncertain boundary.

`PP SAVE` updates the C-Gate database model. It does not save the enclosing
project file, and the receipt therefore keeps `project_file_saved=false`.
Project-file durability remains a separate operator action. Neither operation
contacts a physical unit because it admits `/db` sources and destinations only.

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
Description is optional file metadata, excluded from the checksum and never
programmed. Original SaveTemplate writes an empty Description. The CLI can
preserve a nonempty single-line Description, which may contain any Unicode
XML character and round-trips through the UTF-8 file. Attribute values stay
ASCII-only, and Toolkit's handling of non-ASCII descriptions is unverified.

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
- Three direct-copy and three template-default transactions across KEY1, KEY2
  and KEY4 against an owned cmqttd C-Gate service. Each used one confirmed PP
  save, a fresh destination session and all eight stable excluded fields
  exposed by that service. The retained result is
  [native-template-transaction-acceptance.json](native-template-transaction-acceptance.json).
- Corrupt checksums, incompatible profiles/schemas, bounds, duplicate fields
  partial writes, unrelated-field changes, uncertain saves and interruption
  identity.

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

The transaction acceptance has its own explicit gate, so it can run against
an owned C-Gate-compatible service without changing the original-server test:

```sh
CBUS_TEMPLATE_TRANSACTION_TEST_HOST=127.0.0.1 \
CBUS_TEMPLATE_TRANSACTION_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=/path/to/unitspec \
CBUS_TEMPLATE_TRANSACTION_REPORT=/tmp/native-template-transaction-acceptance.json \
.venv/bin/python -m pytest \
  tests/test_template_transaction_native.py -q
```

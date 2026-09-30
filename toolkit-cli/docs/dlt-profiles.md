# DLT and eDLT profiles

Status: **in progress** under the `dlt-edlt-widgets-and-labels` ledger row
(work item P6.03). This page describes one profile registry for every Python
DLT/eDLT gate, the classic Saturn/Neo/Decorator label-variant model, and the
sanitized eDLT firmware-package inventory. Database eDLT editors admit every
public KEYGL5 catalogue revision (see [KEYGL5 revisions](#keygl5-revisions));
no other type or catalogue number is added, and nothing here establishes
physical display, label-transfer or firmware behavior.

## Profile registry

`cbus_toolkit.dlt_profiles` replaces the unused `dlt_variant_guard.py`
scaffold. Its facts come from the owned Toolkit 1.18.0.2754 / C-Gate
3.4.0.2001 installation and are retained only as the sanitized receipt
[`research/fixtures/dlt-profile-facts.json`](../research/fixtures/dlt-profile-facts.json):
unit types, catalogue numbers, catalogue revision ranges and flags,
specification names/digests/version bounds, help topic IDs with the unit types
and catalogue names they state, and digests of reviewed Toolkit instruction
ranges. No specification parameter text, help prose or instruction bytes are
committed.

| Unit type | Style | Specification | Catalogue numbers | Catalogue revisions (public) | Help topics |
|---|---|---|---|---|---|
| KEYBL5 | Saturn 5-key DLT | `KEYL5.xml` → `I_DLT.xml` → `I_NEOCORE.xml` | 5085DL | 1.4.00, 2.0.00, 2.1.00 (default), 3.0.00..3.0.99 | 2111, 2500, 4898 |
| KEYML5 | Neo 5-key DLT | `KEYL5.xml` → `I_DLT.xml` → `I_NEOCORE.xml` | 5055DL | 1.4.00, 2.0.00, 2.1.00 (default), 3.0.00..3.0.99 | 2092, 2160, 2506, 4838 |
| KEYDL4 | Decorator 4-key DLT | `KEYL4.xml` → `I_DLT.xml` → `I_NEOCORE.xml` | E5054DL, E5084DL | 2.1.00 (default), 3.0.00..3.0.99 | 2113, 2501, 4825 |
| KEYGL5 | eDLT 5-key | `KEYGL5.xml` | 5055EDL, 5085EDL, 5085EDLB, R5045EDL, R5045EDLW | 1.6.x, 1.7.x, 5.4.x, 5.5.x (default) | 18867, 19689, 19690 |

The remaining catalogue rows are marked `IsInternal`: 1.1, 1.4.01..1.4.16,
2.0.01..2.0.99 and 2.1.01..2.9.99 for the classic types (plus 2.0.00 for
KEYDL4), and 1.5.01..1.5.99 and 5.6.00..9 for KEYGL5. Every catalogue number
of one unit type carries identical revision rows.

Capability flags describe the vendor profile, not CLI support:

| Unit type | Static label text in unit | Dynamic labels | Per-key label variant | eDLT widgets |
|---|---|---|---|---|
| KEYBL5, KEYML5, KEYDL4 | no | yes (group/action variants) | yes (`LabelFlavour`) | no |
| KEYGL5 | yes (64 strings) | yes | no | yes |

### Workflows and admission

Each gate asks `refusal(workflow, unit_type, firmware, catalog_number)` and
receives `None` or an explicit reason.

| Workflow | Identity checked | Admitted | Python gate |
|---|---|---|---|
| `edlt-database-widgets` | type, canonical firmware, catalogue | KEYGL5 / 1.6.00..1.6.99, 1.7.00..1.7.99, 5.4.00..5.4.99, 5.5.00..5.5.99 / 5055EDL | `EdltLighting` (all database eDLT editors), its DBGET identity check and offline export plans |
| `edlt-parent-metadata` | type, exact firmware, catalogue | KEYGL5 / 5.5.00 / 5055EDL | native XML parent/SceneManager metadata |
| `edlt-global-source` | type, exact firmware, catalogue | KEYGL5 / 5.5.00 / 5055EDL | Global Programming / factory source export |
| `edlt-label-clear` | type, exact firmware | KEYGL5 / 5.5.00 | `cgate edlt-label-clear` plan and live guard |
| `edlt-physical-labels` | type, physical firmware | KEYGL5 / 5.5.00 | `cgate edlt-labels`, label audit selection |
| `serial-population` | type | KEYGL5 (with the non-DLT KEYE1 and PC_CNIED) | `cgate serials populate` |
| `classic-dlt-label-variants` | type, exact firmware, optional catalogue | KEYBL5/KEYML5 2.0.00, 2.1.00, 3.0.00..3.0.99; KEYDL4 2.1.00, 3.0.00..3.0.99 | `dlt labels`, `cgate unit ... dlt-labels` |

Physical IDENTIFY firmware accepts one- or two-digit components and is
canonicalized to `M.m.pp` (for example `05.05.00` → `5.5.00`). An exhaustive
test proves the accepted set equals the retired `0?5\.0?5\.0{1,2}` expression.
Database and export identities are exact strings: a range admits only the
canonical `M.m.pp` spelling, so `5.5.0` and `05.05.00` are refused there.

Refusal reasons are explicit, for example:

- other KEYGL5 firmware in a workflow without evidence for it: its catalogue
  revision shares `KEYGL5.xml`, but that workflow's evidence is retained only
  for the listed revisions and it is not extrapolated;
- KEYGL5 internal revisions (1.5.01..1.5.99, 5.6.00..9): C-Gate marks the
  revision `IsInternal`;
- other KEYGL5 catalogue numbers: they share `KEYGL5.xml` with 5055EDL, but
  only 5055EDL evidence is retained;
- classic types in an eDLT workflow: they have no eDLT widgets or
  unit-resident static text;
- classic firmware below 2.0 (for example 1.4.00): below the `I_DLT.xml`
  `MinVersion` that declares the label-variant fields;
- classic internal revisions: C-Gate marks the revision `IsInternal`;
- help-only names and undefined types: see the next section.

Query the registry with `cbus-toolkit dlt profiles`, or one identity with
`cbus-toolkit dlt profiles --unit-type KEYGL5 --firmware 5.5.00 --catalog-number R5045EDL`.

### Catalogue-alias finding

The Toolkit help names the eDLT only as `5505ED, 5085ED, R5045ED` (topics
18867, 19689 and 19690). None of these is a C-Gate catalogue number, and the
help never names **5055EDL**, which is the only eDLT catalogue number with
retained evidence. `5505ED` is not a prefix of any catalogue number. Help
topic 20074 assigns R5045EDL to unit type **KEYH5**, but neither `cbusunits.xml`
nor any decoded specification defines KEYH5; the catalogue maps R5045EDL and
R5045EDLW to KEYGL5. The classic help names `5084DL` and `SLC5055DL` are also
absent; the catalogue uses E5084DL/E5054DL and 5055DL. The registry refuses
help-only names with a reason that lists the real catalogue numbers.

Two specification facts are recorded too: `KEYL5.xml` declares Type `KEYL5`,
which no catalogue revision reports (C-Gate selects it for KEYBL5 and KEYML5),
and `I_DLTF.xml` is a fragment that no specification includes.

### KEYGL5 revisions

The catalogue has six KEYGL5 revision rows for every catalogue number. All of
them select the same `KEYGL5.xml` and C-Gate class `CBusEdlt`:

| Revision | Catalogue flag | Database eDLT editors | Other eDLT workflows |
|---|---|---|---|
| 1.5.01..1.5.99 | `IsInternal` | refused | refused |
| 1.6.00..1.6.99 | public | admitted | refused |
| 1.7.00..1.7.99 | public | admitted | refused |
| 5.4.00..5.4.99 | public | admitted | refused |
| 5.5.00..5.5.99 | public, default | admitted | 5.5.00 only |
| 5.6.00..9 | `IsInternal` | refused | refused |

Layout and handling are identical across the public rows:

- **Specification.** `KEYGL5.xml` (SHA-256 `812d2f92…`) declares `MinVersion`
  0 and `MaxVersion` 9, has no includes and no version-conditional
  parameters, so C-Gate builds one 874-parameter layout for every revision.
- **C-Gate.** The decompiled `CBusEdlt` class never reads a version,
  firmware or revision value.
- **Original eDLT editor.** In the decompiled Toolkit 1.18.0.2754 eDLT editor
  and `CBusLogicModel`, eight source files read unit firmware. None of them
  selects a specification, layout, widget or editor path. The specification
  comes from C-Gate by its catalogue-selected file name. The firmware uses are:
  - `EDLTUnit.FirmwareVersionUnit` returns `n/a` for a database unit.
  - `EDLTUnit.ConfigVersion` rewrites `ConfigVersionMajor/Minor` from the
    firmware only for a network unit, and `BeforeSavePPData` does so only when
    a database unit is saved to the network. A database save keeps the
    `AfterLoadPPData` 1/0 normalization.
  - `FrmBaseUnit` displays the firmware and shows the "Critical Update"
    prompt when a network unit reports firmware older than the 1.7.0 package.
    That comparison is a UI prompt only; it does not map packages to C-Bus
    revisions.
  - `TemplatesDialog` writes the firmware into a template. Template import
    requires a non-empty firmware value but does not compare it.
  - The `CBusBase*` model classes only store the value.
- **Native acceptance.** Owned C-Gate 3.4.0.2001 on loopback created
  synthetic database units KEYGL5 / 5055EDL at 1.6.00, 1.6.99, 1.7.00, 1.7.99,
  5.4.00, 5.4.99, 5.5.00 and 5.5.99. Each unit went through the CLI export,
  offline plan, dry-run and Lighting widget with static label text, then Page
  Control groups 0, 42, 254 and 255, and `PROJECT SAVE/CLOSE/LOAD`. The label
  bytes were read back. The native PP schema, defaults, Lighting changes, Page
  Control changes and final parameters (unit address excluded) hashed
  identically at every revision. The result reports the verified database
  identity. Units at 1.5.01, 1.5.99 and 5.6.00, a 5.4.00 / 5085EDL unit and a
  5.5.1 unit were refused before any write. The receipt is
  [`research/fixtures/edlt-revision-native-acceptance.json`](../research/fixtures/edlt-revision-native-acceptance.json).

Parent metadata, Global Programming source, label clear, factory default and
the physical label read path stay at KEYGL5 5.5.00. They depend on physical
firmware, or have their own evidence at 5.5.00 only. The physical decoder also
requires the observed 5.5.00 configuration bytes.

Reproduce the native receipt and the editor review:

```sh
CBUS_NATIVE_SERVICE_BACKEND=local CBUS_LOCAL_CGATE_VENDOR=/path/to/cgate/app \
CBUS_CGATE_JAVA=/path/to/jdk11/bin/java CBUS_UNITSPEC_DIR=/path/to/decoded/unitspec \
CBUS_EDLT_REVISION_REPORT=research/fixtures/edlt-revision-native-acceptance.json \
PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_edlt_revisions.py -k NativeRevisionTests
CBUS_DLT_VENDOR_ROOT=/path/to/research/vendor PYTHONPATH=src:tests .venv/bin/python -m pytest \
  tests/test_edlt_revisions.py -k OriginalEditorReviewTests
```

### Rust gates

`research/export_dlt_admission.py` writes the registry as
`rust/cbus-cgate/src/dlt_profiles.json`. It also writes 565 exact
decisions to `rust/testdata/vectors/dlt_profile_admission.jsonl`; `--check`
and `tests/test_edlt_revisions.py` fail on drift. `cbus_cgate::dlt_profiles`
embeds the table and ports `refusal`. Its test reproduces every vector,
including the reason text and Python `repr` quoting.

- `LABEL CLEAREDLT` and `DO ... FactoryDefault` in the hardware-backed service
  check the database unit's `UnitType` and `FirmwareVersion` against the
  `edlt-label-clear` workflow, which the Python clear and factory-default
  guards also use. A refusal is `402 Target is not a supported eDLT: <reason>`
  and sends no PCI traffic. `DO FactoryDefault` on a unit type outside the
  `CBusEdlt` class keeps the native `402 Method not supported by object`.
- `NET SYNC` 0xFB/WidgetGroups enrichment, the KEYGL5 `GET`/`SHOW` vendor
  properties and the mock's `FactoryDefault` method follow the native
  `CBusEdlt` class. They ask only whether the type is in the table's eDLT
  family, because native C-Gate performs them for every revision.

## Classic DLT label variants

Classic DLT units keep no label text in unit memory. Label text is project
data: each group or action selector has up to four label variants per
language, delivered as dynamic labels. The unit-resident label configuration is
one variant selection per key slot, stored in bytes `0x60..0x67`:

| Bit(s) | Field | Source |
|---|---|---|
| 0..2 | `IndicatorBlockAssignment` | `I_NEOCORE.xml` |
| 3 | `LabelFlavourLSB` | `I_DLT.xml` |
| 4..5 | `IndicatorFunction` | `I_NEOCORE.xml` |
| 6 | `LabelFlavourMSB` | `I_DLT.xml` |
| 7 | `SceneKeySelector` | `I_NEOCORE.xml` |

The Toolkit exposes each key's **Label Variant** as 1..4. In the pinned
`CBusToolkit.exe`, `TCBusDynamicLabelInputCGateAgent` binds the two PP arrays,
`LoadLabelFlavours` calls `SetLabelFlavour(2*min(MSB,1) + min(LSB,1) + 1)` per
key, and `SaveLabelFlavours` stores `LSB = (variant-1) mod 2` and
`MSB = (variant-1) div 2`. `Get/SetLabelFlavour` add and subtract one. The six
reviewed instruction ranges are identified by address, length and SHA-256 in
the facts receipt.

`cbus_toolkit.dlt_labels.ClassicDltLabels` checks the exact layout in the
loaded specification, reads a complete five-field snapshot, and plans only
`LabelFlavourLSB`/`LabelFlavourMSB`. Each plan records the expected snapshot
for staleness checks and a raw-byte preview whose changed mask may only contain
`0x48`. Apply refuses a different identity or stale values, stages the two
arrays, verifies PP readback and, on a native session, `GET_RAW_DATA` for
bytes `0x60..0x67`. It never retries or restores after a partial PP error.
`EnableDynamicLabels` (byte `0x3E` bit 6, "Allow Dynamic Labelling") is
reported read-only.

```sh
# Offline, from a PP export or native DBGETXML
cbus-toolkit dlt --spec-dir "$CBUS_UNITSPEC_DIR" labels show --file neo.json
cbus-toolkit dlt labels plan --project-xml project.xml --unit //P1/254/p/20 --variant 1=4 --variant 8=2
# Database unit through C-Gate
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 dlt-labels --show
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 --dry-run dlt-labels --variant 3=4
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 dlt-labels --plan plan.json
```

The native command accepts only database destinations. `--dry-run` stages and
verifies without saving.

### Evidence

- Offline: `tests/test_dlt_labels.py`, `tests/test_dlt_profiles.py` and
  `tests/test_cli_dlt.py` use a synthetic literal layout. They cover all four
  variants, slots 1 and 8, invalid slots/variants/duplicates, neighbour-bit
  preservation, stale plans, partial failure, plan round trip, XML input and
  every refusal class.
- Vendor-gated: with `CBUS_UNITSPEC_DIR`, the decoded KEYL5/KEYL4 layouts,
  include order and digests are checked. With `CBUS_TOOLKIT_EXE`, the six
  instruction digests and the compose sequence are checked. With
  `CBUS_DLT_VENDOR_ROOT`, both receipts are re-derived with
  `research/dlt_profile_facts.py --check`.
- Native: owned C-Gate 3.4.0.2001 on loopback created synthetic database units
  KEYBL5 2.1.00/5085DL, KEYML5 2.0.00 and 3.0.99/5055DL, and KEYDL4
  3.0.00/E5084DL and 2.1.00/E5054DL. Nonzero neighbour fields were set, two
  selections covering every variant and both boundary slots were applied, and
  80 raw-byte assertions confirmed that only bits 3 and 6 changed. All other
  PP values were preserved, the DBGETXML projection matched the session, and
  values and raw bytes survived `PP SAVE_TO_SOURCE`, `PROJECT SAVE`, `CLOSE`,
  `LOAD`. KEYBL5 1.4.00, KEYDL4 2.0.00 and KEYML5 2.5.00 were refused without
  writes. The receipt is
  [`research/fixtures/dlt-label-variants-native-acceptance.json`](../research/fixtures/dlt-label-variants-native-acceptance.json).
  The CLI native test repeats show, dry-run, saved-plan apply, stale refusal,
  non-database refusal and KEYBL5 1.4.00/KEYGL5 refusals.

Reproduce the native receipt:

```sh
CBUS_NATIVE_SERVICE_BACKEND=local CBUS_LOCAL_CGATE_VENDOR=/path/to/cgate/app \
CBUS_CGATE_JAVA=/path/to/jdk11/bin/java CBUS_UNITSPEC_DIR=/path/to/decoded/unitspec \
CBUS_DLT_LABEL_REPORT=research/fixtures/dlt-label-variants-native-acceptance.json \
PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_dlt_labels.py -k native
```

### Limits

- Slot numbers are PP array indexes 1..8 (the catalogue declares eight
  inputs). Their mapping to physical keys and pages is not verified.
- Label text, languages, variant contents, dynamic-label transfer and
  `Block Dynamic Updates` are not implemented here; the relationship between
  that checkbox and `EnableDynamicLabels` is not source-verified.
- Other classic dialog tabs, the original Toolkit dialog, physical PP transfer,
  display rendering and power-cycle persistence are unverified.
- Firmware 1.4.00 and internal revisions are refused rather than extrapolated.

## eDLT firmware packages

[`research/fixtures/edlt-firmware-package-facts.json`](../research/fixtures/edlt-firmware-package-facts.json)
records the central directory of the four Toolkit packages without opening,
decompressing or decrypting any entry and without any archive password: zip
size and SHA-256, entry names, compressed and uncompressed sizes, CRC fields,
method, flags, extra-field IDs, DOS timestamps and local-header offsets.

| Package | Entries | Encryption |
|---|---|---|
| 1.3.0, 1.4.0 | font data, `hwv1` main | WinZip AES-256 (AE-2, deflate inside; CRC field zero) |
| 1.5.0 | font data, `hwv1`, `hwv2` main | WinZip AES-256 (AE-2) |
| 1.7.0 | font data, `hwv1`, `hwv2`, `hwv3` main | PKWARE traditional encryption, deflate, CRC present |

Package versions name updater main images. No retained source maps them to
C-Bus IDENTIFY revisions such as 5.5.00, so the receipt marks the mapping
`unmapped` and no eDLT profile is admitted from a package version. Updater
behavior is described in [firmware-research.md](firmware-research.md).

Regenerate both receipts from the owned installation:

```sh
.venv/bin/python research/dlt_profile_facts.py \
  --catalogue /path/to/cgate/app/unitspec/cbusunits.xml --spec-dir /path/to/decoded/unitspec \
  --help-dir /path/to/toolkit-help --toolkit-exe /path/to/CBusToolkit.exe \
  --firmware-dir /path/to/app/Firmware/eDLTFirmware [--check]
```

## Remaining P6.03 work

KEYGL5 catalogue numbers other than 5055EDL, and non-database eDLT workflows
at revisions other than 5.5.00, need their own evidence before admission.
Physical behavior at 1.6.x, 1.7.x and 5.4.x is unverified. The original eDLT
editor was reviewed from source and not executed at those revisions. Classic
DLT key functions beyond label variants, label text and language transfer, the
original classic dialogs, eDLT firmware package-to-revision mapping and all
physical behavior remain open.

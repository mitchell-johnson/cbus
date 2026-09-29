# DLT and eDLT profiles

Status: **in progress** under the `dlt-edlt-widgets-and-labels` ledger row
(work item P6.03). This page describes one profile registry for every Python
DLT/eDLT gate, the classic Saturn/Neo/Decorator label-variant model, and the
sanitized eDLT firmware-package inventory. It does not add eDLT widget support
for any new type, firmware or catalogue number, and it does not establish any
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
receives `None` or an explicit reason. The admitted identities preserve the
earlier behavior exactly.

| Workflow | Identity checked | Admitted | Python gate |
|---|---|---|---|
| `edlt-database-widgets` | type, exact firmware, catalogue | KEYGL5 / 5.5.00 / 5055EDL | `EdltLighting` (all database eDLT editors) and its DBGET identity check |
| `edlt-parent-metadata` | type, exact firmware, catalogue | KEYGL5 / 5.5.00 / 5055EDL | native XML parent/SceneManager metadata |
| `edlt-global-source` | type, exact firmware, catalogue | KEYGL5 / 5.5.00 / 5055EDL | Global Programming / factory source export |
| `edlt-label-clear` | type, exact firmware | KEYGL5 / 5.5.00 | `cgate edlt-label-clear` plan and live guard |
| `edlt-physical-labels` | type, physical firmware | KEYGL5 / 5.5.00 | `cgate edlt-labels`, label audit selection |
| `serial-population` | type | KEYGL5 (with the non-DLT KEYE1 and PC_CNIED) | `cgate serials populate` |
| `classic-dlt-label-variants` | type, exact firmware, optional catalogue | KEYBL5/KEYML5 2.0.00, 2.1.00, 3.0.00..3.0.99; KEYDL4 2.1.00, 3.0.00..3.0.99 | `dlt labels`, `cgate unit ... dlt-labels` |

Physical IDENTIFY firmware accepts one- or two-digit components and is
canonicalized to `M.m.pp` (for example `05.05.00` → `5.5.00`). An exhaustive
test proves the accepted set equals the retired `0?5\.0?5\.0{1,2}` expression.
Database and export identities remain exact strings.

Refusal reasons are explicit, for example:

- other KEYGL5 firmware: its catalogue revision shares `KEYGL5.xml`, but only
  5.5.00 evidence is retained and it is not extrapolated;
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

### Rust gates

`cmqttd` keeps its own type-only KEYGL5 checks (`402 Target is not a supported
eDLT` in `cbus-cgate/src/service.rs` and KEYGL5-only `NET SYNC` enrichment).
They are not routed through this Python registry.

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

Other KEYGL5 revisions and catalogue numbers need their own widget/layout
evidence before admission. Classic DLT key functions beyond label variants,
label text and language transfer, the original classic dialogs, eDLT firmware
package-to-revision mapping, the Rust cmqttd gates and all physical behavior
remain open.

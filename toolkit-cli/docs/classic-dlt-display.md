# Classic DLT display controls

The classic KEYBL5, KEYML5 and KEYDL4 database workflow now supports three
independent original Toolkit controls: indicator mode, display inversion and
clock visibility. It uses the existing admitted classic profile revisions.

| Control | Original PP storage | Load and explicit save |
|---|---|---|
| `indicator_mode` | `IndicatorMode`, byte `0x35`, bits 0..1 | 0 = off, 1 = normal, 2/3 = on; explicitly selecting on saves 2 |
| `invert_display` | `InvertDisplay`, byte `0x35`, bit 4 | Direct boolean |
| `show_clock` | `HideClock`, byte `0x35`, bit 5 | Inverse boolean |

Only requested controls are changed. In particular, an existing raw indicator
mode 3 remains 3 when changing only inversion or clock visibility. This is an
explicit subset edit, not the original complete form's load/save cycle.

## Commands

```sh
cbus-toolkit dlt display show --file neo.json
cbus-toolkit dlt display plan --file neo.json \
  --indicator-mode normal --invert-display no --show-clock yes > display-plan.json
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 \
  dlt-labels --show-display
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 \
  --dry-run dlt-labels --plan display-plan.json
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 \
  dlt-labels --indicator-mode on --invert-display yes --show-clock no
```

Offline show/plan also accepts `--project-xml project.xml --unit
//P1/254/p/20`, or a bare PP mapping with explicit `--unit-type` and
`--firmware`. `--spec-dir` or `CBUS_UNITSPEC_DIR` selects decoded vendor
specifications. Native application uses the existing database-only
`dlt-labels` route. Display edits cannot be combined with variant/dynamic-update
edits or either show mode in one invocation.

The immutable `cbus-classic-dlt-display-plan-v1` plan binds the selected unit
identity and all six named fields sharing byte `0x35`. Apply re-derives the
writes, validates exact value types and the native layout, and refuses stale
PP values. It reads the whole raw byte before and after staged writes to
verify that all unselected bits survived. Failed writes/readback produce an
unsaved partial-operation error without retry or rollback.

## Evidence and persistence boundary

The original executable/map receipt is
[`classic-dlt-display-original.json`](../research/fixtures/classic-dlt-display-original.json).
Its probe executes original load/save fragments, accessors and conversion
methods on synthetic memory with dependency calls intercepted. Original
instruction execution establishes these mappings; it does not execute the
complete GUI or verify a display.

The owned original C-Gate receipt
[`classic-dlt-display-native.json`](../research/fixtures/classic-dlt-display-native.json)
covers five identities: KEYBL5 2.1.00, KEYML5 2.0.00/3.0.99 and KEYDL4
2.1.00/3.0.00. Each stages `FF → EF → EE → CE → FC → CD → CD`, including
omitted raw mode 3, explicit normalization to 2, all control values and a
no-op. Every unselected PP field and raw bit is preserved while staged.
Every named PP field survives PP save and project save/close/load.

Byte `0x35` bit 7 has no PP field in the original specification. Original
C-Gate database persistence drops that artificial sentinel bit: the edited
byte reloads as `4D` instead of `CD`. An independent native control using no
display editor likewise stages `FF` and reloads as `7F`. Consequently,
`raw_bytes_verified` describes the staged PP session before save, as stated
by `raw_verification_scope`; it does not promise persistence of unnamed bits.
Offline raw previews cover only the declared `0x7F` mask.

Run `test_dlt_display.py`, `test_cli_dlt_display.py`,
`test_dlt_display_native.py` and `test_classic_dlt_display_original.py` with
`PYTHONPATH=src:tests:.`. Native tests use the owned local C-Gate settings
described in [classic label controls](classic-dlt-label-controls.md).
`CBUS_DLT_DISPLAY_REPORT` writes a fresh native receipt. The original probe
requires `CBUS_TOOLKIT_EXE` and its adjacent `.map` (or `CBUS_TOOLKIT_MAP`).

Page fallback, pressed-brightness duration and nightlight controls have a
separate [ordered Indicators workflow](classic-dlt-indicators.md). Physical key
and page mapping, rendering, label delivery and power-cycle persistence
remain unverified. The separately retained
[original delivery sequence](classic-dlt-delivery-original.md) explains why
a complete physical label executor needs more than an enable/send/disable
transaction.

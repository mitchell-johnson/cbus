# Differential acceptance plan (Phase 4 scaffolding + two attempted rows)

Phase 4 only: ledger/census inventory plus a differential harness with an
executable slot-flip rubric. No Toolkit parity is claimed. The harness
holds exactly two partially filled rows (`edlt-reset-controls` and
`edlt-retained-scene-editing`, `nominal_workflow` only, 1/6 slots each);
every other slot stays `unassessed`, `accepted_areas` stays 0, and
`complete` stays false.

## Authoritative inputs

- Feature ledger: `../src/cbus_toolkit/capabilities.json` — **38 areas**,
  `census_complete: false`. Statuses (`implemented` / `in_progress` /
  `pending`) describe implementation categories, not Toolkit parity. Two
  acceptance IDs remain `pending`: `toolkit-differential-acceptance` and
  `unit-hardware-acceptance`.
- Status narrative: [implementation-status.md](implementation-status.md) —
  `cbus-toolkit coverage --require-complete` intentionally returns nonzero
  while this work remains; no completion percentage is reported.
- Documentation census: [toolkit-surface.md](toolkit-surface.md) — **3767
  indexed help topics** in 21 branches, **209 public C-Gate command blocks**,
  56 mapped typed-wrapper candidates, **118 configuration-dialog
  candidates**. Topic and command acceptance is `unassessed`; raw forwarding
  and wrapper presence do not establish workflow acceptance.

## Matrix shape

Implemented in `../src/cbus_toolkit/differential.py`:

- One row per ledger area (38 rows), preserving the ledger `status`,
  `limits`, and `evidence` fields verbatim.
- Per row, three workflow slots (`nominal_workflow`, `error_path`,
  `device_firmware_variation`) and three negative-path slots
  (`invalid_input`, `unsupported_profile`, `hardware_divergence`),
  starting at `unassessed` except the two rubric-passed nominal slots
  (`edlt-reset-controls` and `edlt-retained-scene-editing`).
- Per-row `differential_status: pending` (no area meets the all-six-slot
  area rule) and `evidence_paths: []` except the Reset row's seven and
  the SceneManager row's six committed paths.
- Matrix summary: `ledger_areas: 38`, `accepted_areas: 0`,
  `complete: false`, `census_complete: false`.

## Honesty gates

- `tests/test_differential_matrix.py` enumerates all 38 areas x
  workflow/negative slots and asserts the exact state: only
  `edlt-reset-controls` / `nominal_workflow` and
  `edlt-retained-scene-editing` / `nominal_workflow` are `accepted`; all
  other slots are `unassessed`, `accepted_areas` is 0, `complete` is
  false. A dedicated offline test pins each row's hardcoded evidence
  constants against its committed fixtures (Reset: 44 / 520 / 454,480;
  SceneManager: 34 vector cases / 17 original executions / 8 native
  cases).
- `tests/test_coverage_require_complete.py` asserts `coverage
  --require-complete` still exits 1 with `complete: false`.
- The pre-existing `test_cli.py::test_coverage_cannot_claim_completion`
  guard is preserved; no status inflation was made in `cli.py`.
- `capabilities.json` keeps `census_complete: false`; do not flip it until
  the executable-level census and its acceptance mapping are complete.

## Slot-flip rubric (executable, in `differential.py`)

`SLOT_RUBRIC` plus `slot_meets_rubric()` encode the checkable criteria so
the Checker can re-execute every verdict; `build_matrix()` only sets
`accepted` when the rubric passes (fail-safe). Self-referential unit tests
never flip a slot. Area rule (`AREA_ACCEPTANCE_RULE = "all_six_slots"`):
an area counts as accepted iff all six slots are accepted, so a partial
row is progress, not acceptance.

- `nominal_workflow`: ≥10 fresh-or-captured original executions replayed
  by a committed replay test, plus native persistence (save/close/load
  readback) where the workflow saves, plus a committed acceptance record
  with a bounded scope note (profile, tabs/variants, explicit
  non-claims).
- `error_path`: ≥1 original-observed error vectors with exact original
  error identity; own guard tests do not count.
- `device_firmware_variation`: ≥2 distinct unit/firmware profiles with
  original comparisons; a single-profile scope note bounds nominal but
  does not flip this slot.
- `invalid_input` / `unsupported_profile`: exact-rejection evidence
  grounded in original-observed behavior; never absence-of-test.
- `hardware_divergence`: physical-device evidence with exact effect
  identity; loopback native runs and simulators do not count.

## The single attempted row: `edlt-reset-controls` (1/6)

Chosen for the deepest independent original-Toolkit evidence with a
ledger row it can fill 1:1 (bounded KEYGL5 / 5055EDL / 5.5.00 Reset
scope). Rejected candidates, one line each:

- `edlt-restore-levels` (64 captured Windows cases): evidence belongs to
  the `dlt-edlt-widgets-and-labels` mega-row, which one widget subset
  cannot accept; kept for a later per-function mapping.
- Measurement/culture converter (invariant-culture pins): same mega-row
  problem, and culture-specific parsing remains open per
  implementation-status.
- `edlt-corridor` / `edlt-applications` (original vectors): same
  mega-row problem with fewer native reload cases than Reset.
- Thermostat / database-CSV / PCI streams: broad ledger rows with
  native/physical gaps; no 1:1 bounded row available.

Per-slot verdicts (evidence paths are committed artifacts only):

- `nominal_workflow` = `accepted`: 44 captured original executions / 520
  phases / 454,480 comparisons replayed by
  `tests/test_edlt_reset_vectors.py` over
  `research/fixtures/edlt-reset-windows-vectors.json`, plus 4 fresh
  native save/close/load cases per run (`tests/test_edlt_reset_native.py`,
  all 874 fields at ten phases, five CRCs, 274 raw bytes) and the bounded
  acceptance record
  (`research/fixtures/edlt-reset-acceptance.json`, itself declaring
  `toolkit_parity_complete: false`). Scope: 4 tabs × 2 binding variants,
  single profile.
- `error_path` = `unassessed`: no original-observed error vectors; the
  malformed-default original failure is a preserved observation, and our
  guard tests are self-referential.
- `device_firmware_variation` = `unassessed`: single profile only
  (KEYGL5 5.5.00).
- `invalid_input` / `unsupported_profile` = `unassessed`: our rejections
  (unsupported widget types, nav modes, wrong-profile envelopes) are
  scoping guards without original-observed error identity.
- `hardware_divergence` = `unassessed`: `physical_device_verified` is
  false; native runs are closed-loopback databases (`state=new`).

37 rows plus the full census mapping remain outstanding; this row's five
open slots require fresh original/firmware/negative/hardware evidence.

### Offline gate posture (this env)

`tests/test_edlt_reset_vectors.py` (requires the `CBUS_UNITSPEC_DIR`
vendor unitspec) and `tests/test_edlt_reset_native.py` (requires the
`CBUS_WINDOWS_BRIDGE=1` + `CBUS_CGATE_TEST_HOST` + `CBUS_UNITSPEC_DIR` +
`CBUS_TOOLKIT_EXE` Windows bridge + C-Gate + toolkit exe) both SKIP
offline in this env (2 skipped observed). Gate runs here therefore rest on
committed artifacts plus the prior vendor runs recorded in
`research/fixtures/edlt-reset-acceptance.json` — the `runs` array (two
passed runs with per-run `native_cases` / `native_report` / `log` /
`vendor_manifest` / `owned_provenance` records) and the top-level
`run_results` (`path`/`sha256`) pointer plus `captured_original_vectors`
(executions/phases/comparisons) — not on live vendor re-execution.

## The second attempted row: `edlt-retained-scene-editing` (1/6)

Bounded KEYGL5 / 5055EDL / 5.5.00 retained SceneManager scope: the
retained scene-model editor beside the declarative scene-table helper,
with the original SaveScenes 233-token temporary-CRC behavior at exactly
64 items (native PP stores 232 bytes). It fills the
`edlt-retained-scene-editing` ledger row 1:1 and does not claim the
`dlt-edlt-widgets-and-labels` mega-row, full SceneManager panel/form
initialization, new label allocation, or physical behavior.

Numbers verification (both claimed numbers verify against committed
artifacts; nothing assumed):

- "17 fresh original executions": verified. The committed oracle test
  (`OriginalSceneManagerTests::
  test_original_validation_and_retained_control_literals` in
  `tests/test_edlt_scene_manager.py`) executes 13 model-validate cases +
  `get-new-missing-trigger` + 3 bounded actual-control cases
  (baseline/sync/copy-paste) = 17 fresh original Windows model/control
  cases per interpreter, each comparing the full 874-parameter
  `after-original-crc` phase; both module acceptance runs record
  `original_cases: 17`, and `original_research` splits the 34 committed
  vector cases as 10 retained-model + 3 bounded control + 13 validation
  + 8 getter/cache (10+3+13+8 = 34 = `len(cases)`).
- "8 native persistence cases": verified. `NativeSceneManagerTests::
  test_original_full874_raw_crc_save_close_load_and_metadata_preservation`
  runs 8 cases per interpreter (baseline, add-remove, cross-application,
  copy-paste, clear-scene, validate-all-four, get-new-missing-trigger,
  capacity-add at full 64), each with 874 parameters, 5 CRCs, raw-byte
  readback, and save/close/load with `state=new`; both module acceptance
  runs record `native_cases: 8` and `native.cases_per_module_run: 8`.
- Self-limit disclosure: unlike the Reset row, this acceptance record
  carries NO `toolkit_parity_complete` key at all (verified absent, not
  false). The self-limit is expressed instead through
  `physical_device_verified: false`, `full_form_verified: false`, the
  `boundaries` non-claim list (model scope only, no complete panel init,
  no live levels/capture/broadcast/physical programming, no metadata
  creation), `capacity64.native_pp_only_crc_matches_original: false`,
  `partial_edit_persistable: false`, and the preserved-failures record.
  The rubric does not require a parity key, so nominal still passes; the
  absence is disclosed here rather than patched into the fixture.

Per-slot verdicts (evidence paths are committed artifacts only; the
existing rubric is applied unchanged):

- `nominal_workflow` = `accepted`: 17 fresh-or-captured original
  executions (≥10) replayed by committed tests — offline
  `SceneManagerTests` replay the committed vectors with no provisioning,
  and the gated oracle/native tests re-executed them fresh per the
  acceptance record — plus 8 native save/close/load cases per run and
  the bounded acceptance record
  (`research/fixtures/edlt-scene-manager-acceptance.json`, scope:
  KEYGL5/5055EDL 5.5.00 retained model scene editing and database
  persistence, exports review-only; single profile).
- `error_path` = `unassessed`: no original-observed error vectors with
  exact error identity; the `preserved_failures` entries (capacity-64
  CRC, combined validation-probe dispatch) are process observations, not
  replayable original error vectors, and our guard tests are
  self-referential.
- `device_firmware_variation` = `unassessed`: single profile only
  (KEYGL5 5.5.00); the scope note bounds nominal but does not flip this
  slot.
- `invalid_input` / `unsupported_profile` = `unassessed`: our rejections
  (bounds, unknown cache facts, issued-object and profile guards) are
  scoping guards without original-observed rejection identity.
- `hardware_divergence` = `unassessed`: `physical_device_verified` is
  false in both fixtures; native runs are closed-loopback databases.

36 rows plus the full census mapping remain outstanding; these two rows'
ten open slots require fresh original/firmware/negative/hardware
evidence.

### Offline gate posture (this env, SceneManager row)

`NativeSceneManagerTests` (requires `CBUS_UNITSPEC_DIR` +
`CBUS_CGATE_TEST_HOST`), `OriginalSceneManagerTests` (requires
`CBUS_TOOLKIT_EXE` + `CBUS_UNITSPEC_DIR`), and the CLI native test
`test_native_cli_preview_complete64_original_crc_save_close_load_and_guard`
(requires `CBUS_CGATE_TEST_HOST` + `CBUS_UNITSPEC_DIR`) all SKIP offline
in this env. The offline-runnable suites — `SceneManagerTests` (9 tests
replaying the committed original vectors) and `SceneManagerCLITests`
offline tests (4 tests) — run here with no provisioning. Gate runs here
therefore rest on committed artifacts plus the prior vendor runs recorded
in `research/fixtures/edlt-scene-manager-acceptance.json` (two module
runs × 11 tests and two CLI runs × 5 tests, per-run `original_cases` /
`native_cases` / report/log sha256 records, `source_sha256` /
`documentation_sha256` / `vendor_files` pins) — not on live vendor
re-execution.

## Fresh-wheel relationship (scaffolding only)

The full fresh-wheel acceptance run (installed wheel, all native gates)
is not executed in this phase. This harness only records where future
per-area original-Toolkit comparisons and negative-path evidence will
attach. Later phases add vectors, system tests, and evidence paths without
inventing endpoints, credentials, or vendor specifications; reserved
ledger fields stay intact and provisioning-gated skips are reported.

## What Phase 4 does not build

Phases 1–3 and 5–14 are not built here: no protocol/transport/MQTT/C-Gate
behavior changes, no MMI/unravel work, no UI or snapshot semantics, no
factory-prep or specialist-app mocks, and no compatibility-gate changes.

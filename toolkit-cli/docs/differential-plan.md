# Differential acceptance plan (Phase 4 scaffolding + eight attempted rows)

Phase 4 only: ledger/census inventory plus a differential harness with an
executable slot-flip rubric. No Toolkit parity is claimed. The harness
holds exactly eight partially filled rows (`edlt-reset-controls`,
`edlt-retained-scene-editing`, `edlt-global-category-programming`, and
`edlt-scene-live`, `nominal_workflow` only, 1/6 slots each, plus
`thermostat-configuration`, `all-unit-parameter-encoding`,
`preferences-and-update-workflow`, and `toolkit-database-report-export`
audited 0/6 with all slots `unassessed`); every other slot stays
`unassessed`, `accepted_areas` stays 0, and `complete` stays false.

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
  starting at `unassessed` except the four rubric-passed nominal slots
  (`edlt-reset-controls`, `edlt-retained-scene-editing`,
  `edlt-global-category-programming`, and `edlt-scene-live`). The
  fourth attempted row (`thermostat-configuration`), the fifth attempted
  row
  (`all-unit-parameter-encoding`), the sixth attempted row
  (`preferences-and-update-workflow`), and the seventh attempted row
  (`toolkit-database-report-export`) are each audited 0/6: all six slots
  stay `unassessed` because their evidence does not meet the rubric.
- Per-row `differential_status: pending` (no area meets the all-six-slot
  area rule) and `evidence_paths: []` except the Reset row's seven, the
  SceneManager row's six, the GlobalProgramming row's seven, the
  Thermostat row's thirty-one, the AllUnitParameterEncoding row's six,
  the PreferencesUpdate row's sixteen, the DatabaseReportExport row's
  twenty-two, and the SceneLive row's six committed paths.
- Matrix summary: `ledger_areas: 38`, `accepted_areas: 0`,
  `complete: false`, `census_complete: false`.

## Honesty gates

- `tests/test_differential_matrix.py` enumerates all 38 areas x
  workflow/negative slots and asserts the exact state: only
  `edlt-reset-controls` / `nominal_workflow`,
  `edlt-retained-scene-editing` / `nominal_workflow`,
  `edlt-global-category-programming` / `nominal_workflow`, and
  `edlt-scene-live` / `nominal_workflow` are `accepted`;
  `thermostat-configuration`, `all-unit-parameter-encoding`,
  `preferences-and-update-workflow`, and `toolkit-database-report-export`
  are each 0/6 (all `unassessed`); all other slots
  are `unassessed`, `accepted_areas` is 0, `complete` is
  false. A dedicated offline test pins each row's hardcoded evidence
  constants against its committed fixtures (SceneLive: 14 vector cases
  / 14 original executions x 874 parameters / 17 tests per run with 0
  skips / 9 + 75-test regressions; Reset: 44 / 520 / 454,480;
  SceneManager: 34 vector cases / 17 original executions / 8 native
  cases; GlobalProgramming: 32 matrix vectors / 2 reversed / 2 sequential
  / 36 module + 2 CLI native targets per run; Thermostat: 14 methods /
  28,840 fresh-original cases / 28 pilot + 1,176 full Windows cases /
  14 inner outcomes / 12 + 12 outer captures / 12 AfterLoad outcomes with
  71,832 instruction entries / 2 composition native tests with one target
  save each; AllUnitParameterEncoding: 6,497 selected / 6,487 verified
  (6,382 pass + 105 vendor-catalogue-rejected = 6,487; 10 command-limited
  excluded, 6,487 + 10 = 6,497 selected) /
  616,722 comparisons (552,391 + 64,331) / 163 layouts with 161 pass + 2
  unexercised / 322 change trials, and 0 original-Toolkit executions;
  PreferencesUpdate: 12 original leaves + 12 witnesses / 47 records /
  11 supported + 1 excluded observations with 0 replayed calls / 107
  Int32 observations (76 + 31) / 2 runs x 78 tests / 0 replayed
  conditions rows vs 279 arms / 94 expanded tests with 21 Windows cases /
  36 updates menu + 20 captured + 2 TLS / 51 About instruction cases /
  7 live observations with 108 host + 113 CLI tests, and 0 row-level
  original-Toolkit executions; DatabaseReportExport: 88 serializer
  vectors (73 row + 15 quote; 70 + 13 replayed offline per execution) /
  12 projector outcomes per execution (10 completed + 2 provider stops)
  / 8 backend original cases (16 invocations, 37,933 entries) + 4
  native captures (473 inputs unchanged) + successor replay of all
  four through 8 invocations / 27,661 entries (B03 created exactly one
  group at address 13, "Group 13") / B03 owned C-Gate apply (42
  focused + 1 owned test: backup, Group 13 create, save, reload, 0 CNI,
  no physical) / 2 live protocol cases without mutation / 26 columns
  with 15 selection methods (53 host + 2 owned Windows) + ACP encoding
  (56 core + 3 owned Windows), and GRENACHE sweeps (22 KEYE / 4 DIN /
  1 sensor) excluded as site-dependent with raw snapshots uncommitted).
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

That sentence records the boundary of the frozen acceptance run summarized
below. A later additive implementation now supports ordered static scene-name
allocation by reusing the separately original-tested whole-unit allocator.
Its focused and environment-gated native tests are documented in
`docs/edlt-scene-manager.md`; the historical execution counts and fixture
hashes below are unchanged, and there is still no new SceneManager WinForms
label-control or physical-display acceptance.

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
in this env. The current offline-runnable suites — `SceneManagerTests` (12
tests, including three additive name-allocation cases),
`SceneManagerCLITests` offline tests (6 tests) and the 12-test shared static
allocator suite — run here with no provisioning. Gate runs here therefore
rest on committed artifacts plus the prior vendor runs recorded
in `research/fixtures/edlt-scene-manager-acceptance.json` (two module
runs × 11 tests and two CLI runs × 5 tests, per-run `original_cases` /
`native_cases` / report/log sha256 records, `source_sha256` /
`documentation_sha256` / `vendor_files` pins) — not on live vendor
re-execution.

## The third attempted row: `edlt-global-category-programming` (1/6)

Bounded KEYGL5 / 5055EDL / 5.5.00 prepared-model category-payload scope
for existing closed database units only: selected Toolkit categories are
copied with source OverallCRC plus zero GlobalParameterCRC while
destination WidgetsCRC / StaticTextCRC / ScenesCheckSum are retained. It
fills the `edlt-global-category-programming` ledger row 1:1 (row id
verified present in `capabilities.json`) and does not claim the factory
Reset/Project preparation checkpoint, the full-form Project preamble,
missing-target creation, label transfer, destination full-image CRC
validity, or physical behavior.

Numbers verification (every claimed number verified against committed
artifacts; nothing assumed):

- "All 16 masks match original vectors": verified. The committed vectors
  file holds 16 masks (0-15) in each of 2 full-874 source contexts
  (`defaults-loaded-fixture`, `retained-lighting-scene-mra`) = 32 matrix
  vectors, plus 2 reversed-input-order vectors (masks 0/15) plus 2
  retained sequential payloads; the committed offline test replays all 32
  masks per execution (full source phases, ordered payload, zero
  GlobalParameterCRC) plus both supplements with no provisioning.
- "Final 28 tests pass both Python with 38 saved/closed/loaded targets
  per version": verified. Both per-version entries in the acceptance
  record show 28 tests / 0 skips with 36 native-module targets plus 2
  native CLI targets (36 + 2 = 38), 874 parameters, 39 shared raw bytes,
  and 10 CRC raw bytes per target. (The ledger's "five CRC raw bytes"
  shorthand reconciles as five CRC parameters x 2 bytes = 10 raw bytes.)
- "Historical 40-case original matrix, reversed-order + peer supplements,
  74 prior native transactions": verified. The acceptance record's
  historical section shows a 40-case original matrix (39 save calls: 36
  true incl. 1 true-with-rejected-PP-SET, 3 false), a 2-case reversed
  supplement, a 2-case peer supplement (`original_model_executed:
  false`), and 74 prior native transactions (per-version split recorded
  in gitignored run reports, unverifiable offline). A small set of
  original-only failure/creation cases remain unreplayed and explicitly
  separated.
- "77-test checkpoint" and "six captured factory source patterns":
  verified but NOT claimed by this row. The separate factory acceptance
  record shows 77 tests on both Pythons and exactly six accepted whole
  source patterns (`default-like`, `rich-scene`, `first-mra`, `enable`,
  `mixed-controls`, `fallback127`), with factory-worker masks 0/15
  directly verified. Those belong to the factory preparation checkpoint;
  this row claims only the category-programming nominal slot.
- Self-limit disclosure: like the SceneManager row, this acceptance
  record carries NO `toolkit_parity_complete` key at all (verified
  absent, not false). The self-limit is expressed instead through
  `physical_device_verified: false`,
  `destination_full_crc_validity_verified: false`,
  `export_is_review_only: true`, the `limits` non-claim list (no full-form
  preamble, no destination full-image CRC validity, no proven global
  session exclusivity, non-atomic batches), and the unreplayed-case
  separation. The rubric does not require a parity key, so nominal still
  passes; the absence is disclosed here rather than patched into the
  fixture.

Per-slot verdicts (evidence paths are committed artifacts only; the
existing rubric is applied unchanged):

- `nominal_workflow` = `accepted`: 32 original matrix executions (>=10)
  replayed by committed offline tests (all-masks payload test over both
  source contexts, plus reversed-order and sequential supplements), plus
  36 native-module + 2 CLI save/close/load targets per run and the
  bounded acceptance record
  (`research/fixtures/edlt-global-programming-acceptance.json`, scope:
  KEYGL5/5055EDL 5.5.00 prepared-model category payloads, exports
  review-only; single profile).
- `error_path` = `unassessed`: the 7 `negative_results` entries (with
  original per-phase counts) are preserved observations, not replayed
  original error-identity vectors -- the one committed test reading a
  negative entry (`pp-set-rejected`) asserts only fixture fields and is
  self-referential. The trim-prose rubric enforces only
  the error count, so the count is recorded as 0 (as the Reset row does
  for its preserved observation); the identity keys the trim removed are
  not re-added, and the slot is left unassessed with this note.
- `device_firmware_variation` = `unassessed`: single profile only
  (KEYGL5 5.5.00); the scope note bounds nominal but does not flip this
  slot.
- `invalid_input` / `unsupported_profile` = `unassessed`: our rejections
  (duplicate keys, non-finite numbers, category/metadata guards, exact
  raw-source spelling) are scoping guards without original-observed
  rejection identity.
- `hardware_divergence` = `unassessed`: `physical_device_verified` is
  false in both fixtures; native runs are closed-loopback databases with
  no physical commands.

34 rows plus the full census mapping remain outstanding after the fourth
row below; all four rows' twenty-one open slots require fresh
original/firmware/negative/hardware evidence (final tally at the end of
the thermostat row).

### Offline gate posture (this env, GlobalProgramming row)

`NativeGlobalAcceptanceTests::
test_all_masks_source_contexts_order_full_pp_metadata_backup_and_native_reload`
(requires `CBUS_CGATE_TEST_HOST` + `CBUS_UNITSPEC_DIR`) and the CLI native
test `test_native_cli_two_targets_preview_backup_full_reload_and_source_preservation`
(requires `CBUS_CGATE_TEST_HOST`; the CLI suite itself requires
`CBUS_UNITSPEC_DIR` at class setup) all SKIP offline in this env. The
offline-runnable suites -- all 8 `GlobalProgrammingTests` (committed
hash-pinned vector replay incl. guards) and the offline
`NativeGlobalFailureTests` (mocked clients, self-referential) -- run here
with no provisioning. Gate runs here therefore rest on committed
  artifacts plus the prior vendor runs recorded in
  `research/fixtures/edlt-global-programming-acceptance.json` (two
  per-version entries x 28 tests, per-run report/log/native-report sha256
  records, `source_sha256` pins) -- not on live vendor re-execution.

  ## The fourth attempted row: `thermostat-configuration` (0/6)

  Broad row: fourteen scalar temperature conversions plus the retained
  inner CreateLevels model, the outer scheduling API/CLI, the offline
  unit-load planner/CLI, and the native unit-to-level composition
  manager/CLI. Row id verified present in `capabilities.json`. The
  rubric is applied UNCHANGED and decides against a flip: a 0/6 verdict
  with documented gaps is the honest success here, not a failure. No
  bounded-scope acceptance record spans the full claimed scope, and the
  >=10-original leg and the native-persistence legs belong to different
  sub-scopes that cannot be stitched into a nominal pass.

  Numbers verification (every claimed number verified against committed
  artifacts; nothing assumed):

  - "28,840 fresh original comparisons per run": verified. The committed
    temperature vectors hold 14 methods, 28,840 extended-emulator rows
    and 1,176 native-Windows rows (`source_reports`: emulator cases
    28,840; Windows pilot 28 / full 1,176); the acceptance record shows
    `original_methods` 14, `fresh_original_cases_per_python` 28,840, 17
    tests per Python. The scope note explicitly claims NO scheduling,
    database save/load, or physical device -- the conversion workflow
    performs no native persistence by design. FRESH original runs (not
    replayed vectors): the gated `OriginalThermostatTests::
    test_all_28840_fresh_original_instruction_cases` (requires
    `CBUS_TOOLKIT_EXE`) executes them fresh; the offline
    `test_thermostat_temperature.py` replays the committed vectors.
  - "14 captured inner outcomes, no fresh original or native execution":
    verified. The levels acceptance fixture records
    `captured_original_cases_compared` 14, `fresh_original_executions` 0,
    `native_storage_or_vm_called` false on both Pythons; the vectors file
    holds 14 cases. Scope: retained model with supplied save-callback
    boundaries only.
  - "12 predicate + 12 outer workflows; 12 AfterLoad outcomes (71,832
    instruction entries)": verified. The selection vectors hold 12 cases
    (`original_cases` 12), the outer vectors hold 12 cases, the
    unit-load vectors hold 12 cases (L01-L12), and the committed
    unit-load analysis records `cases` 12 with
    `original_instruction_entries` 71,832. The supplied-state CLI
    performs no native writes; the load planner performs no native
    read/save.
  - "67-combined checkpoint (retained core + 5 integration methods / 8
    scenarios + CLI + backup/save/reload)": verified per the native
    acceptance fixture's two runs (67 tests each, 5 native methods, 8
    scenarios, owned C-Gate, zero CNI). That checkpoint replays captured
    cases with no fresh original execution, and its scope is the
    scheduling core/adapter/CLI -- not temperature, outer, load, or the
    full dialog.
  - "14-test host layer, exactly one target save, 2 fresh owned C-Gate
    3.4.0.2001 integrations": verified. The composition review records
    14 composition tests (8 manager + 6 CLI) and
    `new_original_instruction_execution` false; the composition
    acceptance records `tests_run` 2 with `target_project_save_count` 1
    per case (manager: application 203 + 3 groups + 93 levels; CLI: 31
    levels + read-only no-op). Its `not_claimed` list (inherited
    loader/service factories, collection-order equivalence, remaining
    settings, physical) matches the ledger limits.
  - Self-limit reconciliation: "no native writes/physical" applies to
    the outer/levels/load sub-areas; "exactly one target save" applies
    only to the narrow composition scope (one project/unit XML snapshot,
    PC_TSA 4.6). Inherited loading, original service factories,
    collection-order equivalence, complete settings, and physical
    behavior remain open everywhere per the ledger limits.

  Per-slot verdicts (evidence paths are committed artifacts only; the
  existing rubric is applied unchanged):

  - `nominal_workflow` = `unassessed`: the only >=10 fresh-original leg
    (temperature, 28,840) has no native persistence by design, and no
    single bounded-scope acceptance record spans the row's full
    conversions + levels + outer + load + composition + native-CLI
    scope -- each record explicitly disclaims the other sub-areas. The
    rubric's nominal gate therefore reports `missing rubric requirement:
    has_native_persistence` (row-level flags recorded False).
  - `error_path` = `unassessed`: no original-observed error vectors with
    exact error identity. The levels denial stops, outer injected
    partial failures, and the preserved trace-only AfterLoad harness
    collision are process observations, not replayable original error
    vectors; guard tests are self-referential.
  - `device_firmware_variation` = `unassessed`: single profile only
    (Toolkit 1.18.0 / C-Gate 3.4.0.2001 / one snapshot family).
  - `invalid_input` / `unsupported_profile` = `unassessed`: input guards
    (Int32/boolean/unit checks, address/tag bounds, plan-tampering
    checks) are scoping guards without original-observed rejection
    identity.
  - `hardware_divergence` = `unassessed`: no physical-device evidence;
    native runs are owned loopback C-Gate processes with CNI sentinels,
    and the emulator/Windows runs execute arithmetic only.

  34 rows plus the full census mapping remain outstanding after the fifth
  row below; all five rows' twenty-seven open slots require fresh
  original/firmware/negative/hardware evidence (final tally at the end of
  the all-unit-parameter-encoding row).

  ### Offline gate posture (this env, Thermostat row)

  `OriginalThermostatTests::
  test_all_28840_fresh_original_instruction_cases` (requires
  `CBUS_TOOLKIT_EXE`), the five `NativeScheduleIntegrationTests` methods
  and both `NativeThermostatSchedulingIntegrationTests` methods (require
  Java 11 + vendor C-Gate provisioning) all SKIP offline in this env (8
  skips observed across the thermostat area suites). The offline-runnable
  suites -- temperature replay (6), temperature CLI (4), levels replay
  (17), scheduling model (20), scheduling CLI (12), unit-load (5) -- run
  here with no provisioning. Gate runs here therefore rest on committed
  artifacts plus the prior runs recorded in the acceptance fixtures --
  not on live vendor re-execution.

  ## The fifth attempted row: `all-unit-parameter-encoding` (0/6)

  Row id verified present in `capabilities.json`. The rubric is applied
  UNCHANGED and decides against a flip: a 0/6 verdict with documented
  gaps is the honest success here, not a failure. This audit adds new
  documented understanding the thermostat 0/6 did not cover: the
  native-oracle evidence-kind finding (see the rubric-gap note below).
  Scale does not convert evidence kinds -- 616,722 successful native
  comparisons still contribute zero original-Toolkit executions.

  ### Row-5 candidate survey (rubric applied unchanged; all fail nominal)

  For each candidate the counts below were verified against committed
  artifacts; nothing assumed. Strict rule throughout: documentation
  tables, executable constants, and native-only comparisons are NOT
  original executions.

  - `classic-key-presets` (18 presets; `docs/macros.md`;
    `tests/test_macros.py`): FAILS nominal. 18 presets verified
    (`PRESETS` holds all 18 names; `VECTORS` in `test_macros.py` holds
    the matching 18 stage tuples). The "original Toolkit help tables"
    leg is documentation: `VendorHelpTests` parses help HTML files
    (gated on `CBUS_TOOLKIT_HELP_DIR`) -- tables, not executions. The
    "executable registration constants" leg is static bytes:
    `VendorBinaryTests` compares PE slices at fixed virtual addresses
    (gated on `CBUS_TOOLKIT_EXE`) -- constants, not executions. The
    native leg (`NativeMacroTests`: all 18 presets on KEY4 1.2.67 plus
    KEY1/KEY2 spot checks with database save/reload, gated on
    `CBUS_CGATE_TEST_HOST` + `CBUS_UNITSPEC_DIR`) is native-only with no
    original-Toolkit oracle. Original executions: 0. Native persistence
    exists but the >=10-original leg is absent, so nominal stays
    `unassessed`.
  - `firmware-update` DFU: FAILS nominal. `docs/dfu-protocol.md` records
    44 scripted original-control cases + 12 image-reader vectors + 1
    original suffix-writer vector + 4 `dfuprog` wrapper vectors + 2
    independent program/verify/erase/check workflows + 1 deliberately
    corrupted readback (`docs/dfu-acceptance-summary.json`: 21 focused
    tests pass, gated on `CBUS_DFU_DLL`), all executed by the ORIGINAL
    x86 DLL against a synthetic memory peer. Which counts:
    `dfu-protocol.md` contributes the original-DLL executions above;
    `dfu-transport.md` adds 12 original `DeviceOpen` executions against
    fake USB descriptors plus 15 retained Python-client outcomes (29
    focused tests, fake peer only); `usb-dfu.md` contributes ZERO
    original executions (25 focused tests use real PyUSB 1.3.1 with an
    independent fake backend -- claimed-lease mechanics, no vendor
    binary). Native persistence = synthetic/fake only: the peer is
    `DFUSimulator` flash memory, there is no database save/close/load
    readback anywhere in the DFU path, and no physical device or vendor
    firmware payload was ever accessed (all three acceptance summaries
    state this). The workflow that "saves" here programs emulator RAM,
    not a native database, so the rubric's native-persistence leg is
    unsatisfied and nominal stays `unassessed`.
  - `sensors-wizard-semantics` (40 native event cases): FAILS nominal.
    40 cases verified (5 events x 8 virtual keys in
    `SensorNativeTest::test_all_events_raw_masks_timer_threshold_and_save_reload`,
    gated on `CBUS_CGATE_TEST_HOST` + `CBUS_UNITSPEC_DIR`) with 210
    raw-byte assertions and an explicit database save/reload
    (`docs/sensor-acceptance-summary.json`: `event_key_cases` 40,
    `raw_byte_assertions` 210, `save_reload_passed` true, scope bounded
    to "Toolkit source-grounded sensor setup through native PP and a
    closed database; no physical PIR/lux behavior",
    `physical_hardware_verified` false). The original-evidence leg
    (`SensorSourceTest`, gated on `CBUS_TOOLKIT_HELP_DIR` +
    `CBUS_TOOLKIT_EXE`) reads help topics 307/305/1000/11177 plus
    event-function tables 10114/10115/17328/10116 and checks EXE bytes
    at fixed virtual addresses -- documentation tables and executable
    constants, not executions. Original executions: 0. The acceptance
    record, bounded scope note, and native persistence legs are all
    present, but the >=10-original leg is absent, so nominal stays
    `unassessed`.
  - `all-unit-parameter-encoding` (6,487/6,497 vs C-Gate, 616,722
    comparisons): FAILS nominal under the unchanged rubric -- and is
    therefore chosen as the fifth audit row for the rubric-gap finding
    below. 6,497 selected / 6,487 verified / 616,722 comparisons
    verified (`docs/catalog-acceptance-summary.json`:
    `combined_boundary_workflows` selected 6497, verified_cases 6487,
    successful_parameter_comparisons 616722 = 552391 boundary_workflow +
    64331 boundary_alternative; per-run split pass 6382 +
    vendor_catalog_rejected 105 + vendor_command_limitation 10, with
    6382 + 105 = 6487). 161 of 163 layouts verified
    (`docs/native-memory-acceptance.json`: distinct_layouts 163,
    summary pass 161 / unexercised 2 / passing_change_trials 322; the 2
    unexercised layouts are single-bit little-endian DLT
    LabelFlavourLSB/MSB with no native token-addressable parameter
    name). But every comparison is OUR codec vs NATIVE C-Gate -- a
    native oracle, not replayed original-Toolkit executions. Original
    executions: 0. The 105 + 10 native rejection classes are preserved
    native-oracle observations, not replayed original error-identity
    vectors.

  Numbers verification (every claimed number verified against committed
  artifacts; nothing assumed):

  - "6,497 selected / 6,487 verified / 616,722 comparisons": verified.
    `combined_boundary_workflows` shows selected 6497, verified_cases
    6487, excluded_cases 10, successful_parameter_comparisons 616722;
    the per-run `boundary_workflow` shows selected/completed 6497 with
    pass 6382 + vendor_catalog_rejected 105 + vendor_command_limitation
    10 (6382 + 105 = 6487; 6382 + 105 + 10 = 6497) and 552391
    comparisons; `boundary_alternative_database_load` adds 64331
    (552391 + 64331 = 616722). The record's `does_not_establish` list
    (physical device programming, all firmware values between
    endpoints, all possible parameter values, all Toolkit workflows,
    100 percent Toolkit parity) bounds the claim.
  - "161 of 163 layouts, 322 change trials": verified.
    `docs/native-memory-acceptance.json` (format
    cbus-native-memory-acceptance-v1) shows distinct_layouts 163 with
    163 cases, summary pass 161 / unexercised 2 / passing_change_trials
    322. Scope: "Changing-value differential acceptance of distinct
    logical memory layouts; not per-device, firmware or Toolkit
    workflow parity."
  - Self-limit reconciliation: the catalogue scope ("Offline native
    unit schema and Python session acceptance at selected catalogue
    firmware points") plus the memory scope above plus the catalogue
    `does_not_establish` list jointly bound the area claim to
    native-oracle encoding -- never to Toolkit-workflow parity. The two
    records belong to the SAME ledger-area scope (unlike the
    thermostat row's disjoint sub-scopes), so the row-level
    `has_acceptance_record` / `has_bounded_scope_note` are True; the
    failure is isolated to the original-executions leg, which is the
    point of the audit.

  Per-slot verdicts (evidence paths are committed artifacts only; the
  existing rubric is applied unchanged):

  - `nominal_workflow` = `unassessed`: 0 original-Toolkit executions
    (need >=10). The rubric's nominal gate therefore reports `only 0
    original executions, need >=10`. No committed test replays
    original-Toolkit executions (`research/verify_catalog.py` is a
    gated native-oracle runner; the offline unit/memory tests replay
    committed native-oracle vectors or check our own codec), and there
    is no database save/close/load readback in this path (native PP
    sessions are transient programming contexts, not persistence), so
    the row-level `has_replay_test` / `has_native_persistence` are
    False.
  - `error_path` = `unassessed`: no original-observed error vectors with
    exact error identity. The 105 vendor-catalogue-rejected and 10
    vendor-command-limited classes are preserved native-oracle
    observations, not replayable original error vectors; guard tests
    are self-referential.
  - `device_firmware_variation` = `unassessed`: hundreds of catalogue
    profiles were exercised against native C-Gate, but zero profiles
    carry original-Toolkit comparisons, so `distinct_profiles` is
    recorded as 0 (need >=2 with original comparisons per profile).
  - `invalid_input` / `unsupported_profile` = `unassessed`: codec
    guards are scoping checks without original-observed rejection
    identity.
  - `hardware_divergence` = `unassessed`: no physical-device evidence;
    native runs are loopback C-Gate processes and the memory trials are
    host-side codec comparisons.

  ### Rubric-gap finding (proposed, NOT implemented)

  The rubric as encoded (`SLOT_RUBRIC` + `slot_meets_rubric()`) can only
  express ORIGINAL-Toolkit-oracle evidence: its nominal gate counts
  `original_executions` and nothing else satisfies that leg. It has no
  vocabulary for NATIVE-oracle differential evidence -- large-scale
  agreement between our implementation and live native C-Gate behavior
  with no original Toolkit in the loop. The 616,722-comparison corpus
  is the strongest evidence in the repo by volume and still scores
  exactly 0/6, indistinguishable from "no evidence at all". That
  indistinguishability is the gap: a future rubric revision could add a
  SEPARATE native-oracle slot family (e.g. `native_oracle_agreement`
  with minimum-comparison, layout-coverage, and bounded-scope gates)
  that records this evidence kind WITHOUT weakening the existing
  original-Toolkit gates -- no current `accepted` may flip as a side
  effect. This proposal is documented here for the Checker; no rubric
  key, gate, or verdict was changed to fit the candidate.

  33 rows plus the full census mapping remain outstanding after the sixth
  row below; all six rows' thirty-three open slots require fresh
  original/firmware/negative/hardware evidence (final tally at the end of
  the preferences-and-update-workflow row).

  ### Offline gate posture (this env, AllUnitParameterEncoding row)

  `NativeMemoryTests` (requires `CBUS_CGATE_TEST_HOST` +
  `CBUS_UNITSPEC_DIR`) and `VendorLayoutTests` (requires
  `CBUS_UNITSPEC_DIR`) plus the `research/verify_catalog.py` runner
  (requires a live native C-Gate) all SKIP offline in this env. The
  offline-runnable suites -- `MemoryImageTests`, `MemoryCodecTests`,
  and `UnitSpecTest` -- run here with no provisioning. Gate runs here
  therefore rest on committed artifacts plus the prior native runs
  recorded in `docs/catalog-acceptance-summary.json` (boundary_workflow
  selected/completed 6497, status complete) and
  `docs/native-memory-acceptance.json` (163 cases, 161 pass) -- not on
  live native re-execution.

  ## The sixth attempted row: `preferences-and-update-workflow` (0/6)

  Row id verified present in `capabilities.json` (line 528). The rubric
  is applied UNCHANGED and decides against a flip: a 0/6 verdict with
  documented gaps is the honest success here, not a failure. This is the
  broadest attempted row (40 preference definitions + 5 displays + 19
  OK-handler edits + numeric + preview/reset + updates + metadata +
  revocation + conditions + registry + live observation + About), and it
  fails nominal on three independent legs at once -- zero replayed
  original calls, a persistence-kind mismatch, and no single bounded
  record. CAUTION observed: the sub-scope legs below must NOT be stitched
  into a row-level pass (thermostat row-4 precedent: distinct bounded
  scopes cannot be combined).

  Replayed-vs-observed reconciliation (read before claiming anything):

  - `original_registry` (in
    `research/fixtures/toolkit-update-registry-conditions-acceptance.json`):
    12 original leaf calls + 12 same-provider witness calls + 47 raw
    ordered records + 11 supported observations + 1 excluded collation
    observation, BUT `replayed_original_calls: 0`. "Replayed 0" means the
    12 leaves were OBSERVED once by original Windows-pilot research
    (external `/Volumes/external` paths only, never committed) and their
    outcomes committed to
    `research/fixtures/toolkit-update-registry-conditions-vectors.json`;
    no committed test re-executes original-Toolkit registry calls. The
    `runs` (2: Python 313 + 310, 78 tests each, 0 failures/errors/skips)
    execute OUR suite against supplied facts and committed vectors --
    self-referential checks plus committed-vector replay, never fresh
    original-Toolkit executions. Which tests replay vs observe: the
    registry/conditions suites carry NO vendor gate precisely because
    they never touch the original (all offline); the fresh-original
    probes (updates 36 menu cases via `OriginalUpdateMenuTests`, About 51
    instruction cases, numeric/reset probes) are gated on
    `CBUS_TOOLKIT_EXE`/vendor paths and SKIP offline; the Windows
    scratch-registry runs (21 cases per expanded run: 13 preference + 8
    reset, owned namespaces removed) and the 7 LocalSystem worker
    observations are Windows-gated. Nothing committed replays
    original-Toolkit executions, so the rubric's >=10-REPLAYED leg
    records 0.
  - `original_int32` (107 compared each Python: 76 booleans + 31 errors):
    observational comparisons recorded in the acceptance fixture (matching
    the conditions record's 107 research-only Int32 arms), not replayed
    executions. The conditions acceptance likewise records
    `replayed_original_rows: 0` against 279 production stage arms (386
    retained / 364 unique / 106 processes).
  - Sub-scope legs that must NOT be stitched: store 40 matrix + 38
    display + 2 key captured cases replayed offline by
    `PreferenceStoreTests` (but the store scope is explicitly "no OS
    registry or GUI effects"); updates 36 fresh menu + 20 captured + 2
    owned loopback TLS per run (vendor-gated fresh leg in a separate
    SESU-candidate scope that disclaims availability); About 51 formula
    vectors replayed offline plus a gated fresh probe (text-formula scope
    with no persistence by design); metadata 52 canonical + 28 lifetime
    + 7 captured signatures (offline diagnostics scope, key untrusted);
    revocation 53 tests (offline signed-metadata scope, no trust
    decision); live 7 typed LocalSystem HKCU observations with 108 host
    + 113 CLI focused tests (system-context scope with
    `user_context_parity_verified: false`). Each leg lives in a different
    bounded scope than the others.

  Persistence-leg judgment (explicit, no silent stretch): the rubric's
  native-persistence leg requires DATABASE save/close/load readback. This
  row's workflow persistence is Windows-HKCU registry load/save (scratch
  namespaces with independent reload) -- a different persistence KIND
  than a C-Bus project database, exactly as native PP sessions were
  judged transient rather than persistence in row 5. Counting HKCU as the
  database leg would stretch the rubric silently to fit the candidate, so
  row-level `has_native_persistence` is False. The verdict is
  over-determined: even a generous reading still fails on the 0-replayed
  leg and the no-single-record leg.

  Classification of the remaining evidence: preference
  store/controls/numeric/preview/reset suites = committed-vector replay
  (offline, no vendor) + Windows-gated scratch-registry runs (native
  HKCU, not C-Bus DB) + vendor-gated fresh probes (skip offline);
  `toolkit-preferences-acceptance.json` family = bounded fragment scopes,
  none spanning the row; live observation (7 Windows observations,
  `toolkit-live-registry-observation.md`) = native-run in system context,
  explicitly not user-context parity and not an original comparison;
  About/metadata/revocation/conditions suites = offline diagnostics +
  captured-vector replay (self-referential alone for rubric purposes) with
  vendor-gated fresh probes.

  Numbers verification (every claimed number verified against committed
  artifacts; nothing assumed):

  - "12 + 12 / 47 / 11 + 1 / replayed 0": verified. `original_registry`
    shows `original_leaf_calls` 12,
    `separate_same_provider_witness_calls` 12, `raw_ordered_records` 47,
    `observed_booleans` 10 + `observed_expected_errors` 2 (12 outcomes),
    `supported_leaf_observations_each_python` 11,
    `excluded_original_collation_observations` 1,
    `replayed_original_calls` 0.
  - "107 Int32 (76 + 31)": verified. `original_int32` shows
    `separate_direct_calls_compared_each_python` 107, `booleans` 76,
    `errors` 31 (76 + 31 = 107).
  - "2 runs x 78 tests": verified. Both `runs` entries (313, 310) show
    78 tests / 0 failures / 0 errors / 0 skips.
  - "conditions 0 replayed rows vs 279 arms": verified.
    `original_comparisons` shows `replayed_original_rows` 0 with
    `production_stage_arms_each_python` 279.
  - "94 expanded tests with 21 Windows cases": verified. Each `tests`
    entry shows 94 tests with `actual_windows_cases` 21 (13 preference +
    8 reset) and `all_namespaces_removed` true.
  - "36 + 20 + 2 updates": verified. `vectors` shows
    `original_menu_cases_per_run` 36,
    `captured_original_collection_cases` 20, `owned_tls_cases_per_run` 2.
  - "51 About": verified. `counts` shows
    `original_instruction_cases_per_python` 51.
  - "7 live observations, 108 host + 113 CLI": verified. The system
    acceptance shows 7 `typed_cases` with `user_context_parity_verified`
    false; the host review shows 108 tests and the CLI review 113.
  - Self-limit reconciliation: the implementation-status
    `preferences-and-update-workflow` limits (line 80) claim the 40
    definitions / 19 OK-handler edits / registry load-save-preview /
    diagnostics / 7-case worker acceptance while leaving actual VCL
    behavior, interactive user-context acceptance, original lazy-wrapper
    comparison, broader condition types, culture-sensitive comparisons,
    rollout, publisher-chain/current trust, and complete
    applicability/update availability open; the "Update registry
    conditions" research row (line 123) leaves interactive user-context
    repetition, lazy-wrapper comparison, and rollout/trust open. The
    audit's per-slot verdicts match those limits exactly.

  Per-slot verdicts (evidence paths are committed artifacts only; the
  existing rubric is applied unchanged):

  - `nominal_workflow` = `unassessed`: 0 row-level replayed
    original-Toolkit executions (need >=10). The rubric's nominal gate
    therefore reports `only 0 original executions, need >=10`. No single
    committed replay test covers the row scope, HKCU registry is not the
    rubric's database leg, and no single acceptance record bounds the
    full 40-preference + updates + conditions + registry + live + About
    scope -- each of the ~12 fixtures disclaims the other fragments.
  - `error_path` = `unassessed`: no original-observed error vectors with
    exact error identity. The preserved failed-preparation record,
    injected fault/interruption tests, and guard tests are process
    observations, not replayable original error vectors.
  - `device_firmware_variation` = `unassessed`: single profile only
    (Toolkit 1.18.00 x86 family); the fragment scope notes bound their
    nominal fragments but do not flip this slot.
  - `invalid_input` / `unsupported_profile` = `unassessed`: input guards
    (JSON bounds, hive/view limits, culture/tagged-default rules) are
    scoping guards without original-observed rejection identity.
  - `hardware_divergence` = `unassessed`: no physical-device evidence;
    Windows runs use owned scratch namespaces / LocalSystem HKCU with no
    C-Bus network, C-Gate programming, or device commands.

  32 rows plus the full census mapping remain outstanding after the
  seventh row below; all seven rows' thirty-nine open slots require
  fresh original/firmware/negative/hardware evidence (final tally at
  the end of the toolkit-database-report-export row).

  ### Offline gate posture (this env, PreferencesUpdate row)

  The fresh-original probes (`OriginalUpdateMenuTests`, the About /
  numeric / reset original probes requiring `CBUS_TOOLKIT_EXE`), the
  Windows scratch-registry suites (requiring Windows +
  `CBUS_WINDOWS_PROVENANCE_ROOT`), and the LocalSystem worker execution
  all SKIP offline in this env. The offline-runnable suites -- store /
  conditions / metadata / revocation / about vector replays, live
  wrapper/transport tests with deterministic providers (108 host + 113
  CLI focused tests), and CLI-shape tests -- run here with no
  provisioning. Gate runs here therefore rest on committed artifacts
  plus the prior runs recorded in the acceptance fixtures -- not on live
  vendor re-execution.

  `NativeMemoryTests` (requires `CBUS_CGATE_TEST_HOST` +
  `CBUS_UNITSPEC_DIR`) and `VendorLayoutTests` (requires
  `CBUS_UNITSPEC_DIR`) plus the `research/verify_catalog.py` runner
  (requires a live native C-Gate) all SKIP offline in this env. The
  offline-runnable suites -- `MemoryImageTests`, `MemoryCodecTests`,
  and `UnitSpecTest` -- run here with no provisioning. Gate runs here
  therefore rest on committed artifacts plus the prior native runs
  recorded in `docs/catalog-acceptance-summary.json` (boundary_workflow
  selected/completed 6497, status complete) and
  `docs/native-memory-acceptance.json` (163 cases, 161 pass) -- not on
  live native re-execution.

  ## The seventh attempted row: `toolkit-database-report-export` (0/6)

  Row id verified present in `capabilities.json` (line 724). The rubric
  is applied UNCHANGED and decides against a flip: a 0/6 verdict with
  documented gaps is the honest success here, not a failure. This is a
  broad multi-scope row (explicit captured-value serializer, strict
  cached-object projector, admitted native XML adapter, live C-Gate
  acquisition, guarded B03 Area13 apply, 26-column selection
  persistence, Toolkit-native ACP encoding, KEYE/DIN/SENPIROA
  profiles), and it fails nominal because no single bounded scope
  carries the >=10-original leg together with the database-persistence
  leg and a spanning acceptance record. CAUTION observed: the
  sub-scope legs below must NOT be stitched into a row-level pass
  (thermostat row-4 precedent: distinct bounded scopes cannot be
  combined).

  Replay-vs-native-vs-self-referential classification (read before
  claiming anything):

  - REPLAYED per-execution (committed offline tests, no provisioning):
    `tests/test_toolkit_database_csv.py` replays 70 row + 13 quote
    committed original vectors per execution (83 of the 88 committed
    vectors; empty/high masks and NUL behavior remain research-only);
    `tests/test_toolkit_database_csv_projection.py::
    test_all_twelve_original_cases` reproduces all 12 captured original
    class/Area/group outcomes per execution (10 completed + 2 declared
    provider stops; the review records
    `original_binary_executed_in_this_test: false`, so this is captured
    replay, not fresh execution);
    `tests/test_toolkit_database_csv_native.py` projects synthetic
    native-XML shapes (RELAY4/KEYE/DIN/SENPIROA) offline -- committed
    adapter checks, self-referential alone for rubric purposes.
  - NATIVE prior runs (not re-executed here): the owned C-Gate B03
    apply test (`tests/test_toolkit_database_csv_area_native.py`,
    requires `CBUS_CGATE_JAVA`) backs up, creates application-56 group
    13 as `Group 13`, saves, closes, reloads and verifies persistence
    with 0 CNI and no physical access (prior run: 42 focused + 1 owned
    test, recorded in `csv-missing-area-review.json`); live acquisition
    (`csv-live-cgate-review.json`) is 2 DBGETXML-only protocol cases
    (existing-Area12 complete, missing-Area13 stop) with
    `native_database_mutated: false`.
  - FRESH ORIGINAL prior runs (not re-executed here): the 88-case
    serializer probe (`tests/test_toolkit_database_csv_original.py`,
    gated on `CBUS_TOOLKIT_EXE`) and the backend original8 (8 cases,
    16 invocations, 37,933 entries) plus the successor replay of all
    four native fixtures (8 invocations, 27,661 entries; B03 stopped at
    the refused GroupSave, not a persisted save) -- all SKIP offline;
    their prior runs are recorded in the committed acceptance/review
    fixtures.
  - SELF-REFERENTIAL (never flip a slot alone): guard/CLI-shape tests,
    adapter-guard tests, static method-byte pins (selection 15 methods,
    encoding writer path), and the Windows scratch-registry / CP1252
    runs (owned namespaces, system ANSI code page only).
  - SITE-DEPENDENT, EXCLUDED from the flip basis: the KEYE read-only
    sweep (all 22 matching KEYE records), the DIN sweep (4 records),
    and the SENPIROA sweep (1 record) in `csv-keye-profile-review.json`,
    `csv-din-profile-review.json`, and
    `csv-senpiroa-profile-review.json` each ran against "unchanged
    GRENACHE.xml copied read-only from the user-owned Windows VM" with
    `raw_snapshot_committed: false`. `csv-keye-secondary-application-review.json`
    is a static-only SecondApplicationBlocks mask/resolution analysis
    (no snapshot reference) and is likewise excluded. The site snapshot is not committed
    and is never read by the committed tests; those four reviews are
    deliberately absent from the row's evidence paths. Profile coverage
    in the flip basis rests only on committed offline synthetic tests
    and static analyses (zero original executions per profile).

  Numbers verification (every claimed number verified against committed
  artifacts; nothing assumed):

  - "88 vectors (73 row + 15 quote), 70 + 13 replayed offline":
    verified. The vectors fixture shows `case_count` 88,
    `row_case_count` 73, 88 entries; the acceptance fixture shows
    `original_cases` 88 with `portable_row_cases` 70 +
    `portable_quote_cases` 13 over 23 tests per Python, and its scope
    declares `database_projection_verified: false`. The offline tests
    assert counts 70 and 13.
  - "12 projector outcomes (10 + 2)": verified. The cached-projection
    review shows `captured_original_cases_replayed` 12,
    `captured_original_completed` 10, `captured_provider_stop_partials`
    2, with `original_binary_executed_in_this_test` false; the offline
    test asserts `len(cases) == 12`.
  - "8 backend cases / 4 native captures / 27,661 replay entries / 473
    inputs unchanged": verified. The original8 analysis shows
    `complete_cases` 8, `original_invocations` 16,
    `original_instruction_entries` 37933; the native4 analysis shows 4
    fixtures with `archived_inputs_verified` 473; the successor replay
    shows `original_invocations_attempted` 8,
    `original_instruction_entries` 27661, 4 fixtures, and
    `historical_native_archive_inputs_verified` 473. B03 created exactly
    address 13 / `Group 13` and declared stop "Explicit owned storage
    save denied".
  - "Guarded B03 backup/save/reload + live acquisition": verified. The
    missing-area review shows focused 42 + owned C-Gate 1 passing with
    backup true, created 56/13/`Group 13`, target save + reload true, 0
    sentinel CNI, physical false. The live review shows 2 protocol
    cases with no database mutation.
  - "Windows corroboration (26-column selection, ACP output)":
    verified. The selection review pins 26 labels / 15 methods (host
    53, owned Windows 2: SelectAll default, 32-bit REG_SZ roundtrip,
    cleanup); the encoding review pins the CP_ACP path (core 56,
    owned Windows 3 on CP1252 incl. surrogate-pair replacement).
    Static bytes only -- not original executions.
  - Self-limit reconciliation: the implementation-status
    `toolkit-database-report-export` limits (line 84) leave
    secondary-application associations for other families and remaining
    unit profiles open; the CSV research row (line 122) leaves
    secondary-application associations for other families, remaining
    unit profiles, and physical behavior open. The audit's per-slot
    verdicts match those limits exactly.

  Per-slot verdicts (evidence paths are committed artifacts only; the
  existing rubric is applied unchanged):

  - `nominal_workflow` = `unassessed`: 88 serializer fresh-original
    cases (>=10) with committed offline replay exist, but the only
    database save/close/load leg (exact archived B03 apply scope) and
    the only spanning-claim records live in different bounded scopes
    than the serializer/projector scopes -- the serializer acceptance
    explicitly declares `database_projection_verified: false`, and each
    of the ~7 acceptance/review fixtures disclaims the other fragments.
    The rubric's nominal gate therefore reports `missing rubric
    requirement: has_native_persistence` (row-level persistence /
    record / scope flags recorded False).
  - `error_path` = `unassessed`: no original-observed error vectors with
    exact error identity. Preserved preparation observations, injected
    faults, and guard tests are process observations, not replayable
    original error vectors.
  - `device_firmware_variation` = `unassessed`: single Toolkit-profile
    family for all original comparisons (1.18.0.2754); KEYE/DIN/SENPIROA
    static/synthetic coverage carries zero original comparisons per
    profile (need >=2 with original comparisons per profile).
  - `invalid_input` / `unsupported_profile` = `unassessed`: strict input
    guards and profile rejections are scoping guards without
    original-observed rejection identity.
  - `hardware_divergence` = `unassessed`: no physical-device evidence;
    owned runs record 0 CNI connections and `physical_device_accessed:
    false`, and native runs are loopback C-Gate processes.

  31 rows plus the full census mapping remain outstanding; these seven
  rows' thirty-nine open slots require fresh original/firmware/
  negative/hardware evidence.

  ### Offline gate posture (this env, DatabaseReportExport row)

  The fresh-original serializer probe (`OriginalCSVTests`, requires
  `CBUS_TOOLKIT_EXE`), the owned C-Gate B03 apply test (requires
  `CBUS_CGATE_JAVA` + vendor C-Gate), and the Windows selection/encoding
  suites (require Windows + `CBUS_WINDOWS_CSV_SELECTION` /
  `CBUS_WINDOWS_CSV_ENCODING`) all SKIP offline in this env (5 skips
  observed across the row's gated suites). The offline-runnable suites
  -- serializer vectors (70 + 13), 12-outcome projector, synthetic
  native-XML adapter, Area guards, selection logic, and CLI shape (65
  tests) -- run here with no provisioning. Gate runs here therefore
  rest on committed artifacts plus the prior runs recorded in the
  acceptance/review fixtures -- not on live vendor re-execution.

## The eighth attempted row: `edlt-scene-live` (1/6)

The `edlt-scene-live` ledger entry already cites the six committed tests,
fixtures, and bounded narrative used by this audit. The existing rubric is
applied unchanged: `nominal_workflow` passes; the other five slots stay
`unassessed`. A partial fill is progress, not area acceptance.

The accepted slot is limited to KEYGL5 / 5055EDL / firmware 5.5.00 one-shot
serial capture and broadcast on issued retained scene references. Capture has
verified PP staging and save/close/load readback, and broadcast has an
independent synthetic receiver. This does not claim GUI timer or asynchronous
dispatch parity, complete form binding, or physical-device behavior.

Evidence classification:

- Replayed original executions (gated, with prior runs recorded): the
  committed `OriginalSceneLiveTests` oracle test executes all 14 named vector
  cases through the original DLL for each provisioned run. It compares the
  874-field `after-original-crc` result and ordered wire output for every case,
  including callback completion markers for broadcast cases. Both acceptance
  runs record 14 original executions with 874 parameters each, within a
  17-test run with no skips. The offline module tests separately replay the
  committed complete-capture result.
- Native persistence (gated, with prior runs recorded):
  `NativeSceneLiveTests` captures known levels through an owned loopback C-Gate
  3.4.0 build 2001 service, verifies the complete 874-parameter plan, 232 raw
  SceneBucket bytes and five CRC fields, saves, closes and reloads the project,
  then compares full readback and unchanged metadata. It also sends the three
  retained items to an independent synthetic PCI receiver and reloads that
  receiver's persisted state. The CLI native test covers preview, save/reload,
  and receiver behavior through the command surface.
- Self-referential evidence: offline guard, transport, failure-attachment,
  interruption, and CLI-shape tests use synthetic clients or peers. They test
  this implementation and therefore do not independently flip a slot.
- Site boundary: all cited evidence paths are committed. The combined CLI
  regression fixture records 10 modules and 75 passing tests with no skips on
  both Python versions, but it is source regression corroboration rather than
  installed-wheel or physical-device acceptance.

The hardcoded evidence values are pinned by an offline test to the committed
artifacts:

- `edlt-scene-live-vectors.json` has format
  `cbus-original-scene-live-vectors-v1`, 14 cases, 874 input parameters, and an
  874-field final state plus ordered wire and hash pins for every case. It sets
  `physical_device_verified: false`.
- `edlt-scene-live-acceptance.json` has two runs. Each records 17 tests, zero
  skips, 14 original executions with 874 parameters each, and true
  `save_close_reload_verified`, `metadata_unchanged`, and
  `independent_receiver_persisted` values. Its profile is
  KEYGL5/5055EDL/5.5.00, and it records nine additional SceneManager regression
  tests per run.
- The focused source collection has 11 module tests and six CLI tests. The
  combined regression fixture has 10 modules and 75 tests per run. The offline
  integrity test derives these counts from the committed test sources and
  fixtures rather than trusting prose alone.

Per-slot verdicts:

- `nominal_workflow` = `accepted`: 14 original executions meet the minimum of
  10 and are replayed by a committed oracle test; the owned native run supplies
  save/close/load readback; and the acceptance record bounds the claim to one
  profile and explicitly excludes physical-device verification.
- `error_path` = `unassessed`: negative vector cases are original-oracle
  provenance, but no committed test replays this implementation against those
  vectors with exact error-identity assertions. Its offline negative tests use
  synthetic clients and guards, so `original_error_cases` remains 0.
- `device_firmware_variation` = `unassessed`: the evidence covers one profile,
  KEYGL5 5.5.00.
- `invalid_input` and `unsupported_profile` = `unassessed`: local argument,
  cache, and source guards have no original-observed rejection basis.
- `hardware_divergence` = `unassessed`: both retained fixtures explicitly set
  physical-device verification false; loopback C-Gate and the synthetic
  receiver do not count as hardware evidence.

Thirty other ledger rows plus the full census mapping remain outstanding.
Across the eight attempted rows, 44 of 48 slots remain open: five for each of
the four 1/6 rows and six for each of the four 0/6 rows. `accepted_areas`
therefore remains 0 and `complete` remains false.

### Offline gate posture (this environment, SceneLive row)

The original-DLL test requires `CBUS_TOOLKIT_EXE` and `CBUS_UNITSPEC_DIR`.
The native module and CLI tests require `CBUS_CGATE_TEST_HOST` and
`CBUS_UNITSPEC_DIR`. Without that provisioning they skip. The nine remaining
module tests and five remaining CLI tests run offline against committed data
and synthetic transports. The slot therefore rests on committed artifacts and
the prior gated runs recorded in `edlt-scene-live-acceptance.json`, not a new
vendor or physical-device execution in this environment.

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

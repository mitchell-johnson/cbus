# Bounded IOPE editor workflows

Issue #40 has eight callable component workflows for IOPE1R1, IOPE2R2 and
IOPE2C4: [Environment corridor linking](iope-environment.md),
[output Turn On/Restrike](iope-output-settings.md), [output Logic](iope-logic.md),
[join power-up recovery](iope-join-recovery.md),
[Environment block timers](iope-block-timer.md), [join group selectors](iope-join-groups.md)
[scene action selectors](iope-scene-selectors.md) and
[retained scene command levels](iope-scene-levels.md). The source/catalogue
intersection admits firmware 1.0.00..1.2.99; native execution covers the nine
exact model/revision combinations at 1.0.00, 1.1.00 and 1.2.00.

## Standalone CLI

No shared CLI file is changed by this slice. The wheel includes this entry point:

```sh
python -m cbus_toolkit.iope_workflow_cli --help
python -m cbus_toolkit.iope_workflow_cli --spec-dir "$CBUS_UNITSPEC_DIR" \
  output show snapshot.json
python -m cbus_toolkit.iope_workflow_cli --spec-dir "$CBUS_UNITSPEC_DIR" \
  output plan snapshot.json --edits edits.json > plan.json
```

Snapshots must be `cbus-cli-parameters-v1` with exact unit type, firmware and
catalogue number; bare mappings are refused. An output `edits.json` example:

```json
{"channels":{"1":{"min_percent":50,"restrike":true},"3":{"min_percent":60}},"restrike_delay":60}
```

This example requires IOPE2C4 because channel 3 is a dimmer. Channel keys are
canonical strings `"1"`..`"4"`; unsupported channels and controls are rejected.
Use `environment`, `logic`, `join-recovery`, `block-timer`, `join-groups` or
`scene-selectors` or `scene-levels` in place of `output` for those editors. All seven require the
explicit `group_cache` described in their documents. Logic uses its own cache format; both scene components share the complete
scene-selector cache. The other four share the Environment cache format.
Both scene components declare a complete inventory of existing action addresses.
Logic `channels` and `logic_groups` keys are canonical strings `"1"`..`"4"`.
Caller group evidence establishes positive object membership, not original GUI
execution.

The database command takes an explicitly selected server and canonical unit
path. It never accepts a physical PP path, separate destination, automatic
network open, group creation or an unrelated network lock. For an **owned
synthetic project**, a typical preview is:

```sh
python -m cbus_toolkit.iope_workflow_cli --spec-dir "$CBUS_UNITSPEC_DIR" \
  output database --host 127.0.0.1 --port "$OWNED_CGATE_PORT" \
  --source /db//TEST/254/p/20 --lock-address //TEST/254 \
  --plan plan.json --exclusive-project --dry-run
```

Replace `--plan ... --exclusive-project --dry-run` with `--export` to produce
an offline snapshot, or `--show` for the current editor view. To save a
reviewed plan, omit `--dry-run`. The caller must exclusively own project
editing and reloading. The workflow verifies every project network is closed
with synchronization idle before staging and before save. Every plan that
uses group metadata proves each claimed application/group against fresh native
database XML at both points. Both scene components require exact agreement
with the complete native action-address inventory at both points. Level Values
are preserved and do not encode those selectors. It does not create missing groups. Native access remains the
caller's explicit endpoint choice; examples do not authorize physical access.

A save performs one PP SAVE_TO_SOURCE, one PROJECT SAVE, then a fresh PP LOAD
and exact whole-parameter comparison. `saved=true` requires both save replies
and this fresh reload. A no-change plan sends neither save. Dry-run stages,
verifies, then discards the PP session. Stale/canonical-plan and metadata
refusals happen before writes. Invalid/forged plans with a supplied identity
are rejected before connection. The PP editor handles failures during staging;
no automatic restore or retry occurs after a save attempt. Interruptions and
failed saves retain `pp_save_attempted`, `project_save_attempted`,
`outcome_uncertain` and `automatic_retry_performed=false` in the error result.

The unapplied [registration patch](iope-workflow-registration.patch) adds
`cbus-toolkit iope-workflow` as an alias using the same parser and execution
path. It changes only the parser registration and dispatch; integration owns
its application and the central capability/dialog/coverage records.

## Retained scene-level acceptance

[The current acceptance summary](iope-scene-levels-acceptance-summary.json)
binds the frozen wheel, source receipts and focused tests. `scene-levels`
selects one raw or percentage value for an existing command; optional
synchronization owns all eight level assignments in that scene. Its per-row
integer attribute equality guard preserves retained raw 126/127/128 when
50% is already displayed. The fresh temporary SceneManager lifecycle fixes
Live off and makes both display mode and synchronization transitions explicit.

The unpacked wheel passed 31 focused tests and 245 subtests across the new
component, retained selectors and standalone CLI. Eight isolated native tests
passed with no skips. The new nine-profile matrix verified 243 edits/no-ops,
243 unchanged refusals and 19,440 raw-byte comparisons, plus CLI dry-run,
save/fresh reload, cold project reload, stale refusal and fresh metadata checks.
The three preceding native matrices were reaccepted; their only changed fields
are current implementation hash bindings. All four owned services confirmed
listener ownership, process exit and complete cleanup. These are synthetic
closed database units; no physical effect or original form execution is claimed.

Ten source receipts verify 281 method ranges, 41 data ranges, 25 literals,
19 form resources and four UnitSpecs per receipt. The input audit separately
checks 14 exact next-recovery MAP bounds; those locations remain unrecovered
behavior. The [template transaction audit](iope-template-transaction.md)
corrects the earlier advanced-row branching description and identifies the
ordered factory, entry graph, subset, dependent-stage and serializer gates.
No input-function API is added.

The scene-level component uses the temporary row callback and a static stable
table projection. Whole accepted `SaveNeoScenes` graph replacement and its
input notifications remain excluded. Admission neither executes those callbacks
nor establishes their preservation. A whole original scene-save transaction
requires separate source recovery and acceptance.

Focused native reproduction uses the existing owned Java/C-Gate environment:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests:. python -B -m unittest -v \
  test_iope_scene_levels_native.IopeSceneLevelsNativeTest \
  test_iope_scene_levels_native.IopeSceneLevelsNativeReceiptTest
```

Set `CBUS_IOPE_SCENE_LEVELS_REPORT` to the scoped receipt path only when
intentionally refreshing it. The local backend requires the explicitly selected
Java11, pinned C-Gate vendor files, decoded specs and task-owned temporary
storage. Hash changes invalidate corresponding receipts. No full suite, Rust
build, CPU emulation or household operation ran.

## Join group and scene selector acceptance (earlier component checkpoint)

The existing-application Join component enforces original dropdown object
conflicts and preserves applications, recovery, allocation and scene fields.
It refuses first-group clearing and states requiring corridor initialization.
The Scene component changes one existing normal or all-off selector under a
fixed Trigger group. It requires four stable eight-command scenes and complete
existing action objects, and preserves content, pointers, ramps, inputs and
joins. Whole SceneManager and IOPE SaveScenes execution remain outside it.

The current wheel passed 101 focused tests and 847 subtests with source gates
enabled. Six sequential native tests passed with no skips: both prior matrices
and their receipt checks, then the new matrix and receipt check. The new nine
profile rows cover 225 positive edits, 414 unchanged refusals and 1,305 raw-byte
assertions. Both new CLI families passed export, offline planning, dry-run,
apply, stale/cache refusal and cold reload. A native action whose Address is 30
and Value is 99 proves the selector consumes Address. All three owned services
confirmed complete cleanup. Prior native receipts changed only their wrapper
implementation hash binding.

The static verifier checks 225 named method ranges across eight receipts,
41 data ranges, 25 literals, form resources and all relevant UnitSpecs. The
input-function receipt is explicitly a source blocker; passing its byte hashes
does not admit input edits. [Input-function findings](iope-input-functions.md)
identify the remaining template recognition, subset and dependent recoding
modeling needed before one initialized row can be accepted. No personal setup
or project data is part of these technical records.

Current hashes and exact applicability are recorded in
[iope-graph-editors-acceptance-summary.json](iope-graph-editors-acceptance-summary.json).
The earlier summaries below describe their historical wheels.

Add `tests/test_iope_join_groups.py` and `tests/test_iope_scene_selectors.py` to
the focused command below. To regenerate the new native receipt, use the same
owned-service variables and run these classes in order:

```sh
PYTHONPATH=src:tests:. python -m unittest -v \
  test_iope_join_groups_native.IopeJoinGroupsNativeTest \
  test_iope_join_groups_native.IopeJoinGroupsNativeReceiptTest
```

Set `CBUS_IOPE_JOIN_GROUPS_REPORT` to
`research/fixtures/iope-join-groups-native-acceptance.json` when intentionally
refreshing it. Wrapper changes also invalidate the two prior native receipt
bindings; refresh their four classes sequentially against the same wheel.

## Logic, join recovery and block timer follow-up

This section records the historical `1b512236` wheel and focused checks.

These three families extend the same standalone parser, canonical plan replay,
closed-project checks and save/reload path. The optional registration patch
needs no additional shared dispatch changes. Source-backed behavior includes:

- Logic associations and And/Or for every active output, ordered same-group
  recovery copies and all-four-row initialization when the recovery modal opens.
- Join recovery's five-bit normalization for a positively resolved first join;
  ambiguous dual-populated or mixed-application group state is refused.
- Simple Environment timer expiry commands and duration for an existing enabled
  role, with the corridor minimum and surrounding input/scene preservation.

The frozen wheel passed 81 focused tests and 773 subtests with source gates
enabled. The final expanded join source gate also passed separately. The new
owned native matrix and receipt-integrity test passed: nine exact profiles,
246 positive edits, 234 unchanged refusals, 426 raw-byte assertions and 261
full-array assertions. All three CLI families passed export, offline planning,
dry-run, apply, stale-plan and false-metadata refusal, and cold project reload.
The previous two-family native matrix and receipt test passed against this
same wheel; its refreshed receipt differs only in the CLI implementation hash.
Both owned services confirmed full cleanup.

The source verifier now checks 131 method ranges across all five receipts,
plus 39 join interface/data ranges and 16 original literals. Source receipts
also pin the form resources and four relevant UnitSpecs. Independent review
found no blocking findings. Detailed hashes and acceptance boundaries are in
[iope-editor-followup-acceptance-summary.json](iope-editor-followup-acceptance-summary.json).

Run their focused tests alongside the prior families:

```sh
PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider \
  tests/test_iope_environment.py tests/test_iope_output_settings.py \
  tests/test_iope_workflow_cli.py tests/test_iope_settings.py \
  tests/test_iope_logic.py tests/test_iope_join_recovery.py \
  tests/test_iope_block_timer.py -k 'not IopeNativeTest'
```

The new native receipt is generated and checked with the same owned local
service variables described below, using these classes in order:

```sh
PYTHONPATH=src:tests:. python -m unittest -v \
  test_iope_logic_native.IopeLogicNativeTest \
  test_iope_logic_native.IopeLogicNativeReceiptTest
```

Set `CBUS_IOPE_LOGIC_REPORT` to
`research/fixtures/iope-logic-native-acceptance.json` when intentionally
refreshing it. Run the previous native classes separately after changes to the
shared IOPE wrapper; this follow-up refreshes their implementation hash binding.
The original first-slice summary below remains historical.

## Original Environment/output acceptance

The following records the original `690b096` slice. Its summary binds that
historical wheel; the follow-up acceptance is recorded separately.

Final checks use the built wheel's unpacked package, with imports bound by
hash to the checked-in implementation. The wheel hash and evidence hashes
are in [iope-workflow-acceptance-summary.json](iope-workflow-acceptance-summary.json).

- 41 focused tests and 96 subtests passed. The pre-existing IOPE native test
  was deliberately deselected; its scope was not changed. The new native test
  below executed separately without required skips.
- Two new native tests passed: the matrix/CLI test and receipt integrity.
  Nine model/firmware rows cover 72 positive edits, 102 unchanged refusals and
  162 raw-byte assertions, including hidden corridor writes, slider cascades,
  inactive slots and neighboring bits. Actual native 0.9.99 is refused by both
  new editors without changing its parameters.
- Both CLI families cover export, show, offline planning, dry-run, saved-plan
  apply, stale-plan refusal, all-parameter preservation and cold project
  SAVE/CLOSE/LOAD persistence. A false claimed Environment group is refused.
- The C-Gate JAR and Temurin Java 11 hashes are pinned. The test owns all six
  loopback listeners, adopts no projects and confirms complete process,
  directory and socket cleanup.
- Original EXE/MAP, 21 named method ranges, four UnitSpecs per receipt and
  three output form resources match the source receipts. Independent review
  checked the original corridor handlers and both output slider cascades.

Reproduce source checks without executing original machine code:

```sh
python research/verify_iope_workflow_sources.py \
  --exe "$CBUS_TOOLKIT_EXE" --unitspec-dir "$CBUS_UNITSPEC_DIR"
```

Focused Python checks from `toolkit-cli/`:

```sh
PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider \
  tests/test_iope_environment.py tests/test_iope_output_settings.py \
  tests/test_iope_workflow_cli.py tests/test_iope_settings.py -k 'not IopeNativeTest'
```

Set `CBUS_TOOLKIT_EXE` and `CBUS_UNITSPEC_DIR` to run the source-byte gate.
The separately provisioned native command uses `CBUS_NATIVE_SERVICE_BACKEND=local`,
`CBUS_LOCAL_CGATE_VENDOR`, `CBUS_CGATE_JAVA`, `CBUS_UNITSPEC_DIR` and a private
`TMPDIR`; run these test classes in this order to regenerate and verify:

```sh
PYTHONPATH=src:tests:. python -m unittest -v \
  test_iope_workflow_native.IopeWorkflowNativeTest \
  test_iope_workflow_native.IopeWorkflowNativeReceiptTest
```

Set `CBUS_IOPE_WORKFLOW_REPORT` to the receipt path when intentionally refreshing
it. Source, schema or editor changes invalidate the corresponding hash-bound
receipt and require focused reacceptance. No full suite or Rust build ran.

## Remaining boundary

This does not close issue #40 or establish complete Toolkit parity. Input
functions, scene command/group insertion or removal and whole-manager saves, join application
changes and first-group clearing, unsupported timer expiry families,
group auto-creation, other tabs and unrelated whole-dialog save rewrites remain outside these
components. Original GUI/CPU-runtime execution, physical timing, real-unit
writes and power-cycle acceptance are unverified. No household, USB,
firmware or physical network operation was performed.

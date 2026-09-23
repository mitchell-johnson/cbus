# eDLT database model lifecycle

`EdltLifecycle` computes the original eDLT model's **AfterLoadPPData → BeforeSavePPData(database) → five configuration CRCs** for **KEYGL5 / 5055EDL / firmware 5.5.00**. It is a separate, explicit normalization workflow. Existing widget and global-setting helpers retain their documented direct-edit behavior.

The plan exposes each phase and its changes before applying anything. It requires a complete PP snapshot and explicit caller-supplied cache facts. It does not construct the complete Toolkit dialog, create missing metadata, upload dynamic labels, or program a physical unit.

```python
from cbus_toolkit.edlt_lifecycle import EdltLifecycle, LifecycleCache

editor = EdltLifecycle(spec)  # caller's original KEYGL5.xml
requirements = editor.requirements(values).as_dict()  # no I/O
plan = editor.plan(values, metadata=LifecycleCache.from_dict(cache_document))
print(plan.as_dict()['phases'])
result = editor.apply(session, plan)  # exact database identity, full PP readback
session.save_to_source()             # explicit database save
```

`.configure(session, metadata=...)` validates the cache syntax and identity, reads PP state, plans, and applies. `LifecycleMetadataError.details` and `.as_dict()` preserve the exact required fact and original failure stage. A failed plan performs no parameter edits.

## Retained load and save phases

The same workflow is available as two pure phases:

```python
loaded = editor.load(values, metadata=cache_document)
print(loaded.as_dict())       # diagnostics do not invoke original mutating getters
plan = editor.prepare_save(loaded)
```

`plan(values, metadata=...)` composes those exact methods. The immutable `LoadedEdlt` belongs to the editor instance that created it. `prepare_save` accepts that intact object, leaves it unchanged and returns the existing `LifecyclePlan` format. It does not load again, parse scene bytes again or resolve item groups against a new application. A copied/modified dataclass, dictionary or state from another editor is rejected. The diagnostic dictionary is not a model resumption format.

Loaded diagnostics retain the legacy plan-event ordering. Entries marked `before_save` describe the upcoming save projection; they do not mean that save has already run.

The state retains 21 widget identities with stored type and actual model family, a separate page-widget object, all eight scene identities, scene item references to shared immutable cache objects, original static text bytes and initialized MRA globals. A missing scene action remains the private `-1` value until save projects the original fallback. Two scenes sharing a source pointer remain distinct loaded objects; their items can share the same cached application/group object. Unsupported stored types retain their bytes while using `BlankData`.

Static-label diagnostics decode valid UTF-8 only. Invalid text bytes are retained unchanged; the new diagnostic API does not claim to evaluate the original replacement-decoded string. No text setter, application edit, control binding or Corridor editor is added by this split. Existing preflight guards remain in force, including early rejection of a missing scene output group with `original_stage='before_save'`.

## Cache facts

```json
{
  "format": "cbus-edlt-lifecycle-cache-v1",
  "applications": [56, 57, 202, 203],
  "groups": [
    {"application": 56, "group": 42, "exists": true,
     "dynamic_images": [false, true, false, false]},
    {"application": 202, "group": 42, "exists": true,
     "levels": [0, 1, 2]},
    {"application": 202, "group": 255, "exists": true,
     "levels": [], "dynamic_images": []},
    {"application": 56, "group": 99, "exists": false}
  ]
}
```

This example is illustrative; `requirements(values)` lists the exact applications, group facts and conditional image/level requirements for the supplied snapshot. The CLI does not fetch those facts automatically.

| Field | Meaning |
|---|---|
| `applications` | Unique original cached application objects, addresses 0..255. Required missing applications are rejected. |
| Group `exists` | Strict boolean stating whether that exact cached group object exists. An absent record means **unknown**, not absent. |
| `dynamic_images` omitted | Image/cache state unknown; rejected if the constructor needs it. |
| `dynamic_images: null` | A present group has an unpopulated `DynamicAll`; the original Lighting constructor preserves its label type. |
| `dynamic_images: []` | The populated dynamic list is empty. An indexed read fails. |
| Boolean image array | Actual image-object presence in effective variant slots, at most four entries. It does not assert that an icon exists on a physical device. |
| `levels` | Complete populated native level-cache addresses for that trigger group, including initialized `DynamicAll` collections for every listed level object. Omitted means unknown. |

The level-cache contract excludes partially constructed native level objects whose dynamic collection is null. The original `CBusLevel.ReadXmlData` populates that collection; the original scene refresh otherwise fails while iterating it. The schema cannot represent that incomplete-cache state as a valid populated level list.

Unused group 255 is also an explicit cache fact when consumed. Original application objects contain a virtual unused group; this does not mean a new database or physical group was created. A group declared absent cannot supply image or level data. Duplicate applications, group keys or levels, unknown fields, boolean/integer substitutions and out-of-range values are rejected. Limits are 256 applications, 512 group records, 256 levels per group and 8,192 total level addresses.

The result identifies `metadata_provenance='caller-supplied-cache'`. It records the facts consumed, while `cache_freshness_verified`, `database_metadata_created` and `physical_device_verified` remain false.

## Original phase behavior

| Phase | Covered behavior |
|---|---|
| Load globals | Primary 255→56, inversion 1→0, configuration major/minor 255→1/0. |
| Construct widgets | Lighting dynamic text/icon resolution from actual cached image presence; Enable macro and dependent preset normalization. Construction runs even for a widget later cleared by a functional terminator. |
| Load terminators | Type 1 reads as blank. Standby 255 becomes blank. The first functional 255 and following functional widgets become blank. Restore resets only on an actual type change; opaque bytes remain. |
| Resolve surviving groups | Disabled-secondary selection clears on surviving primary/secondary application widgets; fixed-application Scene and Enable retain their separate semantics. |
| Save scenes | Read all eight source pointers independently of SceneCount, preserve slot identities, repack all eight slots, resolve trigger/action references from supplied facts, mask reserved header bits, and pad to 232 bytes. |
| Save widgets | Propagate first surviving MRA globals; add final functional terminator; force Lighting offset, Timer target and Fan/MultiLevel static status with the original dependent-reference resets. |
| CRCs | Calculate all five original configuration CRCs over the documented zero-initialized temporary serialization image. |

Loading a hidden Lighting widget can still convert its label byte from `0x10` to `0x20` before its type is cleared. A hidden Enable widget can likewise acquire macros 10/23 and preset 255 before becoming blank. The original Enable constructor preserves a preset when either old macro is 23 or 24; otherwise switching to 10/23 resets it. This follows the original macro input definitions, including the original Preset2 metadata using TargetLevel1.

Stored dynamic label indexes above 3 are retained while the getter uses effective index 0. A present image array must contain that effective slot. Missing groups preserve the Lighting label type; they are distinct from a populated group whose effective image is absent.

A missing scene trigger becomes unused 255. A missing action becomes cached action 0 if present, otherwise the original invalid sentinel serializes as 255. Missing scene output groups fail the original before-save stage and are rejected before edits. Default empty scenes serialize as `02 00 FF FF FF`; eight such records occupy 40 bytes with pointers 0,5,…,35. Shared source pointers and holes remain separate slots in the repacked result.

Existing unknown types 17..254 use the original BlankData fallback while retaining their stored type and opaque bytes; they still count as active for final terminator placement. The result identifies these records as `blank_fallback_widgets`, without claiming they are usable Toolkit widgets. The lifecycle does not allocate text and preserves unchanged text bytes, including invalid UTF-8. It does not itself read the navigation `MultiPage` property, so raw NavWidgetType255 remains unchanged.

## Bounds, application and scope

Source values must satisfy the supplied unit specification. Every scene header and item must lie within the 232-byte bucket, and all eight repacked records must fit. The original permissive out-of-range pointer behavior that reads zero padding, and source SceneCount255 outside the specification, are explicitly excluded. They are negative scope cases, not acceptance passes.

Apply re-derives the canonical plan, rejects forged fields, different schema/identity or stale full PP values, then stages and verifies final changes. Ordinary errors attempt restoration only while connected and report rollback failures. `KeyboardInterrupt` and `SystemExit` retain their original exception and `edlt_lifecycle_evidence`, attempted parameters and uncertainty; no recovery I/O or replay follows interruption. An interrupted rollback also preserves the original failure.

`model_cycle_complete` covers only the named model phases. Full WinForms initialization, UI palette selection, validation dialogs, database auto-population, runtime firmware-version queries, dynamic icon uploads and network saves are outside this helper's scope. An apply result has `verified=true`, `saved=false` until an explicit database save.

## CLI

```sh
cbus-toolkit edlt lifecycle-requirements parameters.json
cbus-toolkit edlt lifecycle-plan parameters.json --metadata cache.json
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-lifecycle --metadata cache.json
```

Remove `--dry-run` to apply and save through the explicit native database workflow. JSON input is bounded and duplicate keys are rejected. Metadata syntax is checked before entering the programming session; required facts are then checked against the complete source snapshot. Database destination restrictions remain in force.

## Evidence and current acceptance state

[NativeEdltLifecycleProbe.cs](../research/NativeEdltLifecycleProbe.cs) calls the unchanged original unit constructor and full model lifecycle with owned original cache objects. Only the outer network constructor is bypassed to avoid its I/O; cache collections, original application/group/level constructors and original population methods supply its data. Missing metadata auto-add is disabled, mutation-request delegates throw, and no network connection is supplied. The Docker backend disables networking; the explicit Windows backend uses owned file jobs without a network listener. An owned Bitmap object exercises image presence; no physical endpoint or USB device is accessed.

Original probes use native `0x` PP value tokens. Supplying decimal fixture tokens changes the original CRC reader's interpretation and is a harness error; earlier research output is retained separately and is not final CRC acceptance. The test image is the same pinned owned Mono/WinForms image used for the Quick Status probe, SHA256 `23a8bfba16d732eff819f71edeec551e84e576eab40a15ec9e97018f649fb568`.

The final combined helper and CLI suite passed **19 tests with zero skips** on Python **3.13.14** (832.057 s) and **3.10.20** (826.124 s). Each run checked 76 original cases: **66 supported full model cycles**, **eight exact original failures**, and **two source patterns outside the supported bounds**. It also checked **2,048 Enable constructor combinations**. All three accepted model phases matched every one of the 874 PP fields. The eight negative cases had to match their native exception type, phase, exit status and complete partial-state evidence; they are not successful supported workflows.

Each Python version also passed **34 original-Windows/macOS-C-Gate cases**, comparing all 874 fields, all five CRCs and exact Widget6 raw bytes. The final complete snapshot survived database save/close/load. The native cases used separate disposable projects, retained `state=new`, and never opened a physical network. These checks total **203,642 parameter comparisons and 500 explicitly counted CRC-value comparisons per Python run**, in addition to the constructor matrix and pure/CLI assertions. The compact record is [edlt-lifecycle-acceptance.json](../research/fixtures/edlt-lifecycle-acceptance.json).

The explicit test environment `CBUS_EDLT_LIFECYCLE_ORIGINAL_BACKEND=windows` selects the original Windows .NET 4.8/x86 fixture; the default Docker backend remains available. Final Windows full-phase reports are `original-windows-313-report.json` and `original-windows-310-report.json`; Windows-original/macOS-C-Gate persistence reports are `native-macos-windows-313-report.json` and `native-macos-windows-310-report.json`, all under `research/runtime/edlt-lifecycle`. Each has an owned proof directory containing source, test, specification, executable and runtime hashes, exact commands/results and complete stdout/stderr. The Python bridge, C# runner and v2 runner executable were captured before execution and checked unchanged after every original case and after the final run. The original 25-file vendor manifest is pinned separately.

```sh
CBUS_EDLT_LIFECYCLE_ORIGINAL_BACKEND=windows \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_CGATE_TEST_PORT=20033 \
PYTHONPATH=src:tests:. python3 -m unittest \
  tests.test_edlt_lifecycle tests.test_cli_edlt_lifecycle
```

This requires the explicitly running [owned Windows research bridge](windows-native-oracle.md) and separate macOS C-Gate service. It does not start a VM or access an installed Toolkit session. The macOS service uses checksum-verified portable ARM64 Temurin 11 with six loopback-only listeners; [local-native-oracle.md](local-native-oracle.md) describes process ownership and cleanup.

Historical incomplete runs remain preserved. The first Windows run completed 2,048 constructor checks and 53 cases before a v1 admission race prevented the next model process from launching; its 281 recovered job/probe files are retained under `windows-run-1-transcripts`. Its changing helper provenance was not reused. A subsequent complete original matrix passed, but its combined suite caught a native test setup typo (`reset` instead of `reset_defaults`). That run is retained under `windows-run-2-native-fixture-error`. After correcting the test call, the entire final suite passed on both Python versions with unchanged production code. Vendor binaries and specifications are not redistributed.


The additive retained-state extraction subsequently passed **45 tests with zero skips** on Python **3.13.14** (868.762 s) and **3.10.20** (964.082 s). This combined the complete 19-test Lifecycle and 16-test Restore suites with ten state/compatibility tests. Each run repeated the 76 original Lifecycle cases and 2,048 Enable combinations, 34 native Lifecycle cases, 15 native Restore save/close/load cases, and 64 captured original Restore cases: **506,046 parameter comparisons per Python**, excluding the separate backward-equivalence hashes and CLI assertions. The 2,124 backward cases compare the prior accepted Python implementation; they are compatibility evidence, not an independent vendor oracle.

The state tests cover private scene action `-1`, shared cached group identity, distinct aliased scene slots, stored versus actual widget type, separate page-widget identity, cached MRA values, opaque text, immutable issued-state ownership, no second load or group resolution, and preserved rollback interruption evidence. All scoped source, probe, runtime and fixture hashes remained unchanged throughout both final runs. The compact record is [edlt-lifecycle-phases-acceptance.json](../research/fixtures/edlt-lifecycle-phases-acceptance.json); complete reports and copied inputs are under `research/runtime/edlt-model-phases/acceptance-v2`.

An earlier 45-test Python 3.13 run passed its assertions but was correctly rejected by the outer provenance check because an imported test file changed during execution. That historical run remains under `acceptance-v1` and is not the accepted extraction checkpoint. Both Python versions were then run again against the frozen inputs recorded above. This extraction adds no application-control, Corridor, physical-programming or full-dialog claim.

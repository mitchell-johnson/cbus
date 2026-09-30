# IOPE, eDLT templates and firmware failure evidence

This batch follows `c6c1fb1d` and integrates nine audited source revisions.
It completes the public registration of bounded IOPE components and local
template interfaces, and adds safe lifecycle diagnostics for failed firmware
updates. These are functions inside unfinished capability areas; the broad
ledger remains 18/42 (42.86%), and functional coverage is still unmeasured.

| Source chain | Implemented scope | Remaining acceptance |
| --- | --- | --- |
| IOPE `690b0965` → `1b512236` → `3847d499` → `18d78566` | Environment, output turn-on/restrike, logic, join recovery, block timers, existing join groups, retained scene selectors and levels; registered `iope-workflow` parser/dispatch matches the standalone CLI. | Complete input/template/parent transactions, whole SceneManager/IOPE scene serialization, missing graph creation, external scene pointers, dependent ramp/recall/scene expiry and hardware timing remain open. |
| eDLT templates `7a23fb5d` → `48112a9c` → `10cbfa07` → `d951e882` | Bounded XML format/CRC, export/inspect/preview, ordered assignments, second-model staging, Reset provenance and terminal normalization and guarded offline Save predicates; public CLI and separate parent local stager registered. | Apply is refused before input reads. Initialized controls and runtime serial/Scene/unit validation, callback outcomes, joined SaveDialog/BeforeSave and original full success/failure/cancel acceptance remain open. Uncommitted owner investigations are excluded. |
| Firmware `3e658045` plus integration privacy fix | Failure and cancellation retain primary errors/exit codes and add bounded transfer/release facts plus a validated read-only journal snapshot. New secondary error fields use fixed labels; secret-bearing backend text cannot enter this projection. | Source/fake-device evidence is separate from original updater, physical USB, bootloader and vendor payload acceptance. No diagnostic authorizes replay or acquires hardware. |

IOPE admission is IOPE1R1/IOPE2R2/IOPE2C4 at exact catalogue/schema identity and
firmware 1.0.00–1.2.99. Native matrices cover nine type/revision combinations
at 1.0.00, 1.1.00 and 1.2.00. Scene components require the documented complete
positive four-scene/eight-command graph. Selectors consume action Address,
independently of Value; unchanged displayed percentages preserve raw levels.
See [IOPE scope](iope-integration-scope.md) and [workflow contract](iope-workflows.md).

The separate [Save-validation stage](edlt-template-save-validation.md) models
serial → Scene-widget → unit order with frozen caller facts, lazy getter
short-circuit rules and explicit mutation/refusal boundaries. It does not
attest initialized controls or admit Apply.

The [template contract](edlt-template-integration-boundaries.md) preserves
issuer-bound immutable stage identities, raw token history, cancellation and
all five terminal CRCs without claiming an applying workflow. The historical
terminal native receipt proves one synthetic image's database durability; it
is a sanitized derivative retaining its original hash and outcomes. Fresh
native image durability must be recorded separately from template Apply.

The [firmware diagnostics contract](firmware-cli-error-evidence.md) retains
failure state without payloads, identity or private backend strings. Its new
privacy regression first reproduced the leak, then passed after fixed error
labels were introduced. Attached original receipts and primary errors are
unchanged. Package snapshot, resume admission, codec and release regressions
remain part of the combined focused verification.

## Acceptance records

The [combined acceptance](iope-template-firmware-acceptance-2026-10-01.json) and
[root validation](iope-template-firmware-root-validation-2026-10-01.json) bind
the final 316 package files, installed imports, 2,694 frozen reference inputs,
raw artifact hashes and each public sanitized derivative. Both Python 3.13.14
runs passed **642 normal test nodes and 1,951 subtests**, with zero failures or
skips. This was a focused selection of 54 modules plus seven exact DALI/parity
guards, not a full suite. All five newly required native-manifest declarations
passed. The wheel SHA256 is
`fa561df17d180c4f3539ad8ac3befadc63b27bed0ac6138f09daf539e8090800`.

Four underlying IOPE matrix methods generated five matrix call nodes because
the scene-level module imports the public workflow test class. Both workflow
calls passed; its raw report retains the last successful write. The 642 count
measures distinct collected node IDs, not unique method definitions or
functional coverage. The aggregate retains precollection AST estimates
(582/584) as planning history; its actual source/wheel results supersede them.

Five nodes were excluded before execution: four original instruction/runtime
producers and the out-of-scope optional parent-metadata native test. The receipt
lists their exact IDs separately. There were no observation-triggered reruns.
The explicit native backend used owned closed synthetic projects; original
Mono/proxy/JIT producers and physical hardware were not executed.

Fresh native IOPE derivatives record source and wheel results for
[workflow](iope-native-workflow-source-2026-10-01.json),
[logic](iope-native-logic-source-2026-10-01.json),
[join groups](iope-native-join-groups-source-2026-10-01.json) and
[scene levels](iope-native-scene-levels-source-2026-10-01.json). Their paired
wheel files and raw/public hashes are mapped by the root validation. The
[Reset prelude](edlt-template-reset-prelude-source-2026-10-01.json) compares all
44 retained original vectors in both contexts; it does not freshly execute
original instructions.

The separate [source terminal proof](edlt-template-terminal-native-source-2026-10-01.json)
and [wheel terminal proof](edlt-template-terminal-native-wheel-2026-10-01.json)
each compare **874 parameters and five CRCs** after a fresh project reload,
with one PP/project save, zero CNI connections and owned-resource cleanup.
Actual imported implementation hashes match the helper's reference hashes.
This proves one synthetic terminal image's database durability per context;
template Apply, original Save validation and complete parent lifecycle remain
explicitly false.

The firmware privacy regression preserved a real red result (10 passed,
one failed), then passed 11 tests/15 subtests after the fixed-label change;
see its [separate receipt](firmware-error-diagnostic-privacy-2026-10-01.json).
The historical terminal receipt retains its original raw SHA256 and unchanged
technical hashes/outcomes in a declared sanitized derivative. Five private
reproduction paths in a supporting document were normalized before the
acceptance freeze, with both document hashes recorded. Initial external
preparation was rejected before execution; the approved preparation created
a minimal explicit environment and public dependency links without copying
prior private environment files, credentials or vendor binaries. Raw artifacts
remain private. Subsequent changes are publication documentation and evidence
only; the root audit records their differences from the frozen references.

Results are not added to earlier overlapping checkpoint counts. Historical
summary hashes bind their own source revisions and are never rewritten to
appear current. New public dispatch tests cover actual CLI JSON equivalence,
preconnection refusals, exclusive file output and local staging/cancellation.

Static source inspection, retained original vectors and owned closed-project
native execution are distinct evidence. Original instruction/Mono/proxy/JIT
producers are excluded before execution. No live C-Bus network, original full
GUI or physical device acceptance is implied. The strict parity register stays
incomplete; [implementation status](implementation-status.md) and the
[path to 100%](../../docs/parity-review-and-roadmap.md) retain remaining work.

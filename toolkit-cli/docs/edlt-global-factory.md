# Bounded eDLT Global factory preparation

The factory bridge prepares KEYGL5 / 5055EDL / firmware 5.5.00 Global Programming from an existing source database snapshot. It follows the captured original factory model path: initial load, conditional Project initialization, silent Reset with new widget/scene models, removal of the Global tab, explicit cached-network Project assignment, retained-model save and source CRCs. Each issued preparation performs exactly two model loads. It does not execute a form, renderer, metadata discovery or physical programming.

```python
from cbus_toolkit.edlt_global_preparation import (
    EdltGlobalPreparation, GlobalPreparationContext,
)
from cbus_toolkit.native_global_programming import NativeEdltGlobalProgramming

manager = NativeEdltGlobalProgramming(client, spec)
context = GlobalPreparationContext(
    source="//SOURCE/254/p/20",
    form_project="SOURCE",
    cached_network_project="NetPrj",
)
prepared = EdltGlobalPreparation(spec).prepare_factory(
    raw_parameters,  # all 874 original PP strings, in original parameter order
    metadata=application_cache,
    context=context,
    global_engine=manager.engine,
)
source = manager.engine.prepare_factory_source(prepared)
payload = manager.engine.select(source, categories=("key-settings", "colour"))
plan = manager.plan(
    payload, ["//SOURCE/254/p/21", "//SOURCE/254/p/22"],
    source_database=context.source,
    exclusive_project=True,
)
review = plan.as_dict()   # read-only; does not create a backup or save a target
result = manager.apply(plan)  # creates a fresh project backup before target writes
```

The caller must own project editing/reloading exclusively during planning and application. This is a caller prerequisite, not a claim of server-wide session locking. All destinations must already exist, be materialized, and belong to the same closed database project. The exact source path is mandatory and is excluded from destinations. Exported JSON is for review; only intact objects issued for the same engine can be applied.

The current source guard accepts six complete observed nonidentity patterns: the original default-like source and the captured rich Scene/MRA, first-MRA, Enable, mixed Shutter/Fan/Timer/MultiLevel and type127 fallback sources. These patterns cannot be combined field by field. Initial NavWidgetType must be255, and the complete ordered schema/default layout is pinned. Identity fields are retained separately. The initial dirty history is empty; the bridge does not accept arbitrary edited form state. Missing required cache facts or a different pattern/order fail before database I/O.

This path currently creates the original default template and selects categories to copy. It has no post-Reset user-control edit stage. The captured source patterns converge to the same default OEM settings and Time/Date widget while retaining their original source preconditions and distinct Project sidecars. Composing later control edits with those retained models is separate work.

The existing [unbound Global helper](edlt-global-programming.md) and [partial Project methods](edlt-global-preparation.md) keep their behavior. They do not silently acquire factory initialization.

## Raw state, identity and Project

`prepared.expected_raw` preserves every original PP string, including trailing Project tokens and initial NavFF. `prepared.raw_phases` records the source-coded raw token, getter, dirty and initialization states. With Global selected, NavFF survives initial setup and Reset; only removal of that tab reads MultiPage and changes it to0. A fresh post-Reset model supplies the save operation; there is no third AfterLoad.

The original Project setter overwrites token positions without removing an old tail. For example, `OLD TAIL` assigned `NetPrj` becomes `NetPrj TAIL`, while the private backing string is `NetPrj`. This raw sidecar can exceed the legacy six-bit field's eight-character physical limit. The unchanged memory codec sees the original valid Project only in the explicitly named OEM projection; the actual raw sidecar remains visible, and no physical encoder is relaxed. Project is excluded from the Global payload and does not retarget database operations.

The explicit cached-network Project setter and category dirty markings are composed at their original logical preworker position. Their terminal result was independently compared with actual original factory workers. Python does not claim to execute the original binding callbacks or reproduce arbitrary mutable UI histories.

## Category payload and database verification

All four category allowlists retain the existing helper's exact membership. Every selected parameter and source OverallCRC is sent in captured attribute order, even when numerically unchanged. Zero GlobalParameterCRC is appended last. Original decimal boolean, uppercase default and lowercase CRC spellings are preserved and validated against their typed numeric values before sending.

The complete source section CRCs remain distinct from the filtered destination payload. The destination receives source OverallCRC and zero GlobalParameterCRC, retaining its other three section CRCs. This does not establish that the entire destination has internally valid full-unit CRCs. Unselected fields, shared raw bits, identity and metadata remain destination values.

Native planning and application compare the source's exact874 PP strings in addition to XML and numeric preconditions. Numerically equivalent respelling is a stale source. Planning rejects a baseline that needs materialization rather than silently normalizing it. Application creates a fresh backup, checks all targets before the first mutation, stages the exact literal payload, verifies all874 values plus relevant raw/CRC bytes, saves, closes and reloads the project, then independently verifies the destination again.

A definite rejected PP SET stops before save. A save/transport interruption preserves evidence and does not replay the write. The batch is non-atomic: earlier verified destinations remain reported if a later target fails. Reusing one frozen prepared payload for multiple targets does not imitate repeated mutable-form save history. The original worker can report completion after a rejected PP SET; that negative oracle is explicitly not the Python success condition.

## Evidence scope

[Factory vectors](../research/fixtures/edlt-reset-factory-rich-vectors.json) pin five whole rich source families, 17 original raw/token/dirty/initializing stages and ten actual all/empty worker captures. The separate handler/component recreation matches every874-field actual post-factory state; it is not mislabeled as an actual mid-factory hook. Full worker terminal states and ordered literal payloads also match independently on Python3.13 and3.10. The [Reset dependency acceptance](../research/fixtures/edlt-reset-factory-dependency-acceptance.json) records its own dual68-test evidence.

The remaining category masks reuse the independently verified original category logic and values; they are not presented as sixteen new full-factory executions. Original assembly, source, runtime, runner, probe, input and output hashes are retained under `research/runtime/edlt-global-preamble/factory-rich`. All original peers were owned strict numeric loopback endpoints with no forwarding. Native acceptance uses only disposable closed projects. No physical device or user project is used, and no physical compatibility or full Toolkit parity claim follows from this bounded workflow.

The [final acceptance record](../research/fixtures/edlt-global-factory-acceptance.json) covers 77 tests on Python 3.13.14 (217.219s) and 3.10.20 (263.052s), with zero failures or skips. Both runs used separate C-Gate children with six verified loopback listeners, no adopted projects and confirmed process/work-directory cleanup. All 53 loaded source files and 285 inputs matched across runs and were archived with a verified hash manifest before releasing the development freeze.

Native tests verify all 874 destination and backup values after save/close/load, exact literal writes, unchanged source XML and rejection of numerically equivalent source respelling. A definite native rejection on the second destination preserves the first verified save, leaves the second unchanged and does not replay. Both ordinary and factory CLI workflows are included. Earlier source-boundary, subprocess import and native fixture failures remain separately recorded; they are not counted as successful acceptance runs.

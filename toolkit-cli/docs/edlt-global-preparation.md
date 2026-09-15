# Partial eDLT Global Programming source preparation

The partial methods in `edlt_global_preparation.py` model the original Project parameter's raw token, backing-string and dirty-flag behavior for KEYGL5 / 5055EDL / firmware 5.5.00. They also record the selected category field set forced dirty by the original preamble. These methods perform no I/O, Reset or factory initialization. The separately named [factory bridge](edlt-global-factory.md) now composes a bounded issued factory dependency; it does not change the partial methods below.

The existing [Global Programming helper](edlt-global-programming.md) remains the accepted model/category workflow and preserves the supplied source Project. This new module does not change that behavior or expose a CLI command.

```python
from cbus_toolkit.edlt_global_preparation import (
    EdltGlobalPreparation, GlobalPreparationContext,
)

engine = EdltGlobalPreparation(spec)
source = engine.begin(
    raw_parameters,  # all 874 original PP strings
    context=GlobalPreparationContext(
        source="//SOURCE/254/p/20",
        form_project="SOURCE",
        cached_network_project="NetPrj",
    ),
)
initialized = engine.initialize_project(source)
preamble = engine.project_preamble(
    initialized,
    destination="//SOURCE/254/p/22",
    categories=("key-settings", "colour"),
)
review = preamble.as_dict()
```

These calls are explicitly partial state observations. They do not reproduce the intervening form setup or Reset. `expected_raw` retains the exact external snapshot, including empty/trailing Project tokens. `raw_model_projection` contains the modeled getter value after the explicit Project phases. All other 873 raw parameter strings are unchanged. Source path, form project and cached Network.ProjectName remain separate explicit values; PP Project never retargets a database operation. Destination must be a canonical unit path in the same explicit project/network.

`ProjectState`, `assign_project()` and `initialize_project()` can also be used independently. The original setter overwrites supplied token positions without truncating a previous tail. Thus `OLD TAIL` assigned `NetPrj` becomes `NetPrj TAIL`; eight spaces initially have an empty getter, but assigning a form name preserves the eight trailing empty tokens. The final private backing string is just the requested assignment. It is distinct from both the PP getter and the immutable original source path.

Equal assignments preserve an existing dirty flag. Changed token positions mark the parameter dirty and emit original notifications only outside initialization mode. `notification_states` records the states immediately before each original notification, with the old backing string; it does not execute callbacks. The original negative fixture proves why this matters: a failing timer notification leaves the PP changed before the private backing assignment occurs. Missing Project PP is representable by the standalone sidecar; the complete-profile preparation engine rejects missing parameters.

The original PP aliases (`0xffffffff`, `$x...`, `$...`) and getter handling of empty tokens are retained. Inputs use exact booleans, bounded text and token counts. Canonical full paths, complete schema-valid raw baseline, known unique dirty names and categories are validated. Engine receipts are immutable and owned by their issuing engine; copied/replaced/cross-engine states and review JSON are not accepted as issued phases.

`forced_parameters` records category membership plus OverallCRC, even when values are unchanged. It does not claim the original PP SET wire order, calculate a CRC or append the later GlobalParameterCRC zero. Source parameter order is retained separately. The completed original worker can report completion after a rejected PP SET; that weak result is captured in the vectors and is not a Python success condition.

Raw Project can exceed the physical six-bit field's eight-character limit after the original setter. The sidecar keeps that evidence without relaxing the memory codec, truncating tokens or claiming the full model is physically encodable. Every export marks `source_preparation_complete`, `initial_factory_binding_applied`, `reset_applied`, `before_save_applied`, `global_bridge_enabled`, `saved` and `physical_device_verified` false. Exports are review-only.

## Original factory phase boundary

The original Windows research now distinguishes the navigation transition from initial setup. With the Global tab selected, the captured NavWidgetType remains `0xff` through load, bindings and control setup. Original Reset changes its spelling to `0xFF` and marks it dirty. Removing the Global tab then selects the next page; real WinForms binding calls the original MultiPage getter and writes `0x0`.

A separate original recreation measured all 874 raw values, token arrays and dirty flags after removal. They exactly equal the independently captured `CreateUnitsDialogWithDefault` → `LoadUnit` → global `SetEDLTFrm` output. Immediately before removal only NavWidgetType differs. Its terminal 873 non-Project raw values/tokens equal the actual completed factory-worker result; Project and category-forced dirty history are separate phases. The earlier diagnostic's manual Widgets selection is preserved and explicitly does not establish a pre-Reset factory transition.

The ordinary [Reset helper](edlt-reset.md) keeps its initial Nav0/1 and partial-dialog guards. Editing an FF baseline to bypass those guards would discard the original state and move the transition to the wrong time. The separate factory dependency instead uses an exact issued `GlobalFactoryContext`, bound to the original full raw snapshot, shared Reset/lifecycle/specification, metadata and dirty state. `factory_context()` issues that receipt without executing Reset. The separately documented `prepare_factory()` executes the qualified composition while retaining the source baseline, original Global-tab order, fresh model identities and Project sidecar. Partial `begin()`, `initialize_project()` and `project_preamble()` still export false bridge flags.

## Evidence

[Fixed vectors](../research/fixtures/edlt-global-preparation-vectors.json) contain ten original partial Project cases, two actual factory Project paths and three completed original workers (all categories, none and a definite PP SET rejection). The worker fixtures retain exact literal field order, raw spelling and source CRCs. The original failure after PP mutation remains a separate negative case.

The bounded Windows jobs use the exact Toolkit 1.18.0.2754 / CBusLogicModel 7.14.0.0 assemblies and pinned .NET runtime files. Owned peers are numeric loopback only, strict nonforwarding, and reject unexpected grammar. The tab-removal probe permits the original session handshake and returns401 to its status query; its one connection, two requests, clean EOF and joined cleanup are recorded. No user projects or physical devices are used.

Reproducible analysis and complete pinned source/executable/input/output/runner evidence remain under `research/runtime/edlt-global-preamble`, including `analysis.json`, `factory-analysis.json`, `factory-worker-analysis.json` and `tab-removal-analysis.json`. The [preparation acceptance fixture](../research/fixtures/edlt-global-preparation-acceptance.json) records the final Python test runs and source hashes. Full arbitrary form histories, fresh cache discovery, image loading, the Delphi wizard and physical transfer are outside this module's scope.

The original partial-foundation checkpoint passed 12 tests with zero skips on Python 3.13.14 (0.937s) and 3.10.20 (1.212s), with its loaded source and vector hashes unchanged. That historical acceptance predates the append-only context and factory bridge. The tests execute no Windows job, C-Gate request or physical operation; they compare against the previously captured original artifacts.

The later [factory bridge acceptance](../research/fixtures/edlt-global-factory-acceptance.json) includes these unchanged partial-method tests, issued context and factory preparation, original raw/dirty comparisons, and closed-database/CLI verification: 77 tests pass without skips on each Python version. Its exact source and input files are archived independently of subsequent development.

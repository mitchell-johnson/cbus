# eDLT Reset Unit controls

`EdltResetControls` implements the original synchronous **Reset Unit** control sequence for KEYGL5 / 5055EDL / firmware 5.5.00, followed by the original model save rules and five CRCs. It operates on an explicit, bounded local control context. It does not send the physical Factory Reset command.

```sh
cbus-toolkit edlt reset-plan source.json --metadata application-cache.json --active-tab widgets --binding-variant audited-local-wiring
cbus-toolkit cgate --host 127.0.0.1 --port 20033 unit --source /db//PROJECT/254/p/20 --lock-address //PROJECT/254 --dry-run edlt-reset-controls --metadata application-cache.json --active-tab widgets --binding-variant audited-local-wiring
```

The native operation supports database destinations only. The normal unit save options apply. Native `--dry-run` stages and verifies the temporary programming session, then discards it without a persistent save. Offline planning performs no I/O.

## Required context

Both `--active-tab` and `--binding-variant` are required. Tested tabs are `widgets`, `general`, `standby` and `colour`. The two binding variants are `base-c3` and `audited-local-wiring`; they distinguish the original probe's base partial setup from an additional, source-audited set of local WinForms bindings. Both variants preserve the same tested terminal values, but their phase records and provenance remain separate. Neither denotes a fully initialized or rendered Toolkit dialog.

The initial navigation value must be 0 or 1. Supported initial stored widget types are 0, 2, 6, 7, 8, 10 and 255. Other types and unknown initial navigation modes are rejected because their selected-control initialization has not been proved by this Reset matrix. The generic lifecycle helper has a wider, separately verified model scope.

Metadata uses the complete ordered [application cache](edlt-applications.md) envelope, including lifecycle facts. `requirements(raw, active_tab=..., binding_variant=...).as_dict()` reports exact required application/group lists and model facts without I/O. Bound control groups need positive, named cache entries; unknown and absent are distinct. The cache must include complete application and relevant group lists, including the reset defaults' dependencies. Populated level/dynamic-label facts follow the [lifecycle cache contract](edlt-lifecycle.md). No groups are created or fetched, and caller cache freshness is not verified.

Repeat `--dirty-parameter NAME` for parameters already marked changed in the declared local editor state. The default is an empty list. This is caller-supplied state, not a reconstruction of a prior Toolkit session. Unknown or duplicate names are rejected.

## Raw parameters and results

Reset needs all 874 original PP strings. `raw_document()` creates the following envelope; the existing native `cbus-cli-parameters-v1` export is also accepted with the same exact profile and string-valued parameters:

```json
{
  "format": "cbus-edlt-raw-parameters-v1",
  "unit_type": "KEYGL5",
  "catalog_number": "5055EDL",
  "firmware": "5.5.00",
  "parameters": {"UnitName": "OLDUNIT ", "NavWidgetType": "0x1"}
}
```

The abbreviated example omits the other required fields. Numeric arrays are not an equivalent input: raw casing, decimal versus hexadecimal spelling, spaces and dirty flags affect the original control sequence. Numeric fields accept decimal or `0x` tokens separated by single spaces, subject to the native field bounds. Input is bounded to 256 KiB of parameter strings and the complete specification. Text fields must also satisfy the supported native encoding and length constraints.

Each `ResetPhase` retains immutable token arrays, the original `PPAttribute.Value` string projection, dirty parameter names and `bInitialiseMode`. Its token sidecar distinguishes leading empty tokens that the original getter collapses from trailing empty tokens it preserves. The external raw input remains the stale-state baseline even if that getter projects a different string. Oversized Project backing strings from the full Global Programming factory remain outside this codec-valid input scope.

Plans expose input, load, binding, pre-reset, component, after-reset, before-save and final phases. They preserve exact default spelling: for example, the specification's uppercase `0xFF` is materially different from the original reset special case's lowercase comparison. `changes` contains numeric/text differences for native staging; full raw phase state remains available separately. Native readback verifies values, not C-Gate's choice of equivalent numeric spelling.

## Original behavior retained

Reset excludes UnitAddress, SerialNumber, Project, NetworkAddress and both configuration-version fields from its default assignment. Earlier AfterLoad normalization can still affect configuration values. UnitName is reset. Reset applies defaults in specification order, clears byte 1 of the old 21 widget objects, invokes the original fresh AfterLoad sequence, then selects Widget10 as single-slice Time/Date with byte 1 exactly `0x2`.

The legitimate `EdltLifecycle.reset_unit_controls(loaded, reset_context=...)` transition issues a `ResetEdlt` receipt owned by that engine. It retains the original expected snapshot and the explicit raw/control context, while recording the original creation of 21 fresh widget models and eight fresh scene models. Terminal `prepare_save()` consumes the issued reset state; it does not perform another load. Copied, replaced, cross-editor and forged context receipts are rejected. Existing load/save and Blank transitions are unchanged.

The selected tab matters. Widgets and General trigger the original mutating MultiPage getter after defaults, producing terminal NavWidgetType `0x0`. Standby and Colour retain `0xFF`. General also refreshes the 16 restore-level controls before Reset, which can change raw hexadecimal casing without changing the numeric value. The prior EnableLevelStore branch is recorded before defaults. The six active brightness/colour groups remain unchanged during the tested BeforeChange branch and are subsequently reset by their defaults.

Raw snapshot capture does not cause navigation normalization. The independent trace places the Widgets getter inside the AfterChange application-list notification and WinForms binding path; General reaches it through its tab handler and restore-group refresh. Forty before/after snapshot checks retained every token, dirty flag and initialization flag. No untested tab is inferred from those results.

Application validates profile, cache, full snapshots and canonical replay before PP writes, then checks the complete raw stale baseline. Failed ordinary staging attempts rollback while the connection is usable. Interruptions preserve the original exception and partial evidence without recovery I/O; `last_evidence` supplies a fallback when the exception refuses attached attributes. CLI finalization records save attempted, save confirmed and cleanup separately. A confirmed save remains recorded if later cleanup fails.

## Evidence and limits

The original probes run unchanged Toolkit 1.18.0.2754 / CBusLogicModel 7.14.0.0 assemblies under owned Windows .NET, with the 25-file vendor manifest, x86 executable, input/output and source hashes retained. The controlled factory is pinned before construction to one numeric-loopback peer. That peer accepts the exact session handshake and returns 401 to the original PSYNC request: one connection, two requests and 72 bytes. Unknown requests fail the probe. The original timers are stopped, the connection factory remains pinned through process exit, and cleanup joins the peer. There is no forwarding, physical endpoint, SetEDLTFrm/LoadUnit stage or renderer flush in this accepted partial-dialog context.

[NativeEdltResetMatrixProbe.cs](../research/NativeEdltResetMatrixProbe.cs), [the edge probe](../research/NativeEdltResetEdgesProbe.cs) and [navigation trace](../research/NativeEdltResetNavigationTrace.cs) provide 44 executions and 520 raw/dirty phases, covering 454,480 parameter-phase comparisons. Separate unchanged-handler and original component-sequence arms agree across empty/rich scenes, MRA, static text, layouts, default casing, previous level storage and equal Quick Status thresholds. [Captured vectors](../research/fixtures/edlt-reset-windows-vectors.json) preserve these results without invoking the Python implementation as their oracle.

The earlier malformed-default original failure, unanswered-session C1 watchdog failure, C2 intentional diagnostic stop and C3 partial setup remain preserved under `research/runtime/edlt-reset-controls`. A Python native-pilot environment failure also remains separate; it was a relative provenance-directory rejection before project creation or original execution. These are not counted as passing terminal reset cases.

Full form initialization, redraw/event-loop completion, Global Programming factory setup, arbitrary prior binding histories and physical Factory Reset remain unverified by this helper. A factory source with initial NavWidgetType 255 must not be rewritten to 0 merely to pass this API's guard; that factory's distinct initialization requires its own evidence and transition.

Final acceptance passed 55 tests with zero skips on Python 3.13.14 (254.498s) and 3.10.20 (301.466s), with all pinned source hashes unchanged. Each run includes 18 Reset/module/vector/native/CLI tests plus 37 retained Lifecycle/Blank regressions, including the exact 2,124-case prior lifecycle comparison. Four fresh original/native cases per Python compare all 874 fields at ten raw/dirty phases, then apply Python results and verify all 874 values, five CRCs and 274 raw bytes before and after database save/close/load. The independent CLI native case also verifies raw export, preview and persistence. Every test network remains closed (`state=new`). [The compact acceptance fixture](../research/fixtures/edlt-reset-acceptance.json) records exact reports, source, vendor, executable and input/output provenance; full logs remain in `research/runtime/edlt-reset-controls/acceptance-v1`.

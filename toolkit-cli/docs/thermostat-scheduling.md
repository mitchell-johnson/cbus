# Thermostat scheduling workflow

The `thermostat-scheduling` commands operate on resolved thermostat state supplied as JSON. They implement the selection predicates, ordered On/Off/Override level creation, and caller-owned save-lock release. The original unit-load rules are now captured separately; production composition with native loading/saving and the complete settings workflow remains outstanding.

```json
{"groups":[{"identity":"schedule","address":12,"levels":[]}],"roles":{"on":"schedule","off":null,"override":null},"enabled":true}
```

```sh
cbus-toolkit thermostat-scheduling selected state.json
cbus-toolkit thermostat-scheduling required state.json
cbus-toolkit thermostat-scheduling load raw-load.json
cbus-toolkit thermostat-scheduling load-create-levels raw-load.json
cbus-toolkit thermostat-scheduling create-levels state.json --policy button
cbus-toolkit thermostat-scheduling create-levels state.json --policy direct
cbus-toolkit thermostat-scheduling end-save-lock locked-state.json
```

An input can also include `save_lock` (0–2) and `pending_save`. The CLI performs no storage writes. The Python `ThermostatScheduling` API accepts level-save and storage-save callbacks; its returned state can be passed to the same manager for lock release. Callbacks receive detached snapshots, and a failed partial state cannot be resumed.

`load` accepts supplied raw scheduling bytes, an explicit `application_present` Boolean and the resolved application group collection. Groups may include their existing `levels`; the command preserves them in `scheduling_state`. It replays the captured `AfterLoad` normalization and resolution rules, reports any application/group objects the original path would save, and emits state in the exact shape accepted by the other commands. Optional `--group-name` and `--unused-name` values supply labels for newly planned groups; the command does not infer localized Toolkit resources. It does not read a unit, invoke inherited loading or perform any save.

`load-create-levels` performs that load and then runs the retained outer and inner scheduling operations in one command. It preserves supplied levels, creates the missing addresses 1–31 for On, Off and Override in role order, and returns both phase records plus the final state. `--policy button` applies the captured enable/required gate; `--policy direct` enters the outer operation unconditionally. This combined operation remains an offline plan with no save providers or native writes.

`selected` ignores the enable flag and looks for the first non-null group whose address is not 255. `required` first checks the enable flag, then checks for missing level addresses 1–31. Address and Value are distinct: existing labels and values do not make a complete address set require creation. Address 0 is actionable; 255 is the unused sentinel.

The button policy calls the required predicate before entering the outer operation. The direct policy enters regardless of enable state. Both process On, Off and Override in order. Shared group references are visited again, preserving labels created by the first role. Each role uses the existing inner engine and its own save lock; a caller lock can defer all storage saves until explicitly released. A depth-two caller lock therefore produces depth-three callback snapshots. Failure retains that depth and the first exception instead of reporting an evidence-export error.

## Evidence

Both the current-tree and [fresh installed-wheel focused run](../research/experiments/2026-09-24/installed-wheel-focused.json) pass **46 tests** on Python 3.13: 20 outer-model methods, nine CLI methods and 17 existing inner-engine methods. It replays the 12 earlier predicate captures and 12 new original outer-workflow captures, comparing final group state, counters, role order, semantic getter/predicate events and every save callback in order.

The new original-code capture executed **1,132,016 instrumented instruction/provider events** across 12 cases in a network-denied process. It includes disabled and empty selections, complete and incomplete groups, shared roles, unused and extra addresses, deferred saves, a second-storage denial, and a denial on the 65th level-save request. All 71 archived inputs were verified unchanged and the child was reaped. [Capture summary and source hashes](../research/experiments/2026-09-24/thermostat-outer/capture-summary.json), [retained original vectors](../research/fixtures/thermostat-scheduling-outer-vectors.json).

The first attempt stopped at an omitted trailing return instruction in the research harness. That failed report remains retained; the revised harness admits two disassembly-verified trailing returns without changing the original instruction bytes, providers or case hypotheses. [Correction record](../research/experiments/2026-09-24/thermostat-outer/preparation-note.json).

This original execution uses resolved object references and declared providers for UI requests, object allocation and persistence. It does not prove cold unit loading, application/group factories, actual VCL dispatch, Delphi exception unwinding or physical-device behavior. The separate [native group scheduling adapter](native-thermostat-schedule.md) has its own backup/save/reload evidence. Full thermostat programming still requires connecting these behaviors through the original load/save workflow and verifying it independently.

The subsequent [programmable-unit load capture](../research/experiments/2026-09-24/thermostat-unit-load-original.json) executes the full derived `AfterLoadProgrammingInformation` body and 26 reviewed helper methods for twelve frozen states. It confirms that Evap values above 1 normalize to 0, NonEvap values above 1 normalize to 1, and remote scheduling enable is then overwritten by their logical OR. It also confirms application203 creation even while disabled, existing group255 reuse without disabled creation, shared enabled-role identity, ordered missing-group creation and capacity refusal. Across twelve invocations it accepted 71,832 original instruction entries with all states matching; the network-denied child made no native, VM or physical CNI call. Inherited loading, original constructors, actual storage callbacks and native save composition remain outside that evidence.

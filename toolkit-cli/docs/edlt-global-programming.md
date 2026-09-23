# eDLT Global Programming

This workflow copies selected Toolkit categories to existing **KEYGL5 / 5055EDL firmware5.5.00** database units. It prepares a source model once, copies the selected parameters, and verifies each saved destination after closing and loading its project. It opens no physical network and transfers no labels.

The four categories contain7 Key Settings,14 Standby,18 Colour and9 General fields. General includes the four Corridor parameters; Colour includes Quick Status and NavigationIndicatorColour. The complete lists are exported as `CATEGORIES` in `edlt_global_programming.py`.

## Use

```sh
cbus-toolkit edlt --spec-dir decoded-specs global-plan source.json \
  --metadata lifecycle-cache.json --category key-settings --category colour

cbus-toolkit cgate --host 127.0.0.1 --port 20033 edlt-global source.json \
  --spec-dir decoded-specs --metadata lifecycle-cache.json \
  --destination //PROJECT/254/p/21 --destination //PROJECT/254/p/22 \
  --exclusive-project --category key-settings --category colour --dry-run
```

Remove `--dry-run` to apply. Application creates a new backup project automatically; `--backup-project NAME` chooses its new name. Existing backup names are rejected. The backup remains available after the operation.

`source.json` is a complete874-parameter mapping or an exact-profile CLI PP export. `--metadata` supplies the source's explicit lifecycle cache facts. `--parameter-order ORDER.json` optionally supplies the original ordered array of all874 parameter names; otherwise the source mapping's order is used. Duplicate JSON keys, non-finite numbers, duplicate categories and malformed values are rejected.

`--source-database //PROJECT/254/p/20` additionally verifies the supplied source snapshot against that separate database unit and excludes it from the targets. It is a provenance/precondition guard, not a request to load a different source or change the source unit.

Every project network must already be closed with idle synchronization. `--exclusive-project` declares that the caller exclusively controls editing and reloading this project for the operation. It does not mean the helper has proven global session exclusivity. Select1..64 distinct existing destinations in the same project. Dry-run reads database/session state and creates no backup or target save.

Targets and an optional database source must already have complete stored PP and initialized native metadata. A unit requiring initial materialization is rejected with instructions to perform a separate deliberate save/close/load and inspect a new plan. Planning does not silently normalize it.

## Source model, order and CRC policy

The source uses the existing unbound `EdltLifecycle.load` and `prepare_save` phases. This includes source widget/scene/MRA normalization and all five source CRC calculations. Those full-source changes are visible in the plan; only selected category fields are copied to destinations.

Every selected parameter is written even if its value is unchanged. OverallCRC is always included, followed by literal GlobalParameterCRC zero. Selecting no categories therefore still sends **two CRC parameters**.

The order is the selected source attributes, including OverallCRC, in the recorded source order, followed by zero GlobalParameterCRC. Both forward and reversed874-attribute orders have been exercised in the original Windows assembly and through native C-Gate. This is an explicit order policy; it does not claim arbitrary .NET Dictionary dirty-history or full-form wire-order equivalence.

The destination receives the **source OverallCRC**, **GlobalParameterCRC zero**, and retains its own WidgetsCRC, StaticTextCRC and ScenesCheckSum. No destination CRC recomputation occurs. The result deliberately reports `destination_full_crc_validity_verified: false`; the mixed destination is not claimed to have a valid full-image CRC or verified firmware behavior. Setting zero GlobalParameterCRC is not a guarantee of a later physical reread.

Source Project, UnitAddress, UnitName, serial and all other source identity fields remain unchanged. The full Toolkit form performs a Project PP setter before its worker; that outer preamble was not executed by this bounded model/category acceptance and is explicitly excluded. Original ResetUnit/default-template construction, pending UI control commits and full-form validation are also separate. Supplied numeric groups are not silently created in destination application metadata.

## Python API

```python
from cbus_toolkit.edlt_global_programming import EdltGlobalProgramming
from cbus_toolkit.native_global_programming import NativeEdltGlobalProgramming

engine = EdltGlobalProgramming(spec)
source = engine.prepare_source(parameters, metadata=lifecycle_cache,
                               parameter_order=original_order)
payload = engine.select(source, categories=("key-settings", "colour"))
merge = engine.merge(payload, destination_parameters)

manager = NativeEdltGlobalProgramming(client, spec)
# Native plans use their manager's own engine and issued objects.
source = manager.engine.prepare_source(parameters, metadata=lifecycle_cache)
payload = manager.engine.select(source, categories=("key-settings",))
plan = manager.plan(payload, ("//PROJECT/254/p/21",), exclusive_project=True)
result = manager.apply(plan)
observation = manager.verify(plan)
```

`GlobalSource`, `GlobalPayload`, `GlobalMerge` and native plans are immutable issued objects. Dataclass replacement, cross-engine plans and dictionaries pretending to be plans are rejected. Their `.as_dict()` exports are review records, not resumable apply/recovery files.

Repetition uses the same frozen prepared payload. The helper does not reload the source model between destinations or pretend to retain arbitrary mutable WinForms history. The original rich-model sequential fixture produced identical payloads on two saves; broader edited-session equivalence remains unclaimed.

## Failure and verification

All target preconditions are checked before the first mutation and again before each target. Each native SET must return one exact successful200 reply. Full staged PP and raw masks are checked before saving. Application then saves the project, ends its sessions, closes/loads the caller-exclusive project, and independently verifies all874 PP, complete target metadata/OID,39 shared-bitfield bytes and10 CRC bytes.

The original Toolkit can return true after an individual rejected PP SET. This wrapper stops on that rejection and never treats a later acknowledgment as complete persistence. A saved destination gets `verified_saved` only after the independent reload checks.

The batch is not atomic. A failure stops later destinations while retaining any earlier verified results. There are no automatic retries, save replays or unguarded rollback writes. Before a target save, a failed staging session is discarded; after a save was attempted, the backup and before/expected evidence support deliberate recovery. Interruption retains the original KeyboardInterrupt/SystemExit object and partial evidence. Cleanup failures cannot replace that original interruption.

`manager.last_evidence` is refreshed per operation. Exceptions attach `edlt_global_programming_evidence`; ordinary errors retain the original cause and cleanup details. If attachment is rejected, the manager still retains its evidence. `verify(plan)` performs only reads and temporary PP sessions; it does not save or reload a project. Its `complete` field describes completed observation, while `matches_expected` reports the comparison. It does not independently repeat the persistence roundtrip.

## Evidence

The compact frozen original vectors are `research/fixtures/edlt-global-programming-vectors.json`, reproducibly extracted by `research/extract_edlt_global_vectors.py`. They retain all16 masks for two full874 source contexts, the reversed-input supplement, retained sequential payloads and original negative results, pinned to the original Toolkit1.18.0.2754 assembly/probe inputs.

The underlying original40 matrix plus reversed-input2 supplement and independent native literal replay are indexed by `research/runtime/edlt-global-programming/final-research-report.json`. Each Python3.13.14/3.10.20 replay verified37 saved/closed/loaded transactions (74 total). Six original-only failure/creation cases remain unreplayed and explicitly separated. The strict peer also rejects an unterminated trailing command prefix after an otherwise complete capture.

Implementation acceptance is separate from that prior research checkpoint. The final run passed all **28 tests on Python 3.13.14 and 3.10.20**, with no skips and unchanged source/input hashes. Each run verified 36 saved/closed/loaded targets through the native module and another two through the CLI. The module cases cover all 16 masks in both source contexts, reversed attribute order, and two sequential destinations with an independently guarded source database unit. The full 874 values, target metadata, shared raw bits and CRC policy were checked after persistence.

`research/fixtures/edlt-global-programming-acceptance.json` pins both final reports, logs, native evidence and the exact implementation hashes. The acceptance also covers source XML preservation, rejection of an unmaterialized source before its session load, stale source rejection before mutation, loaded/closed backup name collisions, literal rejected SET receipts, interruption identity and cleanup evidence.

`tests/test_edlt_global_programming.py` checks literal source phases/payloads and pure guards; `tests/test_native_global_programming.py` checks failure boundaries and disposable native persistence; `tests/test_cli_edlt_global.py` exercises offline planning, preview and two-target application. Native tests require `CBUS_CGATE_TEST_HOST`, `CBUS_CGATE_TEST_PORT` and `CBUS_UNITSPEC_DIR`. No physical device acceptance is claimed.

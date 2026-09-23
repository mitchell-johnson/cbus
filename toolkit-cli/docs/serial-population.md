# Populate database serials

`DatabaseSerials` implements the verified subset of Toolkit's **Get Serials** workflow: copy matching physical model serials into existing database units at the same addresses. It supports KEYE1, KEYGL5 and PC_CNIED when the database and runtime unit type and firmware strings are exactly equal.

```python
from cbus_toolkit.serials import NativeSerials
from cbus_toolkit.serial_population import DatabaseSerials

inventory = NativeSerials(client).cached("//PROJECT/254")
manager = DatabaseSerials(client)
plan = manager.plan(inventory)  # Optional units=[4, 5] selects database targets.
print(plan.as_dict())
result = manager.apply(plan)    # Creates a separate persistent project backup.
```

`populate(inventory, units=None, backup_project=None)` combines planning and application. Plans and results have JSON-safe `.as_dict()` / dictionary forms. The plan lists every old and new serial, unit address, OID, type and firmware. A no-op returns `updated=false` without creating a backup or saving the project.

## Identity and freshness checks

The input must be a complete, nonempty **whole-network** `SerialInventory`; a partial selected inventory is rejected. Every returned unit must have state `ok`, a known native serial and an unambiguous address. Duplicate or malformed serials, partial refreshes and failed getters are rejected. The optional `units` argument selects database units only after this full inventory has passed its global uniqueness checks. The resulting database may not have duplicate known serials within that network.

The runtime's full cached identity snapshot is reread during planning, after backup and immediately before each database write. A changed unit set, type, firmware, serial or state invalidates the plan. The complete network XML is also compared with the planned source. Forged or changed plans are rejected. The physical address, database address and OID remain unchanged.

Cached inventory has the same provenance as Toolkit's cached physical model. It cannot establish whether an unobserved physical replacement occurred since the last scan. Use `NativeSerials.refresh()` explicitly when a new physical observation is needed. Population does not automatically open, synchronize or program a network. A closed or transitioning unit whose state is no longer `ok` cannot be used for population.

## Backup, changes and recovery

For a plan that changes serials, the current project is saved and copied to a unique backup before the first mutation. A named backup must be different from the source project and may not already exist. The backup is retained and returned to the caller.

Each update uses only `DBSETSAFE <unit>/SerialNumber <observed-string>`. The original native serial text is copied; leading-zero normalization belongs to comparison, not this metadata update. Verification compares complete unit and network XML, including opaque metadata and stored PP values, before and after the final project save. Successful updates do not open PP programming sessions.

If an update or save fails while the stream remains usable, attempted units are restored from their original XML after verifying their OIDs. Native `DBSETXML` must return `301 OID=<original-oid>`; restoration and the subsequent project save are verified. A changed OID is never overwritten. `SerialPopulationError.details` includes the backup and any failed rollback steps. If the native stream disconnects, no reconnection or rollback command is attempted implicitly; the retained backup and explicit rollback error identify the recovery requirement. This is a guarded sequence of native operations, not a vendor-supported atomic database transaction.

## Exact Toolkit evidence

Toolkit 1.18.0.2754 `TfrmUnitsNode.actGetSerialsExecute` at MAP 008B4AB8 (PE VA 00EB5AB8) checks address/type compatibility, reads the matching physical unit's serial attribute, updates database serial metadata and saves the project. The read scanner's source references are listed in [serials.md](serials.md).

`TCBUSUnitManager.HasMatchingUnitByAddressAndType` at MAP 0092D130 compares addresses, then invokes virtual compatibility slot 0x134. Base `TCBUSUnit.IsCompatibleWith` at MAP 00932EC4 / VA 00F33EC4 has an explicit success branch when both UnitType and FirmwareVersion are exactly equal (VA 00F33FE0–00F34034). Broader branches compare resolved specification identity and strict-type flags; they are outside this implementation.

The following exact executable class registrations and VMT slots independently confirm that the supported types use that base method:

| Type | Toolkit class / registration | Class pointer → VMT | VMT+0x134 |
|---|---|---|---|
| KEYE1 | TKEYEx; registration at 0138B654, name at 0138B880 | 00EA8CFC → 00EA8D54 | 00F33EC4 |
| KEYGL5 | TKEYGL5, MAP 00C99CCC | 0129ACCC → 0129AD24 | 00F33EC4 |
| PC_CNIED | TPCI4; registration at 013861F1, name at 01386738 | 00D1897C → 00D189D4 | 00F33EC4 |

These pointers, type literals and the firmware comparison branch are checked against the exact EXE by `SerialPopulationSourceTests`. Matching only a family name or presumed catalogue equivalence does not enable another type. Unsupported types, differing firmware, physical readdressing and occupied-address displacement remain separate workflows.

## Tests

`tests/test_serial_population.py` covers preservation of all non-serial XML, PP values and unknown fields; global and selected inventory guards; stale observations and forged plans; backup collisions; no-op behavior; rollback after an ambiguous write, metadata discrepancy or failed save; and explicit recovery errors for changed OIDs or a disconnected stream.

The native test creates a fresh simulator and unique disposable project with all three supported types. It verifies full XML before/after, independently reads all native PP parameters, verifies the backup's old serials, checks saved values after project reload, and injects failures after actual native mutations. Native project loading materializes some scalar metadata from newly initialized PP; the fixture is saved and reloaded before establishing the comparison baseline. The recorded workflow then changes only serial metadata and emits no simulator bus traffic.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_SERIAL_POPULATION_REPORT=research/runtime/serial-population-acceptance.json \
.venv/bin/python -m unittest tests.test_serial_population -v
```

The optional report captures only generated fixture XML and test results. No physical hardware is used.

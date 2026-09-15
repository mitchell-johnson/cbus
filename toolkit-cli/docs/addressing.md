# Address management

`addressing.py` implements verified database-unit readdressing, paired database/runtime readdressing for closed independent wired networks, and a read-only serial reconciliation report. It does not program physical unit addresses.

```sh
cbus-toolkit cgate address inventory //PROJECT/254
cbus-toolkit cgate address readdress //PROJECT/254/p/20 21 --dry-run
cbus-toolkit cgate address readdress //PROJECT/254/p/20 21
cbus-toolkit cgate address network-readdress //PROJECT/254 253 --dry-run
cbus-toolkit cgate address network-readdress //PROJECT/254 253
cbus-toolkit unit-addressing match database-units.json scanned-units.json
```

Both readdress commands create a persistent `B`-prefixed project backup by default. `--backup-project BACKUP` selects a name; an existing backup is never overwritten. The dry run validates and returns a plan without changing the project database. Unit planning makes an unsaved, disposable PP session edit to obtain the native address encoding.

## Database unit moves

```python
from cbus_toolkit.addressing import DatabaseAddressing

manager = DatabaseAddressing(client)
plan = manager.plan("//PROJECT/254/p/20", 21)
print(plan.as_dict())
result = manager.apply(plan)  # Also available as manager.readdress(source, 21).
```

A native `DBSETSAFE .../Address` moves the unit's database path but leaves its stored PP `UnitAddress` unchanged. This was reproduced with the exact C-Gate 3.4 backend. The implemented operation gets the new value through native `PP SET UnitAddress`, then applies one `DBSETXML` containing both the changed database Address and that PP value. The original OID, other PP entries, serial, names and metadata remain in place. Preserving the OID preserves its identifier; opaque textual path references are rejected because their meaning cannot be inferred.

The operation rejects occupied destinations, addresses outside 0–255, a source with inconsistent database/PP addresses, changed or modified plans, bridge and wireless gateway units, and projects with bridge connections. It validates the native database unit before and after the move. Full native XML and all decoded PP values are compared after the change and again after project save. Unknown PP entries are retained without requiring the current specification to understand them.

On failure, the operation locates the original OID, restores captured XML and PP values, verifies the restoration and saves it. A lost command reply is treated as a possibly successful mutation. It never overwrites another OID to restore the original address. `AddressingError.details` contains the backup project and any rollback errors; an unsuccessful rollback is explicitly reported.

## Closed network moves

```python
from cbus_toolkit.addressing import NetworkAddressing

manager = NetworkAddressing(client)
plan = manager.plan("//PROJECT/254", 253)
result = manager.apply(plan)
```

The database and runtime are separate layers. `DBRENAMENETSAFE` takes decimal addresses in the current project and updates database Address and NetworkNumber. `NET RENAME` changes the runtime name/address and leaves the database alone. The raw CLI commands remain available separately. The workflow above pairs them, verifies both layers, preserves the same network OID, validates metadata and every unit's PP values, then saves the project. Result fields include `database_runtime_consistent`, `runtime_configuration_verified`, `metadata_verified` and `parameters_verified`.

Every unit PP value is preserved, including `NetworkAddress`. That parameter is not automatically rewritten merely because the containing database network was renumbered. The exact Toolkit non-bridge routine creates database and runtime rename commands, updates network metadata, and saves. Its bridge helpers change interface paths separately; it does not contain a unit PP edit in the independent wired-network path. A native fixture with an explicitly set PP NetworkAddress of 254 retained 254 after its database and runtime network moved to 253.

Only CNI and serial wired networks are accepted. The native runtime must report `InterfaceState=closed`, `TargetInterfaceState=closed` and `SyncState=idle`; the ordinary `State=new` value alone does not prove that an interface is closed. Database and runtime interface definitions must agree, and the destination must be free in both layers. Bridge connections, bridge/WGATE units, and opaque textual network-path references are rejected. This operation does not open, scan, synchronize or program a physical network.

Rollback independently attempts to restore runtime and database addresses, restores captured network XML if metadata changed, then verifies all PP values and saves. It reports failures from each layer. These multi-command operations use optimistic state checks; they are not a project-wide transaction against other clients. Avoid concurrent edits to the affected network. Toolkit's broader topology adjustment, open-network commissioning and bridge/gateway cascades remain outside this workflow.

## Serial reports

Inventory JSON files contain arrays such as:

```json
[{"address": 20, "unit_type": "KEY4", "serial": "00100700.3526"}]
```

The library equivalent is `match_serials(database_units, network_units)`, where each item is a `UnitIdentity(address, unit_type, serial)`. `DatabaseAddressing.inventory(network)` obtains the database list. The physical/scanned list must be supplied explicitly; inventory does not scan a network.

The report compares exact opaque serial strings and exact unit types. It distinguishes aligned addresses, different addresses, duplicate serials, type mismatches and units appearing in only one list. Blank serials and the native `00000000.0000` placeholder are unidentified. Proposed directions report occupied destinations, including swaps, without displacing anything. Serial text is not reformatted, validated as a manufacturer barcode, or treated as proof that different unit types are compatible. The report applies no changes.

The separate [Get Serials workflow](serial-population.md) now supports a verified subset, and [physical addressing](physical-addressing.md) supports a single KEYE1 move to an empty destination. Occupied-address displacement, broader compatibility matching and automatic multi-unit reconciliation remain unimplemented. Existing `NET UNRAVEL ... matchdb` command exposure does not establish tested equivalence to those Toolkit dialogs. The physical addressing module documents the explicitly enabled simulator subset for protected UnitAddress writes.

## Evidence and verification

Sources are the locally extracted Toolkit 1.18 help, original executable/MAP, and exact C-Gate 3.4 command implementation; proprietary source files are not bundled with this module.

| Workflow | Local evidence |
| --- | --- |
| Database unit readdress to an unused address | Help `4765.htm`, `4350.htm`; `TCBusUnitCGateAgent.DoReAddress`, MAP `006C1E14`; `TfrmUnitsNode.ReaddressDBUnit`, MAP `008BE2C0` |
| Network topology requirements | Help `7438.htm`, `7440.htm` |
| Paired Toolkit network commands | `TCBusNetworkCGateAgent.ReaddressNetwork`, MAP `00786830`; `TcgcDBRenameNet`, `007807B4`; `TcgcNetRename`, `00780B28` |
| Separate bridge helpers | `AdjustBridgedNetworkInterfaceAddress`, MAP `00786470`; `AdjustOtherNetworksInterfaceAddress`, `007865A0` |
| Native database/runtime separation | C-Gate `help/cmds.txt`: `DBRENAMENETSAFE`, `NET RENAME`, `DBVALIDATE` |
| Physical serial matching | Help `4347.htm`, `7668.htm`, `7671.htm`, `7669.htm` |
| Get Serials | Help `4356.htm`, `4759.htm` |
| Compatibility matching and displacement | Help `7646.htm`, `7647.htm` |

Reproduce the optional native and vendor-source checks using disposable projects only:

```sh
PYTHONPATH=src \
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
.venv/bin/python -m unittest discover -s tests -p test_addressing.py -v
```

The acceptance tests cover KEY1, KEY2, KEY4, KEYE1, KEYGL5 and DIMDN4 unit moves; complete metadata and PP comparisons; independently checked native byte 0x20; fresh connections and project reloads; addresses 0 and 255; existing backup preservation; stale/occupied/forged plans; unknown PP retention; CNI and serial network moves; both rename failure boundaries; metadata loss; failures after project save; and failed rollback reporting. All native fixtures use unique disposable projects and closed loopback CNI or unopened serial interfaces. Default tests skip optional server/source checks when their environment variables are absent.

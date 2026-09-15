# Unit serial inventories

`NativeSerials(client).cached("//PROJECT/254", units=None)` returns the native runtime's existing unit identities. `refresh(...)` explicitly refreshes an already open network and then checks address multiplicity. Both return `SerialInventory`; `.as_dict()` is JSON safe and `.identities` supplies `UnitIdentity` values for `addressing.match_serials`.

The methods read Address, Type, Version, SerialNumber and State individually. They deliberately avoid `GET unit *`: native wildcard property enumeration also invokes physical getters such as network voltage. A cached read does not open an interface, synchronize a network, update the database or change a physical address. Runtime identities can be read after closing an interface, subject to their reported unit state.

`units` is an optional iterable of unique integer addresses in 0..255; an empty selection is rejected. An omitted selection returns all modeled units. A requested address absent from the cache is reported as `not_cached`, without inventing its type or serial.

## Explicit refresh

Refresh requires InterfaceState and TargetInterfaceState `running`, SyncState `idle`, AutoUnravel `no` and AutoUpdate `no`. The method checks these settings and rejects incompatible states; it does not change them. It sends `NET SYNC <network> fast`, followed by `NET CHECKUNIT <network> <addresses>` (or `*`).

**Identity refresh has whole-network scope.** A selection limits the returned records and subsequent multiplicity checks, not the fast synchronization. AutoUnravel is excluded because native synchronization can automatically readdress conflicting units when that setting is enabled. AutoUpdate is excluded because it can populate the database during synchronization.

Whole-network scope does not establish complete MMI address coverage. The original
`SYNC` and `CHECKUNIT` reader can treat missing address ranges as zero, including
for explicitly selected addresses. This inventory therefore reports
`mmi_coverage_verified=false`; `complete` describes its returned records and
command results. Its absent results alone must not authorize an address change.
The [physical address workflow](physical-addressing.md) separately requires
`PINGU`, whose older reader validates range coverage, and compares its full
address list with the healthy identity inventory immediately before a write
and during recovery verification. The [native fault regression](native-mmi-address-guard-acceptance.json)
contains an occupied target hidden from `CHECKUNIT` and rejected by that guard.

Each record retains the native serial string, firmware, type and unit state. Missing addresses, ambiguous physical addresses, unknown or malformed serials, duplicate serials, failed getters and unchecked addresses remain visible in the result. Successful records survive partial failures. Duplicate serial detection covers the returned inventory; a subset cannot establish global serial uniqueness.

`complete` is false for any failed or unresolved record. A failed synchronization never exports cached identities as refreshed identities. After a successful synchronization, proven single-address results can still be returned when a later multiplicity check partly fails. A complete native property error retains its error rather than substituting a value. An incomplete command, disconnected stream or framing failure raises `SerialTransportError` immediately; no later getter, retry or implicit reconnection is attempted. Unset/malformed serials may supply an identity with an empty serial for the matcher's unidentified list; their raw text and status remain in the record.

## Comparing native serials

`parse_native_serial(text)` validates decimal-dot components: the first is in 0..1048575 and the second in 0..4095. The reader canonicalizes leading zeroes for `UnitIdentity.serial`, while retaining the original serial in each record. Zero (`0.0`, including its padded forms) and all-ones (`1048575.4095`) are unidentified placeholders. Malformed text is explicitly reported; it is not converted into a fabricated serial. Input components are bounded to 16 digits each.

`match_serials(database, network, native_serials=True)` applies the same normalization, returns invalid serial records separately, and preserves original input text in match details. Its default remains the earlier exact opaque-string comparator for compatibility. Neither mode writes to the database or moves units. Exact unit-type equality is required for a match; broader Toolkit type compatibility has not been mapped here.

```python
from cbus_toolkit.addressing import DatabaseAddressing, match_serials
from cbus_toolkit.serials import NativeSerials

observed = NativeSerials(client).cached("//PROJECT/254")
database = DatabaseAddressing(client).inventory("//PROJECT/254")
report = match_serials(database, observed.identities, native_serials=True)
```

Check `observed.complete`, its records and errors before using a partial inventory for reconciliation.

## Toolkit evidence and remaining workflow

The exact Toolkit 1.18.0.2754 help topics `research/vendor/toolkit-help/4356.htm` and `4759.htm` describe **Get Serials** as copying physical-network serials into corresponding database units. The implementation at MAP symbol `TfrmUnitsNode.actGetSerialsExecute` (008B4AB8; PE virtual address 00EB5AB8) iterates database units, checks `HasMatchingPhysicalUnit`, copies the matching physical unit's cached serial attribute, calls `UpdateSerial`, then `ProjectSave`. The literals at 00EB5D48 and 00EB5D88 are checked by the source test. `HasMatchingUnitByAddressAndType` (0092D130) also invokes type compatibility logic; that broader compatibility is not assumed.

This module implements identity retrieval and explicit physical refresh. The separate, explicit [database serial-population workflow](serial-population.md) supports KEYE1, KEYGL5 and PC_CNIED with exact type/firmware guards, a mandatory backup and verified rollback. Read-only scans do not perform that update.

The exact C-Gate 3.4 decompilation in `research/vendor/cgate-decompiled.tar` provides these additional anchors:

- `cn.java`: decimal-dot parsing, 20/12-bit bounds, canonical decimal rendering and all-ones marker.
- `com/clipsal/cgate/cbus/dev/CBus2Unit.java` and `CBus3Unit.java`, with their `$3` getters: cached SerialNumber fields; zero initialization in CBus2Unit.
- `cB.java`, `cG.java`, `cH.java`: cached Address, Type and Version getters.
- `kC.java`: exact CHECKUNIT result phrases and partial native failures. CHECKUNIT alone does not refresh the identity cache.
- `kV.java`: SYNCNEW rejects a unit already present in the model, so it is not a general identity refresh.
- `aC.java` / `CBusBaseNetwork`: TargetInterfaceState is `running` or `closed`, distinct from the aggregate network state and interface transition states.

## Verification

`tests/test_serials.py` covers deterministic property parsing, partial error handling, placeholder handling, canonical duplicates and compatibility with opaque matching. With `CBUS_CGATE_TEST_HOST` it also creates a unique disposable project and fresh synthetic simulator, waits for native readiness, verifies captured serials for KEYE1, KEYGL5 and PC_CNIED, proves cached reads generate zero wire records, checks a missing address, changes an explicit fixture IDENTIFY4 serial, and proves the changed serial appears only after refresh. It independently detects the resulting duplicate and verifies database XML remains unchanged. No test connects to a physical C-Bus network.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_SERIALS_REPORT=research/runtime/serials-acceptance.json \
.venv/bin/python -m unittest tests.test_serials -v
```

`CBUS_CGATE_TEST_PORT` defaults to 20023. `CBUS_CGATE_SIMULATOR_HOST` defaults to `host.docker.internal`, the simulator endpoint as seen by the isolated native server. `CBUS_SERIALS_REPORT` optionally captures the inventory and wire transcript from the fresh fixture.

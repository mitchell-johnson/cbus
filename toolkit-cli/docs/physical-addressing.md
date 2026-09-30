# Physical unit addressing

`PhysicalAddressing` implements one bounded physical move: a KEYE1 running firmware 2.5.00, at an address in 1..254, moving to a different independently empty address in that range. It uses the same scalar native Address operation as Toolkit. The unit's serial must be supplied explicitly.

```python
from cbus_toolkit.physical_addressing import PhysicalAddressing

manager = PhysicalAddressing(client)
plan = manager.plan("//PROJECT/254/p/4", 6, expected_serial="101136.1558")
print(plan.as_dict())
result = manager.apply(plan)
```

`readdress(source, new_address, expected_serial=...)` combines planning and application. `verify(plan)` performs a separate physical observation without another address write. A completed observation reports `confirmed_moved`, `confirmed_not_moved` or `uncertain` with its evidence. Invalid preconditions and transport failures still raise an error.

The CLI exposes the same workflow:

```sh
cbus-toolkit cgate --timeout 60 address physical-readdress //PROJECT/254/p/4 6 \
  --serial 101136.1558 --dry-run --plan-output preview.json
cbus-toolkit cgate --timeout 60 address physical-readdress //PROJECT/254/p/4 6 \
  --serial 101136.1558 --plan-output recovery.json
cbus-toolkit cgate --timeout 60 address physical-verify recovery.json
```

The output file must not already exist and is written before application. Dry-run still performs the planning observations. Verification accepts either that plan file or the JSON result/error containing a `plan`. An uncertain observation exits with status 1; `confirmed_not_moved` is a successful observation, not a claim that the intended move happened. `tests/test_cli_physical_addressing.py` exercises these commands against native C-Gate and checks that exactly one protected address STORE occurs.

## Required state and checks

The network must have a direct CNI or Serial interface, be Wired, have InterfaceState and TargetInterfaceState `running`, SyncState `idle`, AutoUpdate and AutoUnravel `no`, and **Retries=0**. Runtime and database interface definitions must agree. The helper preserves these settings. Native retries normally default to 2; set zero explicitly using `SET <network> Retries 0` after the network has become ready. Startup can reload the default setting; the helper reads the actual value.

Planning performs a whole-network fast synchronization, requests native source/destination classification, and checks the runtime identity inventory for missing, duplicate or unresolved serials. The source must be a single healthy unit with the expected canonical serial, supported type and firmware. A separate `NET PINGU` must then return successful full MMI coverage with a nonempty address list exactly matching the healthy cached identity addresses, including the source and excluding the destination. Known bridge/wireless gateway topology is rejected. Local PCI units are excluded as move sources by the supported type restriction; their cached identities participate in the full address-list comparison.

Application repeats these observations and compares the plan, database XML and runtime preconditions. It issues another `NET PINGU` as the immediately preceding command before the single `SET <source-unit> Address <destination-number>`. After the native response, another physical synchronization checks the serial, type and firmware at the new address, absence at the old address, unchanged identities for other units and unchanged database XML. Verification independently repeats `NET PINGU` and requires its full address list to match the observed identities before confirming any outcome. Results retain `pre_write_mmi` and `verification.mmi` command, reply and address evidence. Whole-network read/refresh scope is recorded in the plan.

This separate coverage check is necessary because native `NET CHECKUNIT`, including explicitly selected addresses, uses the same `dw/dx` MMI reader as network synchronization. That reader can accept three valid response frames with a duplicated block and silently treat a missing address range as empty. Its selected-address path does not send IDENTIFY to an address absent from that MMI map. `NET PINGU` uses the older `dk/dn` reader, which rejects unexpected offsets and checks that every address was covered. A successful status from CHECKUNIT alone does not establish an empty destination.

The guard accepts only the exact native two-line `302-Units=...` plus `200 OK.` response, with unique ascending decimal addresses in 0..255. Empty/null, malformed, failed and mismatched inventories stop application before a write. A failed post-write coverage check leaves the outcome uncertain and does not trigger another write. This verifies protocol coverage and agreement with the healthy native inventory; it does not provide an atomic lock against another controller or prove that a physical unit will never miss an MMI response.

The database unit address and PP configuration are intentionally independent. This operation can move a physical unit to the address already assigned to its database counterpart. It does not relocate database units, save their project or copy parameters into hardware. Concurrent external edits are not covered by an atomic vendor transaction.

## Uncertain outcomes

A failed response or failed post-write verification raises `PhysicalAddressUncertain`. Its `.details` includes the complete plan, native reply if available, verification evidence, a `cause` and `automatic_write_retries=0`. The helper does not reconnect, replay the address write or issue an automatic reverse move. If the stream was lost, reconnect explicitly and call `verify(plan)` to observe the actual state. A successful native status alone is insufficient for the helper to claim the complete move.

An interruption such as KeyboardInterrupt or SystemExit after the write is
attempted preserves the original exception. Recovery evidence is attached as
`exception.physical_address_evidence` and retained as `manager.last_uncertain`.
No follow-up command runs. The C-Gate transport closes an interrupted command
stream; recovery still requires an explicitly established connection and the
original plan. Preflight interruption records no attempted write.

`plan.as_dict()` is a complete JSON recovery document containing the original identity inventory, runtime settings and database XML/hash. Save it before application when recovery across process restarts is needed. The same document is included in `PhysicalAddressUncertain.details["plan"]`:

```python
import json
from pathlib import Path
from cbus_toolkit.physical_addressing import PhysicalAddressPlan

Path("address-plan.json").write_text(json.dumps(plan.as_dict()), encoding="utf-8")
# On a separately established connection after an uncertain outcome:
recovered = PhysicalAddressPlan.from_dict(json.loads(Path("address-plan.json").read_text(encoding="utf-8")))
observation = PhysicalAddressing(client).verify(recovered)
```

Import validates the format, source/destination, supported identity, complete unique inventory, runtime preconditions and XML/hash consistency without accessing C-Gate. These are caller-supplied baseline records, not signed attestations. Verification compares fresh observations against that baseline; application always rebuilds and compares a fresh plan before writing. Preserve the original recovery document, including its database metadata.

The tests deliberately lose a reply after a real native mutation: the simulator has moved, the helper reports uncertainty, and an explicitly reconnected observation establishes the outcome without another address write.

## Reconciling a selected-serial move with the database

`serial-address apply` changes only the bus and records `database_updated: false`. `serial-address reconcile` then moves the database unit that carries the moved serial from the journal's source address to its destination:

```sh
cbus-toolkit serial-address reconcile --journal new-recovery.json --project site.xml
cbus-toolkit serial-address reconcile --journal new-recovery.json --project site.xml --apply
cbus-toolkit serial-address reconcile --journal new-recovery.json \
  --cgate 127.0.0.1:20023 --project-name PROJECT --apply
```

The library entry point is `cbus_toolkit.serial_reconcile.reconcile(journal, database, apply=...)` with `ProjectFileDatabase(path)` or `CGateDatabase(client, project)`. The command performs no PCI, CNI or C-Bus I/O.

**Journal admission.** Completed Python apply journals
(`cbus-selected-serial-result-v1`) and Rust routed apply-v2 journals
(`cbus-selected-serial-apply-v2`) qualify only with `state: after_observed` and
`outcome: observed_expected_change`. Direct Rust v1 behavior is unchanged;
legacy `cbus-selected-serial-apply-v1` journals are not accepted offline.
Journal outcome fields are not authenticated, so the command reparses the
retained frame evidence: the fresh before inventory must equal the plan's,
local PCI identity and option byte must hold, the exchange must be the plan's
single clean request with its raw receipt reparsed, and the after inventory
must reparse to exactly the plan's expected map with no unexpected changes.
The shared attempt marker named by the journal must still exist, embed the
same plan and name the same journal. A deleted marker is the operator's replay
authorization, so the journal is then stale and refused. Unchanged, unexpected,
uncertain, in-progress, pre-marker, marker-only and tampered journals are
refused before the database is opened. Read-only Rust `serial-verify` output
cannot substitute for an apply journal.

**Matching.** A direct journal names no C-Bus network, so the moved serial must match exactly one database unit across the project (native decimal-dot comparison; `--network` restricts the search). Ambiguous or missing serials, units without a valid OID, bridge/wireless-gateway units and a destination occupied by another unit are refused. `--unit-type` and `--firmware` add explicit database pins; the journal carries no physical type or firmware evidence, and these pins do not establish physical compatibility. Routed journals instead restrict matching to the recorded target network; `--network` is optional and, when supplied, must equal that target. The source network is never searched for the moved database unit. A database unit at the destination is reported as `database_already_matches` and is not changed. A unit at any other address means the journal or the database is stale, and the command stops.

**Database move.** A C-Gate project uses the verified [database unit move](addressing.md#database-unit-moves), including its `B`-prefixed backup project, native PP `UnitAddress` encoding, save and post-save verification. A legacy XML or CBZ file is changed in memory: its Address field and stored PP `UnitAddress` are rewritten in the existing decimal or `0x` form, and everything else is kept, including the OID, metadata, other programming, opaque extensions, archive members and OID references. Direct journals still refuse projects with bridge interfaces. Routed journals admit their exact bound topology as described below. Both paths refuse textual unit-path references requiring explicit reconciliation. `--apply` writes an exclusive `.pre-reconcile-<id>` backup next to the file, saves it atomically and reloads it. The reload must match the planned content. After the two edited fields are reverted, the reloaded document must equal the original.

**Routed offline admission.** A Python routed journal must retain complete
before/after captures on the exact one-to-six-bridge Reply Network and a route
binding with the same project SHA-256 and route as the plan, explicit
source/target networks, `route_rederived: true` and
`topology_fresh_at_handoff: true`. Local PCI identity and options remain direct
evidence. Receipt summaries must agree with the raw reparsed exchange; a lost
or mismatched receipt can still accompany an accepted move when the clean
completed exchange is followed by a fresh exact expected after-inventory.
A receipt alone never proves movement. The caller supplies `--project FILE`;
the recorded private project path is not followed. Routed C-Gate reconciliation
is refused before connecting.

Rust routed apply-v2 uses the independent Python validator
`cbus_toolkit.rust_serial_reconcile`, rather than trusting Rust's summary or
calling Rust to reconstruct it. Its `reconciliation_evidence` must have format
`cbus-rust-selected-serial-reconciliation-v1`, source
`cbus-transport-routed-selected-serial`,
`frame_capture_scope: commissioning_frames` and `raw_connection_capture: false`. Version-one
inventory and frame-capture envelopes retain the before/after inventories,
fresh direct local IDENTIFY4 and option-66 checks, exchange, actual requests
and allocated confirmations. Each original `raw_frames_hex` entry has one
ordered `parser_frames_hex` entry. Reader originals remain unchanged; parser
copies may only normalize trailing CR/LF to CRLF or append an outer checksum
for validated checksum-off frames. Payload, Reply Network and destination bytes
are preserved, and confirmations cannot change.
Original frames require uppercase wire hex and one CR, LF or CRLF terminator,
as emitted by the Rust reader.

Checksum addition is bound to the plan's checksum-off mode; an omitted checksum
in a checksum-on original refuses even when its parser copy is valid. Each
direct PCI identity capture requires exactly one reply, and each remote probe
allows at most seven replies before duplicate serials are collapsed. A repeated
identical direct identity reply therefore cannot satisfy local PCI provenance.

The Python parsers independently verify these relationships, request bytes,
exact routes, contiguous complete 256-state MMI bookends, every present-address
serial probe, the expected local PCI serial and option byte `05`. They compare
the reconstructed before map with the plan and after map with `expected_after`,
and check the receipt summary against the reparsed exchange. Admission requires
one completed send, durable attempt intent, complete streams and the expected
termination for each capture. Ignored traffic, missing or partial proof,
unknown versions/fields, wrong routes, contradictory summaries and uncertain
attempts refuse before database writes. The journal must remain at its recorded
absolute path; its existing marker must bind the same canonical plan,
fingerprint, journal and directory/store scope. The Rust route binding must
record the matching project digest/route, explicit source/target networks,
`route_rederived: true` and `physical_bridge_acceptance_verified: false`.
This is internally consistent commissioning-frame evidence, not a full raw
connection capture, authenticated history or a physical acceptance claim.
The source/schema strings bind an internal contract, not a cryptographic
signature; these offline files remain operator-controlled.

On the first routed run, the supplied XML/CBZ file's raw SHA-256 must equal the journal's original project pin. The route is re-derived from that project before and after the candidate move. Only Address and PP `UnitAddress` change; OID references and opaque CBZ members remain intact. Routed backups and project replacement each require a successful parent-directory fsync. Before replacement, the implementation rechecks raw project freshness after recording durable intent. This check is not a cross-process filesystem lock: the caller must exclusively own the project file for the complete operation.

On restart, the recorded backup supplies the original bytes, which must still match the journal's original SHA-256. The implementation recomputes the exact candidate from those bytes, validates the record against that move, and then checks the current project's expected content digest. The backup must remain available, including for completed-record validation. A `db_pending` source state repeats only on an explicit `--apply` rerun; an exact destination state fsyncs the existing publication and completes only the record, and any changed pending state conflicts. A failed directory fsync cannot become `db_done` automatically. A valid `db_done` record performs no writes and reports whether current content still matches.

**Reconciliation record.** Without `--apply`, nothing is written. With `--apply`, an exclusive record, by default `JOURNAL.reconcile.json` (`--record` selects another path), binds the journal SHA-256 and attempt ID, the database identity, unit OID, and the before/expected digests. The record moves through `physical_done`, `db_pending` (written before any database write, with the backup name), and `db_done`. It keeps a history, `database_changed`, and any `last_error` and `rollback_errors` values. Updates use checked atomic replacement and fsync. A rerun behaves as follows:

* after `db_done`: returns `already_reconciled` without writing and reports whether the database still matches;
* after `db_pending` with the unit already at its planned destination content, for example after an interruption between save and the record update: completes the record as `resumed_complete`;
* after `db_pending` with the unit unchanged at its source: repeats the move under the explicit rerun;
* after `db_pending` with any other change: reports a conflict and leaves the database and record unchanged.

If the journal changes after a record exists, or a record is reused for another database, the command refuses.

Routed coverage in `tests/test_serial_reconcile_routed.py` uses synthetic scripted
software peers and offline XML/CBZ projects. The historical focused direct/routed
run passed 25 tests and 54 subtests; the native acceptance test was deliberately
deselected. The [historical source-bound software receipt](serial-reconcile-routed-evidence.json)
records that earlier revision's command and scope; it has not been regenerated
for the Rust v2 validator and does not verify current-source hashes.

`tests/test_rust_serial_reconcile.py` optionally generates actual Rust CLI
apply-v2 journals against an independent literal fake PCI: one-bridge XML with
all routed replies checksum-off and six-bridge CBZ with checksums on. It
validates each original producer journal and genuine marker before fixture
path relocation. The isolated cases then test dry-run, apply, XML/CBZ
preservation, restart without another save, strict frame/summary/route refusals
and missing or changed markers. Set `CBUS_TOOLS_BIN` to the built CLI to run
these cases. Neither suite establishes native routed UNRAVEL success, bridge
delivery, physical compatibility or hardware persistence.
The [Rust/Python offline reconciliation receipt](rust-selected-serial-reconcile-evidence.json)
records the focused run for this slice. No native C-Gate or hardware was
launched for this slice.

Tests: `tests/test_serial_reconcile.py` drives the existing simulator fixture through `serial-address` plan/apply and uses the journals it writes. It covers offline XML and CBZ projects in these cases: positive, dry-run, ambiguous, not found, occupied destination, stale address and type pin. It also covers every rejected journal class, a deleted marker, a changed journal, an interruption between save and record update, an interruption before save, a pending conflict, rerun idempotence and a CLI chain from the simulator to the project. An owned native C-Gate 3.4 test runs when `CBUS_CGATE_JAVA` and `CBUS_LOCAL_CGATE_VENDOR` are set. It moves a KEYE1 database unit from 255 to 6 and checks the unit and project after save, close and reload. The OID, metadata and an OID reference from another unit are retained. Every PP value except `UnitAddress` is retained, and a second run is a no-op. Physical persistence, power cycling, multi-unit moves and occupied-address displacement remain outside this workflow.

## Exact protocol evidence

Toolkit's `TfrmSerialReaddress.MatchToSerial` (MAP 008A46C0 / VA 00EA56C0) obtains the unit's cached serial, finds the corresponding database unit using `UnitBySerialNumber`, calls `EnsureTargetAddressClear`, sets `MoveToAddress` and invokes the move action. `EnsureTargetAddressClear` (MAP 008A4850) can displace an existing physical occupant to another free address. That displacement branch is outside this implementation; an occupied destination is rejected.

`TCBusUnitCGateAgent.DoReAddress` (MAP 006C1E14 / VA 00CC2E14) creates `TcgcSet`, sets the object's path and builds the Address value from `MoveToAddress`. Exact C-Gate 3.4 source in `research/vendor/cgate-decompiled.tar` traces the operation through `cB.java`, `CBusUnit.e(aX,int)`, `CBusBaseNetwork.a(...)`, and `dc.java`:

- `dd.java` emits UNLOCK for parameter 0x20: `\46<old>001120`, accepting `82 20 <unlock-byte>`.
- `cu.java` specializes `ct.java`: protected address STORE is `\46<old>00A3204E<new><unlock-byte>`. The unlock byte is appended outside the ordinary A3 count. This is not a generic EEPROM write.
- The accepted CAL response is `32 20 4E`, normally from the new source address; `3B 20 4E` is the corresponding negative response.
- `CBusBaseNetwork` updates its runtime address table and unit object after the operation. The native library can otherwise retry; the explicit zero retry guard removes that behavior for this workflow.

Literal vectors for the explicitly chosen simulator challenge 0x5A, source 4, destination 6 and local PCI 16 are:

| Command bytes (ASCII) | Response bytes (ASCII) |
|---|---|
| `\4604001120g\r` | `g.8604100082205A6A\r\n` |
| `A3204E065Ah\r` after the preceding cached header | `h.8606100032204EC4\r\n` |
| `\4606001A2001i\r` | `i.86061000822006BC\r\n` |

`NET UNRAVEL ... MATCHDB` is broader. Its `co.java` path uses a broadcast with a packed serial, requested address and inner checksum. For serial 101136.1558 and destination 6, the source-derived broadcast body is `\05FF000F0018B106160615`. A separate opt-in simulator fixture now tests that request with an explicitly supplied response tail; native single-unit commissioning from address 255 instead uses protected STORE. See [serial-commissioning.md](serial-commissioning.md) for both scopes. Automatic unravel, duplicate-address discovery, occupied-destination displacement and bridge/wireless addressing remain separate work.

## Simulator scope and persistence

The simulator capability is explicitly enabled with `readdress_challenges={4: 0x5A}` and a matching declared UnitAddress byte 0x20. It supports only the synthetic KEYE1 firmware 2.5.00 fixture. Challenge selection and one-use lifetime are deliberate fixture choices; no claim is made about real device challenge generation.

A valid move rekeys the unit and associated per-unit memory/status maps, changes the declared UnitAddress byte and persists state before acknowledging. Serial/type/firmware, other EEPROM bytes, application groups and the local interface remain unchanged. A persistence failure restores the original maps before returning an error. Restart retains the new address and clears pending unlock state. Unknown units, unsupported identities, malformed requests and generic writes to the protected address remain rejected.

`tests/test_simulator_addressing.py` uses independent literal socket vectors, rejected writes, state reload and injected persistence errors. `tests/test_physical_addressing.py` covers identity/empty-target/stale-plan guards and uncertainty, then exercises real C-Gate against a unique project and fresh simulator, including an independent simulator restart and explicit recovery after a lost response. The database target already exists at 6 in that native fixture and remains unchanged.

The native fixture uses an explicit 0.01-second transport response delay. Reopening an existing native network model can defer its next scheduled scan; waiting for readiness alone does not start a scan. The restart test waits for its interface to run, explicitly requests fast synchronization with AutoUnravel/AutoUpdate still disabled, then observes readiness and identities.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_PHYSICAL_ADDRESS_REPORT=research/runtime/physical-addressing-acceptance.json \
.venv/bin/python -m unittest tests.test_simulator_addressing tests.test_physical_addressing -v
```

The recorded lifecycle is in [native-physical-addressing-acceptance.json](native-physical-addressing-acceptance.json). The [MMI guard regression](native-mmi-address-guard-acceptance.json) introduces an explicitly identified occupied target 100 after the initial healthy scan, then supplies independently literal install-MMI frames with the 88..175 block omitted and the first block repeated. Native CHECKUNIT 4,100 reports 100 absent without an IDENTIFY request, but the helper's PINGU rejects the incomplete coverage before any address write. Fixture state and database XML remain unchanged. Earlier wheel checkpoints predating this guard retain that known absence-check limitation. These tests establish the native/simulator workflow for the stated fixture, not hardware-wide addressing parity.

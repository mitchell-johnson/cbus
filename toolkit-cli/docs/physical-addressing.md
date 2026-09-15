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

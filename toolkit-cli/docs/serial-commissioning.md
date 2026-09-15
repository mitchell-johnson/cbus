# Serial-directed commissioning

`SerialCommissioning` supports the native commissioning case independently verified against C-Gate 3.4: one KEYE1 running firmware 2.5.00 at the unprogrammed address 255, moving to an empty address in 2..254 whose database unit already has the same known serial, type and firmware.

```python
from cbus_toolkit.serial_commissioning import SerialCommissioning, SerialCommissionPlan

manager = SerialCommissioning(client)
plan = manager.plan("//PROJECT/254/p/255", 6, expected_serial="101136.1558")
# Save plan.as_dict() as recovery JSON before application when needed.
result = manager.apply(plan)

# On an explicitly established connection after an uncertain response:
recovery = SerialCommissionPlan.from_dict(saved_json_document)
observation = manager.verify(recovery)
```

`commission(source, new_address, expected_serial=...)` combines planning/application. Verification is separate and issues no readdressing operation. It reports `confirmed_moved`, `confirmed_not_moved` or `uncertain` when its observation completes; invalid preconditions or transport errors raise exceptions.

## Native command semantics and bounds

The helper matches the database serial in Python and issues one `SET <source-unit> Address <destination>`. Its plan/result metadata records `method=database_serial_match_then_scalar_address`; application reuses the tested physical Address workflow. Earlier recovery documents without `method` remain readable as identity/database baselines, but new application uses the scalar operation.

The raw `NET UNRAVELUNIT <network> 255 MATCHDB` operation has broader semantics. It can choose another free destination if its own internal serial scan fails, even after successful caller preflight and with Retries=0. A regression test injects one all-ones serial reply during that scan: native UNRAVEL moves the unit to 2 despite a database target at 6. This is why the typed helper uses a fixed-destination scalar operation. The source evidence and fault results are in [native-unravel-fallback.md](native-unravel-fallback.md).

Raw `MATCHDB` also leaves a healthy singleton at a normal address in place: an isolated probe with physical KEYE1 at 4 and its database serial at 6 returned 200 with no move. Native `CBusNetworkUnraveller` selects duplicate/problem addresses or addresses marked for clearing, including 255. Single KEYE1 moves use `dc/dd/cu` unlock/STORE; native uses `co` broadcasts for other branches. The typed helper rejects normal source addresses; use the separately tested [physical Address workflow](physical-addressing.md) for those.

Planning uses a direct wired CNI/Serial network, running interface/target, idle synchronization, AutoUnravel and AutoUpdate disabled, and explicit **Retries=0**. It preserves these settings. It performs a whole-network fast refresh, physically checks source 255 and the requested target, requires complete healthy unique identities, and checks that exactly one database unit matches the expected serial at the target with the same type/firmware. Known bridges/gateways, duplicate serials, occupied targets, missing database counterparts and stale metadata are rejected.

Application rebuilds the plan and rechecks runtime/database evidence before the one native operation. It inherits the [physical addressing coverage guard](physical-addressing.md#required-state-and-checks): a successful `NET PINGU` must return a full nonempty address list exactly matching the healthy cached identities, with source 255 present and the target absent. The check runs during planning, immediately before the scalar write and independently during verification. Native SYNC and CHECKUNIT share a weaker MMI reader that can silently omit a response range, so their classification alone does not establish an empty target.

Afterward the helper refreshes again and verifies the expected serial/type/firmware at the target, absence at 255, unchanged identities elsewhere and unchanged database XML, with successful independent PINGU coverage. C-Gate's 200 response alone is insufficient. Failed coverage after a write leaves the outcome uncertain. The database address, PP values and project file are not rewritten by this workflow. Concurrent external edits are outside an atomic vendor transaction.

The wrapper never retries a commissioning write, reconnects automatically or issues a reverse move. Native Retries=0 is also required by the scalar operation. Any failed response or failed post-write observation raises `PhysicalAddressUncertain` with the original plan, command, reply when available, `cause` and verification evidence. Recovery is an explicit observation against that original baseline. `observed_identities` and `serial_observed_addresses` expose the actual locations found during a complete observation, including unexpected locations after separately issued raw vendor commands.

## Explicit simulator behavior

The native fixture declares the unit's UnitAddress byte as 255, `readdress_challenges={255: 0x5A}` and `readdress_empty_addresses={6}`. An UNLOCK at the explicitly empty destination produces a PCI link confirmation without a CAL response. It does not fabricate a unit response. Successful movement rekeys unit/memory/status state and the challenge, writes UnitAddress 6, swaps the declared empty slot to 255, and persists before acknowledging.

Literal source-derived and native-observed fragments include:

| Command bytes | Reply bytes |
|---|---|
| `\4606001120g\r` at explicitly empty 6 | `g.` |
| `\46FF001120h\r` | `h.86FF100082205A6F\r\n` |
| `A3204E065Ai\r` with cached source 255 header | `i.8606100032204EC4\r\n` |

The separate serial-broadcast fixture is opt-in through `serial_readdress_reply_tails={"101136.1558": b"\0\0"}` and an explicitly empty target. `co.java` grounds the request `\05FF000F00<packed-serial><destination><inner-checksum>`. `cn.java` packs the 20-bit and 12-bit decimal serial components into four big-endian bytes. The checksum covers 00, those four bytes and the target. For serial 101136.1558 and target 6, the literal request is `\05FF000F0018B106160615g\r`.

`co.java` correlates a response source and the CAL prefix `87 00 <packed-serial>`; it does not interpret its final two CAL bytes. Those bytes are therefore required as explicit fixture data. With the deliberately chosen 00/00 tail, the response vector is `g.86061000870018B106160000F8\r\n`. This is a test response with a source-grounded prefix and checksum, not a claim about the meaning or actual values of hardware reply-tail bytes. No supported native commissioning test currently exercises the broadcast branch.

The fixture rejects malformed broadcasts, invalid inner checksums, occupied/unconfigured targets and ambiguous identities. A valid unknown serial receives only PCI link confirmation and changes nothing. An injected persistence failure restores the original memory and empty-slot state before returning an error. Stored state preserves serial reply tails and empty slots; older snapshots remain supported.

## Verification evidence

`tests/test_serial_commissioning.py` covers the matching database guard, stale metadata, normal-address rejection, recovery JSON/method metadata, no-op success statuses and lost replies. Its native fixtures use unique disposable projects, a fresh simulator with 0.01-second transport latency, a database unit at 6, and no physical hardware. The typed helper tests check exactly one SET and protected STORE, no serial broadcast, unchanged full database XML, persisted simulator state and explicit recovery after a deliberately lost response. An armed fault that affects UNRAVEL's internal serial scan is not triggered by the scalar operation; its separate raw-command regression demonstrates movement to 2 and recovery observation locating the serial there.

`tests/test_simulator_serial_addressing.py` checks the independent literal broadcast/UNLOCK vectors, unknown/malformed inputs, explicit configuration, disk reload and failed persistence. All simulator test modules are run to check shared clock, labels, Trigger/Enable, lighting and existing physical-address behavior.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_SERIAL_COMMISSION_REPORT=research/runtime/serial-commission-acceptance.json \
.venv/bin/python -m unittest tests.test_serial_commissioning -v
.venv/bin/python -m unittest discover -s tests -p 'test_simulator*.py' -v
```

Occupied-unit displacement, address cycles, duplicate physical addresses, general serial broadcasts against native PCI/bridge units and hardware-wide commissioning parity remain unverified.

Recorded evidence includes [raw MATCHDB fallback](native-matchdb-internal-scan-fallback.json) and [healthy singleton no-op](native-unravel-healthy-singleton-noop.json). Earlier MATCHDB acceptance records are preserved as [pre-mitigation commissioning](native-matchdb-commissioning-before-mitigation.json) and [pre-mitigation lost reply](native-matchdb-lost-reply-before-mitigation.json); they do not verify the scalar mitigation.

Current scalar evidence: [successful commissioning](native-serial-commissioning-acceptance.json), [lost-reply recovery](native-serial-commissioning-lost-reply.json), and [raw fallback comparison](native-matchdb-internal-scan-fallback.json). The [hidden occupied target regression](native-mmi-address-guard-acceptance.json) verifies the shared PINGU coverage guard. Earlier checkpoints predating the scalar and PINGU mitigations retain their separately documented limitations.

# eDLT Clear Dynamic Labels

`EdltDynamicLabelClear` plans and issues one original `LABEL CLEAREDLT` request for a physical KEYGL5 unit whose native identity `Version` is `5.5.00`. It reports whether C-Gate accepted the request. **It does not verify physical label erasure or persistence.**

This is the Toolkit unit dialog's Clear Dynamic Labels operation. Application/group label commands in `labels.py` have a different target and scope. This operation has no application, group, language or label-family selector.

## CLI and library

```sh
cbus-toolkit cgate --host 127.0.0.1 edlt-label-clear plan //OWNED/254/p/5 \
  --serial 101183.1666 --plan-output clear-plan.json

cbus-toolkit cgate --host 127.0.0.1 edlt-label-clear request //OWNED/254/p/5 \
  --serial 101183.1666 --plan-output clear-request-plan.json
```

Each CLI invocation builds a fresh plan. An optional output path must be new; the CLI writes and synchronizes that evidence before the request. It contains observed identity, runtime and database fingerprints. It is not a backup of the physical unit's dynamic-label cache. The request repeats the plan guards before issuing the native command. Exit zero means a plan was produced or the native request was accepted; it does not mean labels were independently observed to disappear.

The same workflow can use cmqttd's embedded C-Gate listener when
`CMQTT CAPABILITIES` reports `edlt_label_clear: true`. cmqttd sends the control
through its shared CNI connection while MQTT remains active, so Windows and the
vendor C-Gate process are not required. The evidence and verification limits
are unchanged.

```python
from cbus_toolkit.edlt_label_clear import EdltDynamicLabelClear

manager = EdltDynamicLabelClear(client)
plan = manager.plan("//OWNED/254/p/5", expected_serial="101183.1666")
result = manager.request(plan)
```

`plan()` returns an immutable `EdltLabelClearPlan`; `as_dict()` exports the evidence. `request()` requires that exact plan type, validates its canonical fields before I/O, and returns a dictionary. A plan is not an instruction to open a network: the target network must already be running.

## Preconditions and scope

The helper admits one full physical path `//PROJECT/NETWORK/p/UNIT`, with an eight-character-or-shorter project name, network address 0–255 and unit address 1–254. Database paths, wildcards, selections and extra address syntax are rejected. Its supported profile is KEYGL5/5.5.00 with the caller's known native decimal-dot serial. The native command itself permits broader eDLT profiles; those profiles have not been enabled in this typed helper.

The native interface must be running and wired, with idle synchronization, `AutoUnravel=no`, `AutoUpdate=no` and `Retries=0`. Runtime and database interface descriptions must agree and describe one direct CNI or Serial interface. The helper does not change those settings. Bridges and wireless gateway topologies are excluded.

Planning performs a physical identity refresh, including the native whole-network fast synchronization, then checks that the target has exactly one healthy identity. It requires a complete, healthy cached inventory with unique known serials. The independent native `NET PINGU` coverage reader must return the same nonempty address set. Runtime and database fingerprints must remain unchanged through observation. Requesting repeats these checks and then repeats `PINGU` immediately before the one `LABEL CLEAREDLT` command. The reads are sequential observations, not an atomic exclusion of another controller.

## Outcomes and recovery limits

| Outcome | Meaning |
| --- | --- |
| `native_accepted` | One complete, exact `200 OK.` reply was returned by C-Gate. |
| `native_rejected` | C-Gate returned a complete 4xx/5xx error response. Device side effects remain possible. |
| `outcome_uncertain` | Transport, framing, an unexpected reply or interruption prevented a classified native outcome. |

Every attempted result retains `request_attempted=true`, `automatic_retries=0`, `device_side_effect_possible=true`, `labels_cleared_verified=false`, `label_persistence_verified=false`, `strict_receipt_correlation_verified=false` and `database_updated=false`. Native reply lines and identity/pre-request coverage evidence remain available. An ordinary uncertain failure raises `EdltLabelClearUncertain` with `.details`. An interruption preserves the original exception object and attaches `.edlt_label_clear_evidence`. `manager.last_evidence` also retains the attempted result. After attempting the command the helper sends no further requests, retries or verification commands, including on interruption.

There is no evidenced operation here that inventories all dynamic labels stored by a physical eDLT. A database or PP backup cannot reconstruct that cache. Consequently this helper provides no automatic rollback or label-restoration claim. A later explicit resend of known labels is a separate action.

## Original evidence and fixture acceptance

The pinned [original research report](edlt-label-clear-research.json) and [source/wire analysis](edlt-label-clear-research.md) trace the original form, model, communicator and exact native Java/bytecode path. The first literal command was `\46050900A4FF43C1EAq\r`; the normal response was `q.860510010032FF43F0\r\n`. The original native path accepted an extended response, a response addressed to a different local PCI and a deliberately invalid checksum. All those original research cases deliberately kept label records unchanged, including the 200 cases. This is why native acceptance remains weaker than strict packet correlation or label erasure.

`EdltLabelClearFixture` is an isolated opt-in simulator with separate committed label caches for units 4 and 5. It recognizes only the exact clear control `A4 FF 43 C1 EA` on fixture unit 5. Callers must explicitly select `clear_committed_labels_preserve_languages`. The policy clears committed text, Unicode, icon and dynamic records, preserves language selections, and preserves the other unit's cache and baseline programming/network state. Pending uploads and real firmware erase behavior are not modeled. Ordinary fixture writes and application/broadcast mutations remain unsupported.

The whole saved fixture document uses a separate versioned format and serializes both caches and the fixed topology. Loading rejects unknown fields, duplicate keys, nonfinite values, oversized files, links, malformed label records and topology changes. Persistence uses a synchronized temporary file, atomic replacement and directory synchronization. The normal acknowledgement is emitted only after successful declared persistence. Failures preserve the first interruption and distinguish restored memory from an observed replacement whose durability remains uncertain. External file changes are rejected; this does not claim an atomic compare-and-swap against concurrent external writers.

Focused tests cover independent ordinary/SRCHK and cached-header literals, fragmented loopback sockets, all eight reply faults with and without clearing, per-unit preservation, restart equality, malformed state, and persistence/interruption failures. The full helper, fixture and CLI suite passed **27 tests with zero skips** on Python 3.13.14 (194.762s) and Python 3.10.20 (189.885s), with identical source hashes before and after both runs. Nine native fault cases and the CLI lifecycle ran against original C-Gate 3.4.0 build 2001 on an owned macOS loopback endpoint. These reproduce accepted replies without fixture erasure, a missing reply after fixture erasure, and unchanged database/programming state. The [final acceptance artifact](../research/fixtures/edlt-label-clear-acceptance.json) pins both runs, exact source hashes, wire records and independent fixture observations.

To repeat native acceptance, set `CBUS_CGATE_TEST_HOST`, `CBUS_CGATE_TEST_PORT` and `CBUS_CGATE_SIMULATOR_HOST` for an isolated oracle able to reach the owned fixture, then run `tests.test_edlt_label_clear`, `tests.test_simulator_edlt_labels` and `tests.test_cli_edlt_label_clear`. The final runs used `127.0.0.1`, port `20033` and simulator host `127.0.0.1`. Every project was newly created and removed by its test. No physical network or hardware was used.

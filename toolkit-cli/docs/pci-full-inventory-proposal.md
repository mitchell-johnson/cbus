# Proposed direct PCI serial inventory coordinator

This is the accepted design record. The implemented contract is documented in
[pci-full-inventory.md](pci-full-inventory.md). It combines the
verified [MMI collector](pci-mmi.md) and [serial collector](pci-serials.md) into
one bounded, read-only sequence. It does not enable addressing or programming.

The design has been implemented. The prerequisite audit identified the need to preserve
the original exception object, partial observations and one-shot closure when
cancelled. The implementation now retains the last successfully sampled elapsed
time if the final sample fails, marks the result interrupted, and attaches its
evidence before re-raising. Tests cover interruption during receive, close and
final timing, including a second interruption during cleanup without replacing
the first. A subsequent timing review also added an absolute parent deadline
and fresh admission after child construction.

## Proposed API

```python
inventory = PCIInventoryCollector(
    "127.0.0.1", 10001,
    local_unit=16,
    overall_timeout=600.0,
    observation_timeout=10.0,
    confirmation_timeout=2.0,
    response_timeout=5.5,
    quiet_period=2.0,
    max_mmi_frames=7,
    max_serial_frames=7,
    max_unrelated=64,
    max_bytes=65536,
    command_checksum=False,
).collect_inventory()
print(inventory.as_dict())
```

The class would live in a separate `pci_full_inventory.py` module. As with the
existing collectors, the endpoint must be a numeric IP address and the caller
must supply the known local PCI address and exclusive ownership of the
configured transport. Ownership must remain exclusive for the entire sequence,
including the gaps between connections. The coordinator neither discovers nor
changes interface settings and cannot enforce ownership against other software.

Each object is one-shot. Every child observation uses and closes a fresh TCP
connection. There are no retries, raw commands, interface resets, C-Gate
lifecycle changes, or write methods. No failed stream is reused. At most 258
requests are possible: two MMIs and one serial request for each of 256 addresses.

## Sequence and partial failures

1. Collect a complete install MMI, including explicit coverage of addresses
   0 through 255 and presence of the supplied local address.
2. In ascending order, query IDENTIFY4 for every address with a nonzero initial
   MMI state. This includes the local PCI and address 255. Preserve every child
   serial observation, including multiple known serials at one address.
3. Collect a second complete install MMI. Compare all 256 states with the first
   response, not only the set of present addresses.

An incomplete child observation stops the sequence. The result retains that
child's evidence, previously completed children, and the addresses/phases not
attempted. No further request follows a framing, correlation, timeout, resource
limit, unknown serial, transport, or close failure. The final MMI is therefore
absent if an earlier child failed; the result must not imply that membership was
rechecked. A successfully completed serial window reporting no serials is a
consistency issue, rather than a framing failure, so the remaining planned reads
and final MMI can still document the change.

State 3 flags and completed duplicate-address serial windows do not stop
collection. They remain separate health and identity issues. Raw observations
are never rewritten to make an inventory look consistent.

An interruption closes the active child's socket, retains all completed and
partial evidence in `collector.last_observation`, attaches a JSON-safe
`pci_inventory_observation` dictionary to the original exception, and re-raises
that exception. There is no follow-up request after interruption. Cleanup failure
must remain visible without replacing the original interruption.

## Proposed result contract

`as_dict()` would identify `cbus-pci-inventory-observation-v1` and include:

| Field | Meaning |
| --- | --- |
| `initial_mmi`, `final_mmi` | Complete nested MMI evidence, or null if not attempted. |
| `serial_observations` | Ordered nested serial results, including the last partial result. |
| `planned_addresses`, `unattempted_addresses` | Initial MMI membership and remaining reads. |
| `collection_complete` | Both MMI observations and every planned serial window completed. |
| `membership_unchanged` | Both MMIs completed and all 256 states are identical; null if comparison is unavailable. |
| `consistent` | Collection completed, membership is unchanged, every initially present address returned a known serial, and no known serial occurs at different addresses. |
| `complete` | Alias for `consistent`; this does not assert unique addresses or healthy MMI states. |
| `duplicate_addresses` | Addresses that returned multiple distinct known serials. |
| `serial_conflicts` | A known serial observed at multiple different addresses, with all observed locations. |
| `missing_serial_addresses` | Completed empty serial windows for initially present addresses. |
| `changed_states` | Address and before/after MMI states, including additions and removals. |
| `error_addresses` | Addresses with state 3 in either completed MMI. |
| `unique` | Complete, and no duplicate addresses or serial conflicts. |
| `status` | `incomplete`, `inconsistent`, `mmi_errors`, `duplicate_address`, or `complete`, in that precedence order. |
| `termination` | Completed sequence, failing child phase, overall budget exhausted, or interrupted. |
| `timing`, `limits` | Whole-sequence elapsed/budget, per-observation bounds, and phase start/end times. |

The result would also retain the numeric endpoint, local address, request count,
all child connection-closure results, `automatic_retries=0`,
`physical_addresses_changed=false`, `database_updated=false`,
`atomic_snapshot=false`, and `authorizes_address_mutation=false`.

Status precedence is for concise display; all issue lists remain available when
several conditions coexist. A duplicate address can have `complete=true` and
`unique=false`. A CLI should exit zero only for status `complete`. No unit type,
firmware, or database identity is invented from an IDENTIFY4 serial block.

## Deadline contract

The whole-sequence monotonic budget starts before the initial MMI. The proposed
overall bound is finite and positive, at most 3600 seconds; the default 600
seconds allows a two-second quiet interval for up to 256 addresses with ordinary
short responses. That default is a resource limit, not a guarantee every network
can finish within it. Each child also retains its existing finite observation,
confirmation, response, frame, unrelated-event, and byte limits.

Immediately before each child, its overall timeout is capped by the smaller of
`observation_timeout` and remaining sequence time. Configured confirmation,
response and quiet durations are never silently shortened. If the remaining
budget cannot admit the child's existing constructor constraints, the
coordinator stops before creating a socket and reports the next phase as
unattempted. The final MMI is mandatory for a complete result; exhausted budget
after the serial reads still produces an incomplete inventory.

The coordinator checks the deadline after each child as well as before starting
the next. Results returning at or after the overall deadline are retained but
cannot produce a complete inventory. No new connection, command, or retry begins
after budget exhaustion. As with the child collectors, this is a bounded I/O
deadline contract; Python scheduling or socket cleanup can make measured elapsed
time exceed the requested budget. Evidence serialization is not a physical I/O
operation and occurs after the observation ends.

## Address changes and limits

An address added, removed, or given a different MMI state between the two full
MMIs is reported as inconsistent. New addresses are not automatically scanned
and old addresses are not retried. A serial seen at two addresses is ambiguous:
the coordinator does not assume whether it moved during scanning or was already
duplicated. An initially present address with no serial reply is also
inconsistent, even if its MMI state later matches the initial response.

Identical MMI bookends cannot prove that serials did not swap addresses while the
set of occupied addresses remained unchanged. They also cannot detect a device
leaving and returning between observations. This first coordinator performs one
serial pass, explicitly reports a non-atomic observation, and provides no
identity-stability or persistent absence guarantee. The later
[selected-serial workflow](pci-selected-serial.md) has its own stronger,
independently tested guards. A second serial pass could add repeated identity
evidence, but would still not create an atomic snapshot and is outside this
first bounded implementation.

The original protocol carries no scan identifier in bare MMI blocks. Closing a
TCP session does not prove that the bus has no delayed responses. Fresh exclusive
transport ownership and the existing strict per-request correlation remain
preconditions. Digital fixture tests cannot establish analogue collision
coverage on real hardware.

## Independent test plan

- Literal TCP peer: complete initial MMI, local serial, two serials at 255,
  identical final MMI; assert four fresh connections, exact requests, all three
  identities, complete collection, duplicate status, and no writes.
- Missing/overlapping/reordered initial or final MMI blocks; missing local PCI;
  malformed or rejected confirmations; retain null coverage and do not infer
  absent addresses.
- Add/remove/change one address between MMIs; an initially present address with
  an empty serial window; one serial reported at two addresses; preserve all
  conflicting observations without rescanning.
- Fragmented responses, repeated known serial replies, late second serial,
  unknown or conflicting serial data, wrong route/source/destination,
  unrelated traffic, frame and byte saturation; stop after incomplete children.
- Initial and final MMI state 3 with otherwise successful serial reads;
  distinguish complete collection from healthy/unique identity status.
- Deterministic clock/socket tests for total budget exhaustion before a child,
  during a child, and before the mandatory final MMI; verify configured quiet
  duration is retained and no later socket opens.
- Interruption and close failure after partial evidence; preserve original
  exception and evidence, and assert no later request or replay.
- Native comparison on the existing explicit two-node duplicate fixture: direct
  initial/final presence `{16,255}`, three known serials, then sequential native
  PINGU/CHECKUNIT/serial evidence. Unique disposable project, post-ready verified
  Retries=0, unchanged complete database XML and fixture snapshot, no unsupported
  simulator request, and successful cleanup. Clients never own the fixture
  endpoint concurrently.

The literal frame and timing sources are already recorded in
[duplicate-discovery-source-evidence.json](duplicate-discovery-source-evidence.json),
[mmi-coverage-source-evidence.json](mmi-coverage-source-evidence.json), and the
two child collectors' native reports. The coordinator adds ordering, aggregation
and a total budget; it must not claim additional native protocol guarantees.

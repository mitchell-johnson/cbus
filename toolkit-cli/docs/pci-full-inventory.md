# Direct PCI serial inventory

`PCIInventoryCollector` reads full install MMI coverage, collects all serial
replies at every initially present address, and reads full MMI coverage again.
It preserves duplicate identities, incomplete observations and changes between
the two MMI responses. It performs no writes, retries or interface configuration.

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --local-unit 16 inventory
cbus-toolkit pci --host 127.0.0.1 --port 10001 --local-unit 16 --timeout 120 inventory
# Add --checksum before inventory only when outgoing SRCHK is already enabled.
```

```python
from cbus_toolkit.pci_full_inventory import PCIInventoryCollector

collector = PCIInventoryCollector(
    "127.0.0.1", 10001, local_unit=16,
    overall_timeout=600.0, observation_timeout=10.0,
    confirmation_timeout=2.0, response_timeout=5.5, quiet_period=2.0,
    max_mmi_frames=7, max_serial_frames=7,
    max_unrelated=64, max_bytes=65536, command_checksum=False,
)
observation = collector.collect_inventory()
print(observation.as_dict())
```

The endpoint must be a numeric IPv4 or IPv6 address without a scope suffix. The
caller must know the attached PCI address and exclusively own the configured
transport for the entire sequence, including gaps between connections. The
collector cannot establish that ownership or disconnect C-Gate on the caller's
behalf. No SMART reset, BASIC discovery, address change or programming command
runs. The object is one-shot; each child observation uses one fresh TCP
connection and closes it on every outcome.

## Collection and result meanings

The initial [MMI observation](pci-mmi.md) must cover all 256 addresses with
ordered, contiguous, valid blocks and include the supplied local PCI address.
The collector then visits each nonzero address in ascending order, including
the local PCI and address 255. At each address the [serial collector](pci-serials.md)
reads IDENTIFY4 and retains all matching replies throughout its bounded quiet
window. A final complete MMI is mandatory; its full 256-state vector is compared
with the first response.

`PCIInventoryObservation.as_dict()` emits `cbus-pci-inventory-observation-v1`:

| Field | Meaning |
| --- | --- |
| `collection_complete` | Both MMIs and all planned serial windows completed within the sequence budget and closed successfully. |
| `membership_unchanged` | Both full MMI state vectors match; null if either observation is incomplete or absent. |
| `consistent`, `complete` | Collection completed, membership matches, every initially present address returned a known serial, and no known serial appeared at different addresses. |
| `unique` | Complete inventory without multiple known serials at one address. |
| `mmi_healthy` | Collection completed without state 3 in either observed MMI. |
| `healthy` | Unique, complete inventory with healthy MMI observations. |

Status precedence is `incomplete`, `inconsistent`, `mmi_errors`,
`duplicate_address`, then `complete`. The CLI exits zero only for `complete`.
The issue lists remain available even when more than one issue applies. A
duplicate address can have `complete=true`, `unique=false` and status
`duplicate_address`. An MMI error state can have `complete=true` while health
flags are false. Presence does not establish how many physical units share an
address, and MMI state 1 versus 2 is not assigned an unverified interpretation.

The result includes both nested MMI observations, ordered serial observations,
`planned_addresses`, `unattempted_addresses`, `changed_states`,
`missing_serial_addresses`, `duplicate_addresses`, `serial_conflicts` and
`error_addresses`. Nested observations preserve literal requests, received
bytes, decoded replies, confirmation, timing, termination, errors and connection
closure evidence. A serial seen at two addresses is reported as ambiguous; no
assumption is made about whether it moved or was duplicated.

An incomplete child stops further requests. There is no final MMI after an
earlier framing, correlation, transport, unknown-serial, close, timeout or
resource-limit failure. Previously read identities and the partial child remain
available. A completed empty serial window is an inconsistency, so remaining
planned reads and the final MMI still run. Completed duplicate windows and MMI
error states also remain observable without stopping the sequence. New addresses
found in the final MMI are reported without automatically scanning them.

## Time, limits and cancellation

The overall monotonic budget starts before the first MMI and includes the full
sequence. Its default is 600 seconds, with an accepted range above zero through
3600 seconds. Up to 258 requests are possible: two MMIs and 256 serial windows.
The default budget allows the ordinary two-second quiet interval for 256
addresses, but does not guarantee a busy network will finish in time.

Every child also has an observation bound, capped by the remaining overall
budget. Confirmation, MMI response and serial quiet durations are preserved.
Admission is checked again after child construction, and the absolute parent
deadline is passed internally to the child. A later child start cannot extend
its network I/O window. Child collectors also check expiry before creating a
socket, connecting, and transmitting.
If the remaining time cannot admit those configured durations, the next socket
is not opened. If time runs out before the mandatory final MMI, the inventory is
incomplete even when all planned serial windows completed. The coordinator also
checks the budget after each child and before producing a complete result. Data
returned too late remains evidence but cannot complete the inventory.

Child time bounds remain limited to 60 seconds. Frame, unrelated-event and byte
limits apply independently to each child observation; they are not a shared
quota. The result records each phase's start/end time and admitted observation
budget, plus the actual overall elapsed time. Socket cleanup and Python
scheduling can extend measured elapsed time beyond the I/O budget. No new
request begins after detected exhaustion and no failed request is replayed.

Cancellation retains `collector.last_observation`, attaches its JSON-safe
dictionary as `exception.pci_inventory_observation`, and re-raises the original
exception after the active child closes. Child evidence is attached under
`pci_serial_observation` or `pci_mmi_observation` as applicable. The CLI preserves
this evidence and exits 130 for `KeyboardInterrupt`. A later cleanup or clock
interruption does not replace the first exception. If the final clock sample
fails, elapsed time uses the last successful sample and the observation is
marked interrupted. No subsequent request follows cancellation.

## Scope and evidence

This is a non-atomic observation. Matching MMI responses cannot show whether two
units swapped addresses while occupied-address states remained identical, or
whether a unit left and returned between reads. There is one serial pass.
Results explicitly set `atomic_snapshot=false` and
`authorizes_address_mutation=false`; they do not establish persistent absence or
authorize a selected-serial move. Bare MMI responses have no per-scan identity,
and fresh TCP connections do not prove the physical bus is free of delayed
traffic from another actor.

The [native comparison report](native-pci-full-inventory-acceptance.json) records
the default two-second serial windows against an explicit duplicate fixture:
MMI addresses 16 and 255, local serial `100966.1187`, and serials `101136.1558`
and `101136.1559` sharing address 255. Four fresh direct sessions issue exactly:

```text
\05FF00FAFF00g\r
\4610002104g\r
\46FF002104g\r
\05FF00FAFF00g\r
```

Original C-Gate subsequently reports the same MMI presence, local serial, and
duplicate serial replies using PINGU/CHECKUNIT. The clients use the endpoint
sequentially. The unique disposable project has post-readiness Retries=0
verified, complete database XML and fixture state remain unchanged, no
unsupported simulator command occurs, and cleanup succeeds. The two child
collectors' source and literal evidence are linked in their documentation.
This verifies a simulated digital exchange, not analogue collision behavior or
hardware-wide inventory coverage.

Tests additionally cover checksummed and fragmented literal exchanges, complete
duplicate versus unique status, missing/repeated/reordered coverage, changed
membership and MMI states, empty serial windows, cross-address serial conflicts,
partial failed reads, resource admission and exhaustion, interruptions, cleanup,
failures of final timing extraction, and expiry during child construction,
connection setup, or a receive window.

```sh
PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_pci_full_inventory.PCIFullInventoryTests tests.test_pci_interruption tests.test_cli_pci_inventory
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_PCI_FULL_INVENTORY_REPORT=docs/native-pci-full-inventory-acceptance.json PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_pci_full_inventory.NativePCIFullInventoryTests
```

# Direct PCI install MMI

`PCIMMICollector` reads one install MMI directly from a numeric-IP PCI/CNI
endpoint. It verifies contiguous coverage of all 256 unit addresses and checks
that the supplied local PCI address appears in the response. It performs no
serial reads, interface configuration, retries or address changes.

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --local-unit 16 --timeout 10 mmi
# Use the global --checksum option only if outgoing SRCHK is already enabled.
```

```python
from cbus_toolkit.pci_inventory import PCIMMICollector

observation = PCIMMICollector(
    "127.0.0.1", 10001, local_unit=16,
    overall_timeout=10.0, confirmation_timeout=2.0, response_timeout=5.5,
    max_frames=7, command_checksum=False,
).collect_mmi()
print(observation.as_dict())
```

The caller must supply the known attached PCI address and have exclusive
transport ownership. Numeric IPv4 and IPv6 addresses are supported; hostnames
and scoped IPv6 addresses are rejected before connecting. Each collector uses
one fresh TCP connection and is one-shot. It closes that connection on success,
failure or interruption. A failed or completed object cannot issue another
request. No BASIC discovery, SMART reset or C-Gate lifecycle command runs.

## Coverage and result meanings

`MMIObservation.as_dict()` emits `cbus-pci-mmi-observation-v1`. Its 256-element
`states` list distinguishes explicit state 0 from `null`, which means the address
was not covered by an accepted block. `missing_ranges` uses a starting address
and exclusive end. Raw received bytes and every decoded matching block remain
available on partial failure.

| Field or status | Meaning |
| --- | --- |
| `coverage_complete` | Every address was covered by ordered, contiguous, valid blocks. |
| `local_present` | The supplied local address has a nonzero observed state. |
| `complete` | Coverage, local presence, confirmation and connection cleanup all succeeded. |
| Status `complete` | Complete observation without native MMI error flags. |
| Status `mmi_errors` | Complete observation containing state 3 error flags. |
| Status `incomplete` | A coverage, correlation, framing, local-presence, transport or resource-limit failure occurred. |

The CLI exits zero only for status `complete`. `addresses` contains observed
nonzero addresses; it does not count physical devices or establish unique
identities. `error_addresses` contains addresses with state 3. The original
source establishes state 0 as absent, states 1 and 2 as present, and state 3 as a
native error flag. This API preserves 1 and 2 without assigning an unverified
distinction to them.

A complete all-zero response has `coverage_complete=true` but
`local_present=false`, `complete=false` and termination `local_absent`. A missing
middle or final block leaves the corresponding addresses unknown. A repeated,
overlapping or out-of-order block terminates with `coverage_error`; a count of
three lines does not substitute for full coverage.

The result also includes the request and received bytes, PCI confirmation,
unrelated traffic, termination reason, errors, timing, limits and
`connection_closed`. A close error preserves the observation and prevents a
complete result. An interruption retains `collector.last_observation`, attaches
its JSON as `exception.pci_mmi_observation`, and re-raises the original exception
after closing the connection. No further command follows.

## Framing, timing and scope

The single request is:

```text
ordinary: \05FF00FAFF00g\r
SRCHK:    \05FF00FAFF0003g\r
```

Supported responses are direct standard C/D MMI frames for application FF.
Their count byte determines the data length; four two-bit states are decoded
from each payload byte, least significant pair first. Each checksum, length,
offset and range is verified. Routed and extended MMI forms are outside this
collector's scope and produce incomplete results. Valid other-application MMI
and ordinary CAL traffic are retained separately and do not contribute to
coverage or extend its response deadline.

The collector requires its matching PCI confirmation before accepting any
coverage block. Foreign/duplicate confirmations and extra overlapping blocks
are ambiguous. All bytes in the receive chunk that completes coverage are
processed, so trailing malformed or partial data in that chunk prevents a
complete result.

The overall deadline includes connection setup and transmission. A separate
confirmation deadline starts after sending. After successful confirmation,
the response deadline starts and restarts after each matching accepted block.
Timeouts never fill missing states with zeros. All configured time bounds must
be finite, positive, no more than 60 seconds, and fit within the overall bound.
The default response timeout is 5.5 seconds, matching the observed native
ResponseDelay default; native configuration can change that value.

Unlike a serial seeker, MMI has a structural end: validated coverage reaches
address 256. The collector completes when that coverage and the current receive
chunk are complete, rather than waiting for a serial quiet window. Reaching the
frame limit before full coverage is incomplete; reaching it with all addresses
covered is allowed. Incoming byte and unrelated-event limits are independent.

The protocol carries no per-scan identity in bare MMI blocks. A fresh connection
does not prove the physical bus contains no late traffic from another actor.
The supplied local address is checked for presence, not independently bound to
a hardware serial. Complete coverage is evidence from this response, not an
atomic inventory of every physical device. A full multi-address serial scan and
selected-serial commissioning remain separate work.

## Independent evidence

The original source and bytecode are identified in
[mmi-coverage-source-evidence.json](mmi-coverage-source-evidence.json). The
[native coverage audit](native-mmi-coverage.md) explains why explicit coverage
tracking is required and how native PINGU differs from SYNC/CHECKUNIT.

The independently literal duplicate-fixture response is:

```text
g.D8FF000000000001000000000000000000000000000000000028\r\n
D8FF5800000000000000000000000000000000000000000000D1\r\n
D6FFB00000000000000000000000000000000000000080FB\r\n
```

It covers addresses 0–87, 88–175 and 176–255, with states 16=1 and 255=2. Two
explicit fixture devices share address 255, so presence alone cannot detect
their multiplicity. The [native comparison report](native-pci-mmi-acceptance.json)
records the direct collector and exact C-Gate `NET PINGU` agreeing on addresses 16
and 255. They use the fixture sequentially. Complete database XML and fixture
state remain unchanged and cleanup succeeds. This verifies a simulated digital
exchange, not analogue collision behavior or hardware-wide coverage.

Independent literal tests include segment boundaries, state flags, checksums,
lengths, omitted/repeated/reordered ranges, fragments and late replies, wrong
confirmations, unrelated traffic, finite bounds, disconnects and interruptions.

```sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_pci_inventory.PCIMMICollectorTests
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_PCI_MMI_REPORT=docs/native-pci-mmi-acceptance.json PYTHONPATH=src .venv/bin/python -m unittest tests.test_pci_inventory.NativePCIMMICollectorTests
```

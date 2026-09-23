# Duplicate-address discovery fixture

`DuplicateAddressSimulator` is an opt-in, read-only fixture containing two
explicit KEYE1 2.5.00 physical nodes at address255 and a PC_CNIED 5.5.00 local
interface. Each node has its own serial and parameter blocks. The existing
`PCISimulator` address-keyed API and state-file format are unchanged.

```python
from cbus_toolkit.simulator_duplicates import DuplicateAddressSimulator

# nodes: exactly two explicit UnitState objects at255; distinct IDENTIFY4
# serials, matching UnitAddress bytes, otherwise identical read-only profiles.
# pci: explicit PC_CNIED UnitState at1..254 with a third known serial.
sim = DuplicateAddressSimulator(nodes, pci, response_delay=0.01)
with sim.running("127.0.0.1", 0) as endpoint:
    print(endpoint)
```

`sim.nodes` returns detached copies keyed by serial. `sim.snapshot()` retains
both physical nodes, including their shared address, under
`cbus-duplicate-address-discovery-fixture-v1`. The inherited `units[255]` is
only a representative for the base simulator's read/MMI plumbing; it is not a
complete inventory of this topology. `state_path` is rejected. Neither this
snapshot nor its topology can be loaded as a standard simulator state file.

Only BASIC local-address discovery, install MMI, normal IDENTIFY, RECALL and
explicit status reads are accepted. Unlock, STORE, application commands,
serial-address broadcast and OEM programming transport are rejected before
state changes. The fixture cannot commission or readdress either node.

Each address255 read returns one PCI command confirmation and two separately
checksummed CAL replies, in input-node order. This models two distinct frames
received by the PCI, without claiming to model analogue bus contention or
device response timing. Both fixture nodes use the same MMI state: MMI shows
address presence, while the serial seeker distinguishes the identities.

## Native evidence

The original C-Gate `cT.class` constructor issues IDENTIFY4 with multiple
response collection and a 2000ms receive window. Its parser reads the four
packed serial bytes at attribute offsets5..8; its classifier deduplicates
serial strings and returns the duplicate result when more than one remains.
The exact class hashes and method bytecode offsets are recorded in
[duplicate-discovery-source-evidence.json](duplicate-discovery-source-evidence.json).

The independent literal vector is:

```text
request: \46FF002104g\r
reply:   g.86FF10008D0438FFFFFFFF18B10616A200051A\r\n
         86FF10008D0438FFFFFFFF18B10617A2000519\r\n
```

The first block contains captured serial101136.1558. The second contains the
explicitly generated fixture serial101136.1559; it is not a second hardware
capture. Both replies retain source address255.

The [native acceptance report](native-duplicate-discovery-acceptance.json)
records exact C-Gate `NET CHECKUNIT` returning duplicate-address classification
after this two-frame exchange. The test uses a unique disposable project,
AutoUnravel=no, AutoUpdate=no and Retries=0. It independently compares complete
fixture snapshots and database XML before and after discovery, rejects any
unsupported wire command, and checks that no unlock, STORE or serial-address
broadcast was sent.

`NET CHECKUNIT` calls the native checker with its verbose flag disabled, so
the command does not expose the two serial strings as an inventory. The wire
evidence and original classifier establish their detection. Existing
`NativeSerials.refresh(..., units=[255])` deliberately returns an incomplete
inventory with `duplicate_address`, no serial and no usable `UnitIdentity`.
In this native probe, runtime `Units` contained only the local PCI and network
State was `ok`; those fields must not be interpreted as absence of duplicates.

The same test also calls the default `NativeSerials.refresh(network)` without
a unit selection. Its native `NET CHECKUNIT ... *` expands from fresh install
MMI addresses and reports both local PCI16 and duplicate255, even though cached
`Units` is still16. The returned whole-network inventory retains both records,
has `requested=null` and `complete=false`, and exposes no identity for255.
The report preserves the literal default-check reply and all refresh commands.

The test can be reproduced with:

```sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_simulator_duplicates.DuplicateSimulatorTests
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_DUPLICATE_DISCOVERY_REPORT=docs/native-duplicate-discovery-acceptance.json PYTHONPATH=src .venv/bin/python -m unittest tests.test_simulator_duplicates.NativeDuplicateDiscoveryTests
```

The next commissioning extension requires a serial-keyed persistent topology
and independently verified serial-broadcast replies before any mutation is
enabled. Occupied displacement, cycles, duplicate local PCI addresses, bridge
relocation, analogue collisions and physical hardware commissioning remain
outside this fixture's coverage.

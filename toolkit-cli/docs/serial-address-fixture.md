# Serial-keyed address-assignment fixture

`SerialAddressFixture` is an opt-in test fixture in
`cbus_toolkit.simulator_duplicate_addressing`. It retains two separate KEYE1
physical identities even when both occupy address 255. The original
`DuplicateAddressSimulator` remains read-only; the normal simulator and its
state-file format are unchanged.

Construction requires two explicit KEYE1 2.5.00 `UnitState` profiles, an explicit
PC_CNIED 5.5.00 local PCI, destination allowlist, two opaque receipt bytes per
serial, and an address-memory policy:

```python
sim = SerialAddressFixture(
    nodes, pci,
    allowed_destinations=[6, 7],
    address_memory_policy="bus_only",  # or explicitly "parameter32"
    reply_tails={"101136.1558": b"\0\0", "101136.1559": b"\0\0"},
    state_path="fixture.json",
)
restored = SerialAddressFixture.from_state("fixture.json")
```

The serial is the persistent node key. Bus address and parameter 32 remain
separate values under `bus_only`; `parameter32` updates both. Neither policy
claims to model real firmware EEPROM behavior. `nodes` returns detached copies;
`snapshot()` contains both nodes, response order, revision, policies and
`firmware_persistence_verified: false`. Inherited `units[address]` is only a
temporary representative used for existing read/MMI plumbing.

The fixture accepts the exact explicit co broadcast and read-only IDENTIFY,
RECALL, STATUS and install MMI forms. Generic STORE, unlock, application writes
and Local SAL writes are rejected. Destinations must be explicitly allowed and
currently empty within this closed fixture universe. This guard is a fixture
constraint, not an assertion that physical firmware rejects occupied targets.
There are no other implicitly simulated units. Duplicate occupancy is supported
only at 255. Profiles must match apart from serial and address byte; wireless,
bridges and local-PCI relocation are outside the fixture.

`SerialAddressFault` explicitly controls `move`, `reply`, `bare`,
`reported_source` and `reported_serial`. A successful-looking receipt can be
returned without movement, movement can occur without a receipt, and reported
source/serial can differ from the moved node. `co_operations` records the actual
selected node, requested destination, fault, old/new address, persistence result
and raw receipt. It is process-local diagnostic evidence, not a durable journal.
Every request is a single operation; there is no retry or native MATCHDB fallback.

State loading is separate from creation and validates the entire document:
exact schema/fields, duplicate JSON keys, size, serial keys versus IDENTIFY4,
ordering, block bounds, supported profiles, fault options, occupancy and policy
consistency. Writes use a sibling temporary file, file flush/fsync and atomic
replace. Unexpected changes to the previous state bytes reject overwrite. This
check is not an interprocess lock; a fixture state file needs one exclusive
writer. Directory-entry durability after operating-system/power failure is not
claimed.

Persistence failures retain evidence. Before persistence starts, an interruption
restores the old node, parameter byte, revision and address representatives
without disk access. After a persistence attempt, the fixture checks whether the
exact proposed bytes are present: a committed replacement stays committed even
if an injected error follows it. Unknown disk state is reported as unknown and
in-memory restoration does not claim disk rollback. The original interruption
is retained, including when cleanup/probing also interrupts; its
`serial_address_fixture_operation` attribute preserves the operation evidence.

## Independent evidence

The request/parser vectors and exact source/class hashes are pinned in
[serial-address-codec-evidence.json](serial-address-codec-evidence.json).
The fixture implements decoding/checksums independently of the client encoder.
Tests use literal ordinary/SRCHK requests, serial replies and MMI segments.

[duplicate-address-fixture-acceptance.json](duplicate-address-fixture-acceptance.json)
records normal, missing-reply and forged-success cases. Independent full MMI
and per-address serial collections precede/follow each request and repeat after
reloading the state in a new server instance. The short 25 ms quiet windows are
explicit synthetic test timing, not a physical bus timing claim. The direct
collector's separate native/default-window acceptance remains its own evidence.

[native-duplicate-address-fixture-acceptance.json](native-duplicate-address-fixture-acceptance.json)
records original C-Gate discovering the selected serial at 6 and the other at
255 after fixture reload. C-Gate performs reads only; database XML and fixture
state remain unchanged. The PCI options byte is explicitly 07 for this native
read test, matching native initialization. Direct fault tests use explicit 05.
This distinction provides no evidence that either byte is a hardware prerequisite
for co.

Reproduce with Python 3.10+:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_DUPLICATE_ADDRESS_FIXTURE_REPORT=docs/duplicate-address-fixture-acceptance.json \
CBUS_NATIVE_DUPLICATE_ADDRESS_FIXTURE_REPORT=docs/native-duplicate-address-fixture-acceptance.json \
.venv/bin/python -m unittest tests.test_simulator_duplicate_addressing -v
```

The native test uses a unique disposable project and the loopback-owned
synthetic fixture. It never opens a user network or sends C-Gate an address
mutation command. A production selected-serial movement coordinator is still
only [proposed](selected-serial-coordinator-proposal.md).

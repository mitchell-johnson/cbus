# Native clock and burden acceptance

The Python CLI has exercised network clock enable/disable, gateway clock
recovery, and unit burden programming against C-Gate 3.4.0.2001 and an independent
TCP simulator. Every successful change was checked through native `NET CLOCKS`,
an independent PCI EEPROM read, and a new simulator instance loaded from disk.

The explicit fixture contains attached `PC_CNIED` unit 16 and remote `PC_CNICD`
unit 17, both at firmware 5.5.00. The native catalogue maps these identities to
`PCI.xml`. Its `ClockGenEnable` field is EEPROM address `3E`, bit 0; `Burden` is
the same byte, bit 6. Tagged direct STORE changes that byte and preserves
neighbouring bytes. Native `dz.b(int)` reads IDENTIFY attribute 16: its first
byte reports active clock in bit 0, enabled clock in bit 1, and burden in bit 7.

These layouts are independently evidenced by the vendor schema, decompiled
native implementation, captured native requests, and literal socket tests.
For example, enabling unit 17 emitted `A33E0001` after its routing header,
followed by ACK `86111000323E00E9`. Disabling emitted `A33E0000`.

The fixture is opt-in through `pci_settings_units=[16, 17]` and
`clock_generator=16`; existing raw, captured, and synthetic fixtures retain
their previous behaviour. `research/clock_fixture.py` builds the acceptance
fixture from [`pci-clock-synthetic.json`](../research/fixtures/pci-clock-synthetic.json).
Unknown byte layouts remain absent. The native field reader fetches 12 bytes
from `3E`, including seven bytes beyond its declared fields; those seven bytes
are explicitly named `A5` test padding, without field or default semantics.

## Failure and conflict observations

- Native `NET CLOCKS … 2` can return final `200 OK` with an intermediate
  `could NOT be enabled` failure. The test deliberately rejects the unit's
  STORE and verifies that its EEPROM and status remain unchanged. The typed
  clock result reports `complete: false`, and the CLI exits 1 after a fresh
  read-only inspection confirms the requested count was not reached.
- Asking the two-device fixture for three clocks also produces an incomplete
  CLI result, even when the native response has no per-unit error message.
- A competing programming lock makes a second CLI field edit fail with native
  `425 Lock failed`; the fixture state remains unchanged.
- Two enabled burdens remain visible as two enabled burdens. Neither the
  native command nor the simulated device invents an interlock. The acceptance
  restores one and then both burdens to disabled.
- A gateway with clock disabled and burden enabled recovers its clock through
  `NET CLOCKS … R`, preserving the burden bit.

The device simulator does not implement electrical loading, clock loss, clock
arbitration, duplicate physical units at an address, or EEPROM checksum
recalculation. The chosen generator is explicit test state; its active flag is
reported only while its clock is enabled. Native C-Gate can retry rejected
device requests internally; the acceptance records those attempts without
adding Python retries.

## Native confirmation race

An immutable-wheel run on Python 3.10 exposed an intermittent C-Gate sender
race. C-Gate 3.4.0.2001 `cl.a(aW, boolean)` writes the PCI command before
recording its confirmation tag and disabling transmission. Its receive thread
can consume an immediate simulator confirmation first; the sender then loses
that confirmation and stalls until its ten-second recovery timer fires.
The native log showed no outgoing IDENTIFY request during that stall. After
recovery, native code accepted a delayed bare local reply for the next unit,
producing an incorrect clock summary despite unchanged fixture EEPROM.

The clock fixture now explicitly sets `response_delay=0.01`, delaying each
nonempty reply by ten milliseconds. This is a test transport setting, not a
claim about physical PCI latency or a fix to the vendor implementation. The
general simulator retains zero delay by default, and the test still fails on
incorrect summaries without retrying the operation. A socket test checks the
delay, exact unchanged response bytes, and a single request. Timing settings
are connection configuration and are not persisted as device EEPROM state.

## Reproducing the acceptance

Use the existing isolated native oracle, whose CNI can reach the test host:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_CGATE_TEST_PORT=20023 \
CBUS_CLOCKS_REPORT=toolkit-cli/research/runtime/clocks-acceptance.json \
PYTHONPATH=toolkit-cli/src \
python3 -m unittest discover -s toolkit-cli/tests -p test_clocks_native.py -v
```

The test creates a unique marked project and points its only CNI at a fresh
simulator port. It closes and deletes the project afterward. Set
`CBUS_CGATE_SIMULATOR_HOST` if the oracle reaches the host through a name other
than `host.docker.internal`.

`test_simulator_clocks.py` runs without the vendor or native oracle and tests
literal wire vectors, protected bytes, persistence failure rollback, old
snapshot loading, and preservation of Enable application state alongside
clock settings. Full wire reports remain in ignored runtime storage; compact
permanent evidence is in
[`native-clocks-acceptance.json`](../research/fixtures/native-clocks-acceptance.json).

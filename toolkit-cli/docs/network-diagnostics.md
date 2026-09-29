# Network diagnostics

`cbus-toolkit cgate network diagnose` sends the same C-Gate commands as the
Toolkit Diagnostics dialog (`TfrmPingUnits`). It reports whether each unit is
present, along with its network voltage, burden and clock status.

```sh
cbus-toolkit cgate network diagnose //PROJECT/254 --project PROJECT
cbus-toolkit cgate network diagnose //PROJECT/254 --unit 4 --unit 16 --no-clock
```

```python
from cbus_toolkit.unit_diagnostics import NetworkDiagnostics

report = NetworkDiagnostics(client).diagnose("//PROJECT/254", units=[4, 16])
```

`--project` sends `PROJECT USE` first. Native C-Gate and the Rust services
select the project per session, so `DBGETXML` fails with `404 No project
selected` without it. `--unit` limits the per-unit reads to those database
units. `--no-voltage`, `--no-burden` and `--no-clock` clear the dialog's check
boxes.

## Sequence

The static review of the Toolkit executable fixes this order. The receipt
is [unit-diagnostics-static.json](../research/fixtures/unit-diagnostics-static.json).

1. `DBGETXML <network>` lists the database units.
2. `NET PINGU <network>` lists the units that are present.
3. Voltage: `GET <unit> NetVoltage` for each present unit.
4. Burden: `DO <unit> Psync`, then `GET <unit> BurdenActive`.
5. Clock: a PP session loads the unit and reads `ClockGenEnable`.

Only units that `NET PINGU` reports are queried. Units in the database but
not on the network are reported as `not-found`, with each requested field set
to `unknown`, never 0. Units that `NET PINGU` finds but the database lacks
are listed under `rescan_network`. As in the Toolkit, `KEYGL5` and `SENTEMP4`
units get no burden or clock request. They are reported as `not-enabled`
with basis `toolkit-unit-type-rule`. A `460 No such parameter:
ClockGenEnable` reply means the unit has no clock (basis
`no-clockgenenable-parameter`). If a unit's `Psync` fails, its
`BurdenActive` is not read and the burden is `unknown`.

The report is complete only when every selected unit is present and every
requested field is known. The CLI exits with status 1 for an incomplete
report. The `commands` array records each command and its full reply.

## Values

C-Gate 3.4.0.2001 formats `NetVoltage` from byte 9 of the unit's 12-byte
IDENTIFY4 reply as `raw * 0.15904 + 0.55` volts, truncated to one decimal
place. `BurdenActive` is bit 7 of IDENTIFY16. The Toolkit treats a voltage of
0 or less as unknown, and so does the CLI. These values are what the unit
reports. They are not an electrical measurement.

Native `DO <unit> Psync` depends on the unit's C-Gate class:

- `CBus2Unit.m` reads IDENTIFY16 and then IDENTIFY4.
- `CBus2InputUnit.m`, used by classes such as `CBusNeoInputUnit` (`KEYE1`),
  reads only IDENTIFY4 and leaves `BurdenActive` unchanged.

A unit that never answers returns `408 Operation failed: <unit> ()`. A unit
C-Gate has never seen returns `401 ... (Unit not found)`.

## Rust services

`cgate-mock` has no bus. A present unit keeps the native zero state
(`NetVoltage=0.5`, `BurdenActive=no`), `DO Psync` returns
`202 Done: <unit>`, and a PP read of a missing parameter returns native `460`.

`cmqttd` caches `NetVoltage` during `NET SYNC` and runs `DO Psync` over the
shared PCI. It skips IDENTIFY16 when the configured `cbusunits.xml` maps the
unit's type and firmware to a `CBus2InputUnit` class. Without that catalogue
evidence it uses the `CBus2Unit.m` order.

## Evidence

- An owned native C-Gate 3.4.0.2001 run against the synthetic PCI fixture is
  kept sanitized in
  [native-unit-diagnostics.json](../research/fixtures/native-unit-diagnostics.json).
  It covers two passes: all units present, and unit 17 detached.
- `tests/test_unit_diagnostics.py` replays that capture offline.
- `tests/test_rust_cgate_interop.py` runs the CLI against `cgate-mock`.
- `tests/test_cmqtt_interop.py` runs the CLI against `cmqttd` and the Python
  PCI simulator.
- `rust/testdata/vectors/cgate_unit_diagnostics.jsonl` pins the native reply
  envelopes.

## Limits

- `cmqttd` cannot `Psync` the local PCI unit. The simulator's local reply to
  IDENTIFY16 is not accepted, so the command returns `408`. The cause appears
  to be header decoding in the transport and is not yet confirmed.
- On `cmqttd`, a PCI rejection of IDENTIFY16 faults the programming lane and
  forces a PCI reconnect. This happens when there is no catalogue and a unit
  rejects that attribute.
- The `cmqttd` interop case omits the clock pass, which needs decoded unit
  specifications. `cgate-mock` covers the `460` path.
- Routed (bridged) `Psync` is not supported and returns `408`.
- The Toolkit's `N/A` voltage rule for firmware 1.00 units is not implemented.
- The text of the Toolkit error dialogs for IDs 0xEAB–0xEAD is unresolved.
- The Toolkit's PP session naming and "load all" flag are not confirmed.
- No physical electrical validation has been done.

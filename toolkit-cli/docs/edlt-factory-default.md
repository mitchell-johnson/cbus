# Physical eDLT FactoryDefault

`cbus-toolkit cgate edlt-factory-default` provides a guarded one-shot physical
FactoryDefault request for **KEYGL5 / 5055EDL / firmware 5.5.00**. It is
separate from the database-only [Reset Unit controls](edlt-reset.md) and the
retained [Global factory preparation](edlt-reset-factory.md).

```sh
cbus-toolkit cgate edlt-factory-default plan //PROJECT/254/p/5 \
  --serial 101183.1666 --plan-output factory-default-plan.json
cbus-toolkit cgate edlt-factory-default request //PROJECT/254/p/5 \
  --serial 101183.1666 --plan-output factory-default-intent.json
```

`plan` performs no reset. `request` creates and flushes a new exclusive plan
file before sending the control when `--plan-output` is supplied. It then
repeats every guard and sends exactly one command:

```text
DO //PROJECT/254/p/5 FactoryDefault
```

The workflow requires an already open and idle direct wired network, native
retry count zero, disabled automatic unravel/update, matching runtime/database
interface definitions, a complete fresh physical inventory, one healthy target,
the exact expected serial, and KEYGL5 firmware 5.5.00. Bridge and wireless
gateway topologies are rejected. A changed plan, identity, inventory, database
fingerprint, or runtime configuration stops before the destructive command.

## Native control and receipt

C-Gate 3.4.0.2001 exposes `FactoryDefault` on `CBusEdlt`. Its retained
implementation supplies the two bytes `B2 B2` to the OEM programming helper,
which yields the local programming request `A4 FF 43 B2 B2`. `cmqttd` sends the
checksummed unit-5 example as:

```text
\46050900A4FF43B2B262<confirmation>\r
```

The service requires a positive PCI confirmation and a source-correlated unit
ACK carrying `32 FF 43`. A definite PCI rejection or unit NAK returns a failure
while leaving the programming lane usable. Timeout, disconnect, cancellation,
or an incomplete reply faults the lane until reconnect so a late ACK cannot be
assigned to a later programming operation. The request is never automatically
retried.

An exact `202 Done: //PROJECT/254/p/5` result records
`factory_default_control_accepted=true`. It does **not** set any of the following
verification fields:

- `physical_factory_reset_verified`
- `factory_defaults_readback_verified`
- `address_preserved_verified`
- `device_reboot_verified`
- `persistence_verified`

Those require separate post-reset identity, full PP readback, rendered behavior,
and power-cycle acceptance. The command does not rewrite the database unit.
Because FactoryDefault may invalidate displayed labels, `cmqttd` clears its
bounded current-connection dynamic-label observation ring after an accepted
control.

When the optional `cmqttd` LOGIN gate is armed, FactoryDefault requires an
authenticated C-Gate connection. The dormant default remains unchanged.

## Evidence and limits

The exact request is pinned in `rust/testdata/vectors/decode_to_pci.jsonl` and
in transport tests that prove confirmation/ACK correlation, foreign-traffic
fanout, NAK handling, no replay, and subsequent programming-lane reuse. The
hardware-backed service test checks profile/address guards and cache
invalidation. The real-daemon fake-PCI test exercises the same command while
MQTT and C-Gate share one connection.

Python module and CLI tests cover fresh planning, durable intent ordering,
forged/stale plans, profile and path rejection, exact 202 acceptance, complete
native rejection, lost replies, interruption evidence, and no replay. No house
device was reset to produce this acceptance. Physical defaults, reboot,
address retention, rendering, persistence, and recovery remain outstanding.

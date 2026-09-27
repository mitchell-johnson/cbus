# Typed C-Gate network learning and locate requests

The CLI exposes the retained C-Gate 3.4 `NET LEARN` grammar and every
evidenced `NETWORK LOCATE` selector. These commands can send physical C-Bus
traffic. They have no dry-run form.

```sh
cbus-toolkit cgate network learn //PROJECT/254 56 init-relay 1
cbus-toolkit cgate network learn //PROJECT/254 56 cancel 1

cbus-toolkit cgate network locate //PROJECT/254/208 unit 1 ON
cbus-toolkit cgate network locate //PROJECT/254/208 app 56 2
cbus-toolkit cgate network locate //PROJECT/254/208 group 56 1 OFF
cbus-toolkit cgate network locate //PROJECT/254/208 serial 1 12345.67 255
```

The typed wrapper requires a fully qualified direct network for learning and a
fully qualified application 208 for locate requests. It does not accept a
routed address, an implicit project, or another carrier application. C-Gate
still decides whether that direct network is loaded, bound, open, and usable.

## Learn grades

The retained command class admits these six grades. Symbolic names avoid
confusing decimal and native hexadecimal spellings:

| CLI name | Value | Native command token |
| --- | ---: | --- |
| `init-relay` | 1 | `1` |
| `init-dim` | 2 | `2` |
| `cancel` | 128 | `$80` |
| `exit-relay` | 129 | `$81` |
| `exit-dim` | 130 | `$82` |
| `exit-area` | 131 | `$83` |

The CLI also accepts those exact numeric values in decimal, `0x` notation, or
C-Gate `$` notation. It canonicalizes values 128 through 131 to `$80` through
`$83` in the command sent to the server. The application and group are bytes.
No other learn grade is inferred.

## Locate selectors

| Selector | Typed operands | Retained limits |
| --- | --- | --- |
| `unit` | unit, mode | unit 0–255 |
| `app` | target application, mode | application 0–254 |
| `group` | target application, group, mode | application and group 0–254 |
| `serial` | manufacturer, native serial, mode | manufacturer 0–255; serial components 0–1,048,575 and 0–4,095 |

Modes are `OFF`, `ON`, or an explicit byte. The CLI sends `OFF` and `ON` for
values zero and one and decimal text for other bytes. Serial numbers use the
native decimal-dot form, such as `12345.67`; the CLI does not guess another
serial representation.

## Result and failure boundary

An exact terminal C-Gate 200 produces a
`cbus-cgate-network-management-v1` receipt. For example, a successful locate
receipt records:

```json
{
  "format": "cbus-cgate-network-management-v1",
  "operation": "network-locate",
  "network": "//PROJECT/254",
  "carrier_application": 208,
  "selector": "serial",
  "target": {"manufacturer": 1, "serial": "12345.67"},
  "mode": {"value": 255, "name": "byte"},
  "native_command": "NETWORK LOCATE //PROJECT/254/208 SERIAL 1 12345.67 255",
  "cgate_accepted": true,
  "interface_delivery_confirmed": true,
  "device_action_verified": false,
  "physical_state_readback": false,
  "persistence_verified": false,
  "automatic_replay": false
}
```

`interface_delivery_confirmed` reflects C-Gate's terminal-200 contract for
these commands. It does not prove that a unit received, acted on, displayed,
or persisted the request. The typed wrapper performs no physical readback.

The production `CgateClient` assigns the correlation tag and sends the command
once. A server rejection is an error. If the connection ends or times out
after submission, the outcome is reported as unknown, the connection is
invalidated, and the command is not replayed. On cmqttd's embedded C-Gate
service, the server additionally serializes the physical command, waits for
its matching PCI confirmation, checks the PCI generation, and rejects a
foreign, routed, or unbound network before physical I/O.

The wrapper does not claim a Toolkit GUI workflow comparison, discovery of a
safe target device, device-state verification, persistence, or MQTT state.
Use `cgate exec` only when the raw server grammar is intentionally required;
it does not add these typed range and address checks.

## Evidence and tests

The retained native class/help and loopback evidence is in
[`native_cgate_net_lifecycle.json`](../../rust/testdata/fixtures/native_cgate_net_lifecycle.json).
Exact SAL packets for every locate selector and the initial relay learn grade
are shared in
[`network_management.jsonl`](../../rust/testdata/vectors/network_management.jsonl).
The Rust codec and cmqttd daemon tests own packet encoding, correlated PCI
confirmation, generation guards, direct-binding refusal, exact-once delivery,
and no replay. This Python slice composes those server operations without
reimplementing their wire encoding.

[`test_networks.py`](../tests/test_networks.py) covers all learn grades, every
selector, canonical commands, receipts, limits, and refusal before command
submission. [`test_cli_network_management.py`](../tests/test_cli_network_management.py)
uses the production tagged TCP client to check literal commands, JSON output,
server rejection, lost replies, and no client replay. These are software and
retained-evidence checks; no Toolkit GUI or physical unit was run for this
Python checkpoint.

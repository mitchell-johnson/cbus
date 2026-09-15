# Direct PCI serial collection

`PCISerialCollector` sends one read-only IDENTIFY4 request for one unit address
and collects all matching replies during a bounded observation window. It can
report both explicit serials at a duplicate address. It has no addressing,
programming, interface-configuration or retry operation.

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --local-unit 16 --timeout 10 serials 255
# Add the global --checksum option when outgoing PCI SRCHK is already enabled.
```

The endpoint must be a numeric IPv4 or IPv6 address, without a scope suffix.
Hostnames are rejected before connecting because DNS and multiple resolved
addresses cannot satisfy this collector's connection deadline. The caller
must have exclusive access to the configured PCI transport and provide the
known local PCI address. That address checks routed reply destinations and
allows a bare local CAL reply only when querying the local PCI itself. The
collector does not discover or change interface settings, disconnect C-Gate,
or establish exclusive ownership on the caller's behalf.

```python
from cbus_toolkit.pci_serials import PCISerialCollector

observation = PCISerialCollector(
    "127.0.0.1", 10001, local_unit=16,
    quiet_period=2.0, overall_timeout=10.0, confirmation_timeout=2.0,
    max_frames=7, command_checksum=False,
).collect_serials(255)
print(observation.as_dict())
```

Each collector object is one-shot. It uses a fresh TCP connection and closes
it on every outcome. Reusing the object raises before connecting. Closing
failures preserve the observation and set `connection_closed=false` instead
of replacing partial evidence with a cleanup exception.

## Results and timing

The JSON format is `cbus-pci-serial-observation-v1`. `complete` means the
documented collection window completed successfully; it does not mean a unit
has a unique address. The CLI exits zero only for `single`.

| Status | Meaning |
| --- | --- |
| `single` | The completed window returned one distinct known serial. |
| `duplicate_address` | The completed window returned multiple distinct known serials. |
| `absent` | The completed window returned no matching known serial. |
| `incomplete` | A limit, ambiguous reply, unknown serial, framing error or transport failure prevented completion. |

Results retain every parsed matching reply, its raw bytes, source and
destination, the deduplicated known serial list, repeated-response count,
unrelated traffic, bounded received bytes, confirmation, timing, termination
and errors. Previously valid replies remain available if a later frame is
malformed or the connection fails. Unknown serials and conflicting data for
the same serial are incomplete outcomes, with their raw evidence retained.

The default quiet period is two seconds. After a matching PCI confirmation,
the collector waits a full quiet period and restarts that period after every
complete matching serial reply. Unrelated traffic and partial frames do not
restart it. An overall deadline includes connection establishment and sending;
a separate confirmation deadline starts after transmission. If an overall,
frame, byte or unrelated-traffic bound is reached, the result is incomplete.
Reaching the default seven-frame limit is deliberately incomplete because
additional identities could have been suppressed by saturation.

The exact native `cT` command uses IDENTIFY4, a 2000ms quiet interval and up to
seven responses. Original `aW` bytecode updates its last-response timestamp
after an accepted response and measures its quiet deadline from that timestamp,
or from sending if no response arrived. The Python collector adds a separate
confirmation phase and starts its initial quiet interval after confirmation;
it preserves the native quiet duration without claiming identical total
deadline behavior. Explicitly changing `quiet_period` is supported and recorded
as `timing.vendor_quiet_period=false` when it differs from two seconds. The
[source evidence](duplicate-discovery-source-evidence.json) and
[timing audit](selected-serial-addressing-research.md#proposed-separate-collector-and-transport-api)
identify the original classes and bytecode checks.

A matching reply must contain exactly one twelve-byte IDENTIFY4 CAL. Remote
replies must retain the queried source, explicit local PCI destination and
direct route. Bare replies are accepted only for the explicitly queried local
PCI. Foreign or duplicate confirmations, data before confirmation, unknown
serials, conflicting serial blocks, invalid checksums and truncated frames are
incomplete. The current decoder covers the existing PCI CAL grammar; unsupported
ambient frame formats also produce an incomplete result.

Collection completion is bounded evidence. A reply that arrives after the
finished window cannot change an earlier result, and a new TCP connection does
not establish that the physical bus contains no delayed replies. This API is
not a full network inventory, persistent identity binding, commissioning plan
or proof that an address remains empty. No address mutation is enabled.

## Independent validation

The literal duplicate exchange is:

```text
request:       \46FF002104g\r
SRCHK request: \46FF00210496g\r
reply:         g.86FF10008D0438FFFFFFFF18B10616A200051A\r\n
               86FF10008D0438FFFFFFFF18B10617A2000519\r\n
```

Serial `101136.1558` is from the captured KEYE1 block. Serial `101136.1559`
is an explicitly generated second fixture identity. Tests supply the literal
reply bytes independently of the request encoder and cover split packets,
delayed second replies, late fragments, absent/missing/rejected confirmations,
wrong source/destination/route, repeated and conflicting identities, unknown
serials, checksum failures, all collection bounds, disconnects and close errors.

The [native comparison report](native-pci-serial-acceptance.json) records the
direct collector finding both serials and original C-Gate `NET CHECKUNIT`
classifying the same fixture address as duplicate. The two clients use the
fixture sequentially. A unique disposable native project has AutoUnravel and
AutoUpdate disabled and Retries set to zero. Complete fixture state and database
XML remain unchanged, cleanup succeeds, and no unsupported request occurs.
The current fixture reapplies and reads Retries=0 after native readiness;
earlier snapshot evidence requested it before startup, which can reload the
default. The earlier successful read-only exchange remains valid for its
observed happy path.
This verifies the simulated digital exchange, not analogue collision timing or
physical hardware behavior.

```sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_pci tests.test_pci_serials.PCISerialCollectorTests tests.test_cli_pci_serials
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_PCI_SERIAL_REPORT=docs/native-pci-serial-acceptance.json PYTHONPATH=src .venv/bin/python -m unittest tests.test_pci_serials.NativePCISerialCollectorTests
```

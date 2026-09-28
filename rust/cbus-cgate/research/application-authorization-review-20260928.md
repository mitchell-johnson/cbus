# Native C-Gate application handler entry roles

This bounded P2.04 slice adds 24 exact application command paths to the native
authorization evidence. It does not close P2.04 or prove permission to deliver
a message to physical hardware.

The [capture script](native_application_authorization_probe.py) launched the
pinned C-Gate 3.4.0.2001 jar (SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`)
with Temurin 11 under `LocalCGate`. Its six listeners belonged to the owned
Java child on IPv4 loopback. Nine fresh sockets logged in at the nine ACCESS
levels using generated credentials. Every target named absent project
`MISSING`; no C-Bus endpoint, broker, site project or physical network was
configured. The harness confirmed child exit and removed the disposable work
directory. The [sanitized fixture](../../testdata/fixtures/native_cgate_application_authorization_probe.json)
retains all 216 role/invocation replies, source hashes and cleanup flags, not
credentials or raw logs.

| Entry role | New paths |
| --- | --- |
| Operate | Ten `AIRCON SET_*`, `CLOCK DATE` and `REQUEST_REFRESH`, `ENABLE LABEL` and `REMOVE`, `LIGHTING UNICODELABEL` and `TERMINATERAMP`, `SHORTMESSAGE SEND`, and all five `TELEPHONY` leaves |
| Program | `TRIGGER LABEL` and `UNICODELABEL` |

All lower roles returned `420 Access denied.`; the listed role returned a
non-420 later handler response. For each exact invocation the floor response
was `401` for the absent target. This is entry-order evidence, not later
object-specific authorization or bus-send permission. In particular, all five
Telephony leaves reach object lookup at Operate. The previous contract inventory
had characterized their Program delivery guard as a resolved native floor;
that overclaimed the evidence. The inventory now records an unresolved role
subaxis with the exact native Operate observation, and cmqttd matches the
missing-object outcome at Operate. Existing configured targets retain a
separate Program guard pending an original C-Gate comparison at a present,
disconnected target and a controlled physical endpoint.

The Rust registry enforces all 219 currently observed entry floors before
mutation or PCI I/O. Focused tests verify each of the new lower-role denials
leaves the durable repository, event stream and PCI unchanged, that admitted
responses reach later handler logic, and that the existing Telephony fanout
and failure tests still pass. The Toolkit contract inventory and parity
validator bind this fixture by SHA-256; all 219 known facts remain unresolved
functional scope. The full local suite was deliberately not run for this
slice. After integration, changing `access.rs` or `service.rs` invalidates
source-bound C-Gate session differential receipts; regenerate them before
the parity register and installed-package checks.

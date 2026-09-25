# C-Gate and Toolkit compatibility reference

## Physical service in cmqttd

Use cmqttd's embedded listener for supported real-network operations. It shares
the CNI with MQTT; do not open a competing direct PCI connection or fall back to
Windows for live eDLT static-label reads. Read `docs/cmqttd-cgate.md` for the
current supported operations and remaining C-Gate replacement work. Query
`CMQTT CAPABILITIES` before assuming an operation is implemented. Physical reads:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 edlt-labels --network //PROJECT/254
cbus-toolkit cgate --host 127.0.0.1 --timeout 30 edlt-labels //PROJECT/254/p/UNIT
```

Use the configured endpoint and project address. The network form runs one
whole-network serial refresh (`NET SYNC` plus `NET CHECKUNIT`), reports every
fresh record and reads exact KEYGL5 5.5.00 devices in numeric address order.
Unsupported firmware, unknown or ambiguous identities and per-device failures
remain in the JSON beside successful reads. The physical configurations are
sequential rather than an atomic network snapshot. Physical IDENTIFY4 reads
bracket each selected memory snapshot. The fresh inventory identity is attached
only when both physical serials match it; a mismatch remains a per-unit error
without stale identity attachment. An incomplete report is still emitted and
the command exits nonzero.
Treat a wildcard MMI candidate with a `No units detected` CHECKUNIT result as
an unresolved identity, not proof of physical absence. The network inventory
must remain incomplete while preserving successful eDLT snapshots.

Each successful device read returns physical identity, all 64 static strings
and their widget, page and scene references, a stable-header check and CRC
evidence. The network form then requests `CMQTT LABELS` exactly once at network
scope. Its bounded current-connection SAL observations remain top-level,
network-wide, transient and recipient-unverified; they are never assigned to a
device. A unit-shaped `CMQTT LABELS` request is only a compatibility alias for
the same network ring. The nested observation document's `complete: false` and
`device_readback: false` distinguish it from an inventory of a display's
pre-existing cache. `CMQTT LABELS`, `UNIT READMEM` and `UNIT IDENTIFY` are
cmqttd extensions.
A 502 response is a missing backend or failed device operation; never replace
it with saved project data and describe that as a live result.

The physical service also implements lighting commands, C-Gate `DO` object
methods for lighting and direct-network `SYNC`, Trigger Control,
Enable Control, clock date/time/refresh, Temperature Broadcast, `NET PINGU`, `NET SYNC`,
`NET CHECKUNIT`, physical `NET CLOCKS`, physical `PP LOAD`, and readback-verified physical `PP SAVE` for
`direct`, `edlt`, `paged`, `ncc`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and
`goc2` parameters using decoded unit specifications. Direct and page-aware
`lock` parameters use the captured unlock phase. A specification containing
`ProgramMethod=ncc` identifies the vendor C-Bus 3 families; after at least one
changed store, SAVE performs native group-0 operation-4 EXECUTE followed by
500 ms POLLs for up to 15 seconds and succeeds only on status zero. An unchanged
or tag-filtered save does not issue the NVM command.
`LIGHTING`, `TRIGGER`, and `ENABLE` label commands also use the physical bus.
They support the Toolkit CLI's raw/text, icon, language, segmented Unicode, and
dynamic bitmap forms. Enable Unicode is a native-invalid form. A 200 response
proves confirmed fragment delivery, not display rendering or persistence.
`SCENE RECORD set name` atomically persists currently observed lighting levels
from the configured network. `SCENE PLAY set name` sends confirmed zero-time
ramps and requests status readback; its success does not by itself prove the
loads reached those levels. These named server snapshots are separate from
device PP scene tables.
`LABEL CLEAREDLT //PROJECT/NETWORK/p/UNIT` is hardware-backed for KEYGL5. It
sends one native clear control and requires a correlated unit ACK. Report it as
accepted, never as verified erasure or persistence; there is no dynamic-label
cache readback operation.

Standard native cache clear is a separate operation:

```text
LABEL CLEAR //PROJECT/NETWORK/APPLICATION UNIT
LABEL CLEAR //PROJECT/NETWORK/APPLICATION UNIT KEY
```

Use `cbus-toolkit cgate label cache-clear APPLICATION UNIT [--key KEY]` for
the typed form. Applications are 48–95, 202 or 203, units are 0–255 and keys
are 1–8. The all-key form emits `A3 FF 00 27`; the keyed form emits
`A4 FF 00 66 KEY`. cmqttd sends one point-to-point frame with no replay and
waits only for its matching PCI confirmation. Native C-Gate considers both
`.` and `#` confirmation outcomes complete. There is no unit ACK or readback,
and the native handler publishes no label-specific success event. Optional
high-verbosity audit events remain generic command/response logging. Report
`native_accepted` and `pci_confirmation_received`, while keeping delivery
outcome, erasure and persistence unverified. This is also distinct from
`cgate label clear`, which sends an empty group-label SAL.

The native KFI commands are also hardware-backed on the configured direct
network:

```text
LABEL KFIGET //PROJECT/NETWORK/APPLICATION UNIT
LABEL KFISET //PROJECT/NETWORK/APPLICATION UNIT KFI1 KFI2 KFI3 KFI4 KFI5 KFI6 KFI7 KFI8
```

The application must be one of the label-capable native IDs 48–95, 202 or 203;
the unit is 0–255 and KFISET requires exactly eight values from 0 through 15.
The application token is a native `LabelSupportingApplication` scope/class
gate; it is not encoded into KFIGET's fixed selector `0x1c`.
KFIGET returns eight ordered `300` KFI rows from exactly one source-correlated
native reply; zero or multiple replies return 524. KFISET sends four packed
parameter-`0xFF` writes and stops at the first failed confirmation or unit ACK.
Despite the GET name, KFIGET first sends three volatile parameter-`0xFF` selector
writes. It is a programming operation behind the optional LOGIN gate and should
not be run casually on live hardware. It does not read a dynamic-label cache,
does not require a modeled KEYGL5 unit type, and has scripted rather than live
hardware acceptance.

Every KFI parameter-`0xFF` write and the GET IDENTIFY request is a
generation-safe exact-once send and never enters automatic retry. A lost
confirmation faults the programming lane until reconnect, preventing a late
confirmation or identical untagged ACK from advancing a later selector and
preventing GET replay from manufacturing response multiplicity.

`DO //PROJECT/NETWORK/p/UNIT FactoryDefault` is also hardware-backed for
KEYGL5. Use `cbus-toolkit cgate edlt-factory-default plan|request` with the
expected native serial. cmqttd sends captured control `A4 FF 43 B2 B2` exactly
once and requires PCI confirmation plus the source-correlated unit ACK. A 202
proves acceptance only; reset values, reboot, retained address, rendering and
persistence require separate verification. When the optional LOGIN gate is
armed, this destructive method requires authentication.
It also implements guarded scalar `SET //PROJECT/NETWORK/p/UNIT Address DEST`
against the physical bus. That command proves one source and an empty
destination, uses the native parameter-`0x20` one-use challenge, sends the
special address STORE once, requires the destination ACK, and deliberately
leaves the database unit address unchanged for the Toolkit workflow to verify.
The bounded `NET UNRAVELUNIT //PROJECT/NETWORK 255 MATCHDB` path resolves
exactly two known serials colliding at 255 to two unique, independently empty
database destinations on a direct network. It requires local PCI parameter
66=`05`, sends each selected-serial broadcast once, verifies each destination,
and repeats the complete MMI and serial inventory before returning 200. Query
`CMQTT CAPABILITIES`; `net_unravelunit_matchdb_duplicate_255: true` denotes
this exact scope. Whole-network UNRAVEL, other source/subset forms, occupied
destinations, cycles, larger duplicate sets, and bridged networks remain 502.
PINGU and whole-network checks send the install-MMI request
with the active PCI checksum setting. They buffer blocks that arrive before the
request confirmation but accept only positively confirmed, contiguous coverage
of addresses 0–255. SYNC uses the configured interface-unit
address as a routing hint, or BASIC discovery when that hint is unavailable;
fresh MMI and IDENTIFY replies physically validate the result. It probes
IDENTIFY1/2 and collects all IDENTIFY4 replies for every present address, then
atomically replaces the live identity cache. Silent legacy/error addresses stay
present with unknown identity fields. Native eDLT metadata requires MMI state
one, exactly one known IDENTIFY4 serial, and both the configured database type
and fresh IDENTIFY1 to be KEYGL5. Eligible units follow retained CBusEdlt
classfile order:
parameter `0xFB` length 9 becomes the NUL-terminated volatile
`FirmwareVersion`; an OEM address-16 selector plus parameter-1 length-2 recall
becomes decimal `Application` and `Application2`; parameter `0xFA` length 44
becomes opaque decimal-CSV `WidgetGroups`. `Version` remains the separate
IDENTIFY2 value and the persistent database `FirmwareVersion` is unchanged.
Read the properties with `GET //PROJECT/NETWORK/p/UNIT PROPERTY`; these cached
`300` getters issue no bus I/O. Every request is exact-once and responses must
match source, selector tag or parameter, and total length. A failed optional
read leaves earlier values from the same sequence fresh, invalidates the failed
and all later unrefreshed values, and does not fail an otherwise valid identity
SYNC. The programming lane remains faulted until reconnect and no request is
replayed. `WidgetGroups` is static mapping, not dynamic-label cache readback.
State two, state three, zero-serial, and multi-serial addresses receive no
source-address-only metadata traffic and expose no stale metadata. Reconnect or
transport loss invalidates an in-flight snapshot before commit and returns 408
without a sync-ok event.
CHECKUNIT actively collects IDENTIFY4
replies through the native two-second quiet interval; it does not infer duplicate count from the
two-bit MMI state. Use `GET //PROJECT/NETWORK Units` and unit `Type`, `Version`,
`SerialNumber`, `Address`, and `State` getters for the resulting live snapshot.
For Rust commissioning work that must preserve duplicates rather than populate
the service cache, use `cbus_transport::inventory::collect_full_inventory`. It
requires complete contiguous MMI coverage, retains raw IDENTIFY4 replies with
multiplicity, bounds each address and the full collection, and marks silent or
malformed identities partial. Its observations are sequential and are not an
atomic network snapshot.
`NET SYNCNEW //PROJECT/NETWORK [unit]` is hardware-backed for direct networks.
It merges five complete MMI passes. The optional targeted form rejects an
already-modeled address before bus I/O, runs native duplicate challenges
`0x80`, `0x81`, and `0x82`, then reads IDENTIFY1/2/4. The general form reports
new identities and MMI state-3 duplicate addresses. Results update the volatile
physical cache only and retain native progress/result codes (`120`, `303`,
`408`); they do not create persistent database units.
`NET SET_PROJECT_IDENTIFY //PROJECT/NETWORK NAME` is also hardware-backed.
It packs the uppercased 1–8 character native six-bit identity, selects the
first MMI-state-one unit with valid IDENTIFY1 data and exactly one valid known
IDENTIFY4 serial reply over the complete quiet window, stores parameter 35,
and requires exact RECALL readback. A failed or uncertain write invalidates an
older cached `ProjectName`. The typed CLI mK-quotes spaces, quotes and
backslashes; the cached `ProjectName` is decoded from verified bytes so the
native `?`/space alias stays canonical. It updates only the volatile physical
snapshot and does not rename or persist a project. This is distinct from the
unsupported topology-discovery command `NET PROJECT_IDENTIFY`.
Query `CMQTT CAPABILITIES`; `unit_readdress: true` denotes the readdress path and
`physical_pp_save_cbus3_nvm: true` denotes the NVM commit path,
`dynamic_labels: true` denotes the label sender,
`dynamic_label_observation: true` denotes the volatile network-wide observed
SAL ring (including unit-shaped compatibility aliases with no verified
recipient), while
`dynamic_label_device_readback: false` preserves the unsupported device-query boundary,
`edlt_label_clear: true` denotes the one-shot KEYGL5 clear control,
`label_clear: true` denotes the standard physical all-key/one-key cache-clear
command above,
`label_kfi: true` denotes the native physical KFIGET/KFISET sequences above,
`edlt_extended_firmware: true` denotes parameter-`0xFB` physical firmware
readback during KEYGL5 NET SYNC,
`edlt_applications: true` denotes the native OEM address-16
Application/Application2 readback,
`edlt_widget_groups: true` denotes the bounded KEYGL5 static mapping populated
by NET SYNC,
`cgate_auth: true` denotes the armed opt-in LOGIN gate (`false` dormant
default): with `--cgate-auth-file` configured, each connection needs
`LOGIN <token>` before programming verbs while reads and bus control stay
open; failures answer `420 LOGIN required` / `420 LOGIN failed` (malformed
`LOGIN` with no token is 400 and also clears the flag), never `401`.
Not native `access.txt` parity; loopback-only first slice;
`named_scenes: true` denotes hardware-backed named-scene playback,
and `do_methods: ["factorydefault", "lighting", "sync"]` denotes the physical object-method aliases,
`network_clocks: true` denotes IDENTIFY16 inspection plus schema-backed target
count and gateway recovery,
`network_syncnew: true` denotes the direct-network five-pass discovery backend,
`network_set_project_identify: true` denotes the verified parameter-35 write,
`pp_reset_to_defaults: true` denotes specification-backed staged
`PP RESET_TO_DEFAULTS` behavior,
while `full_cgate_compatibility` remains false until every remaining backend and
acceptance requirement is complete.

Command connections also provide native-shaped `SESSION_ID`, `SESSION_ID ALL`
and one-shot `SESSION_ID TAG` state, including live TCP/TLS peer and connection
time fields. `EVENT` and its `EVENTS` alias default to `e0s0c0` on a new cmqttd
connection. `QUIT` and `EXIT` flush `204 Closing connection.` before closing the
stream. These operations are volatile and perform no PCI or persistent database
I/O.

`PP RESET_TO_DEFAULTS SESSION` replaces the loaded session values with exactly
the `DefaultValue` fields from its decoded unit specification. The change is
staged: it performs no PCI or database write until a later `PP SAVE` or
`PP SAVE_TO_SOURCE`. A missing or malformed exact specification returns 408
without changing the session.

Run `NET SYNC` before `NET CLOCKS`; clock operations use the synchronized
physical inventory. Query mode reports native `120-address=...` rows. A target
of 1..10 and recovery `R` change `ClockGenEnable` only when the live unit has a
decoded direct schema, preserving neighbouring bits and requiring physical
readback. Inspect the response lines because native behavior can report a
per-unit failure before final status 200.

`DO //PROJECT/NETWORK/APPLICATION/GROUP ON|OFF|RAMP|TERMINATERAMP` uses the
same confirmed SAL path as the corresponding lighting command. `DO
//PROJECT/NETWORK SYNC` runs the same physical identity-populating direct-network
synchronization as `NET SYNC` and returns native `202 Done: object` framing.
`DO ... UNRAVEL` returns 502; never describe the mock's in-memory result as
physical success or treat the bounded NET workflow as general unravel support.

## Mock service

The user-facing CLI is Python `cbus-toolkit cgate`; see [toolkit.md](toolkit.md) for installation, typed workflows, and JSON output. This reference describes its Rust test server. Connect the CLI with `--host 127.0.0.1 --port 20033` for the default mock listener; native plain TCP defaults to 20023.

## What is supported

The maintained registry combines 224 public headings from C-Gate manual section 4.5 with 268 registered bytecode command paths, producing 431 unique paths after overlap removal. Tests assert inventory sizes, uniqueness, help visibility, parser reachability, and dispatch reachability. Unknown commands return an error.

Core project, database, network, unit, group-level, label, lock, session, event, repository, and PP programming flows use shared in-memory state. Specialist application and hardware-facing commands have deterministic handlers so a client can exercise every registered path without Schneider services or physical equipment.

The Rust mock supports CLI clients and C-Gate command traffic. It does not provide persistent project storage, physical C-Bus access, firmware transfer, real port discovery, or exact device timing and side effects. The Python Toolkit CLI has its own native-server and physical-device workflows with separate limits and acceptance evidence. Full Toolkit parity remains unfinished.

## Start and connect

```sh
rust/target/release/cgate-mock --bind 127.0.0.1:0
```

Read the printed address, then connect with a line-oriented TCP client. For a fixed development port:

```sh
nc 127.0.0.1 20033
```

Commands may be untagged or tagged. A tag is written before the command:

```text
APIVER
[1] PROJECT LIST
[2] EVENT ON
```

Tagged replies retain the client tag. Multiline replies use a hyphen after the status/tag prefix for continuation lines and a space for the final line. Events may appear before a command's final response and can arrive asynchronously on subscribed clients, so clients must parse reply framing rather than assume one input line produces one output line.

## Addresses and stateful examples

C-Gate addresses use forms such as `//PROJECT/NETWORK/APPLICATION/GROUP`. The tests use examples like:

```text
[1] PROJECT LIST
[2] PROJECT USE TEST
[3] LIGHTING ON //TEST/254/56/1
[4] LIGHTING RAMP //TEST/254/56/1 128 20
[5] LIGHTING OFF //TEST/254/56/1
```

These commands require suitable model state; a fresh mock may return a not-found response for an address that has not been created. Use `HELP` and the repository command inventory for discovery, and construct a project/network/application/group before testing level changes.

Programming sessions are lock-gated:

```text
[10] PP LOCK L //TEST/254
[11] PP START S L
[12] PP NEW S KEY1 1.2.67
[13] PP SET S Example value
[14] PP GET S *
[15] PP END S
[16] PP UNLOCK L
```

Run with `--deny-programming` when testing access denial. Supply `--unitspec DIR` when catalogue-backed parameter schemas are required. Without vendor specifications, the model still supports the spec-free programming behavior allowed by the command.

## Sessions and events

The server model is shared across TCP connections. Each connection keeps its own selected project and event mode. `EVENT ON`, `EVENT OFF`, or a detailed `e[+0-9]s[01]c[01]` mode controls delivery. Subscribed clients receive cross-client events; the originating client receives eligible command events in order before its reply.

## Resource bounds

- Input line: 1 MiB maximum.
- Here-document body: 16 MiB maximum.
- Library event queue: 4,096 entries by default, with an overflow marker.
- TCP fanout: unbounded channels; a subscribed client that never reads can consume growing memory while writers continue.
- Unit-spec file: 8 MiB maximum; include traversal is capped at 128 files and checked for directory containment.

Use loopback and an ephemeral port in automated work. Stop the child process after the check. Do not expose the mock listener beyond the intended test environment.

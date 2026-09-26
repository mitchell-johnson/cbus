# System reference

## Data flow

`cbus-toolkit` is the Python project and commissioning application. Offline workflows edit XML/CBZ or plan device settings; online workflows use its C-Gate client and typed wrappers, or its direct PCI client. Native C-Gate supplies online server behavior. Rust `cgate-mock` can stand in for that server during tests. The Toolkit CLI is maintained independently of the Rust bridge.

`cmqttd` connects one C-Bus PCI/CNI endpoint to one MQTT broker and can also serve C-Gate clients through `--cgate-bind`. Both interfaces share one transport. Incoming C-Bus frames become typed protocol values, state publications, and Home Assistant discovery messages. Valid MQTT commands and supported C-Gate lighting, named-scene playback, Trigger, Enable, clock, dynamic-label, standard label-cache clear, eDLT label-clear, direct and routed install-MMI discovery, verified project-identity parameter-35 writes and physical PP LOAD/SAVE commands become C-Bus traffic. `DBNETWORKPATH` resolves imported Bridge topology; `NET PROJECT_IDENTIFY` performs C-Gate 3.4's interface-rooted MMI and parameter-35 read on the already shared interface; `NET PINGU`, `NET SYNC`, general `NET SYNCNEW`, `DO ... SYNC`, and `NET CHECKUNIT` support read-only source routes through one to six bridges. Native Reply Network correlation prevents direct or neighbouring-network replies from populating the target cache, while MQTT continues through the same reader. Routed writes and routed targeted `SYNCNEW` remain unavailable; bridged general SYNCNEW updates only the reconnect-invalidated volatile target-network cache. `DO` lighting and `SYNC` are aliases over the same physical backends and retain native `202 Done` replies; `DO ... UNRAVEL` is explicitly unavailable until a physical unravel backend exists. Direct NET SYNC additionally reads native KEYGL5 metadata only for non-error present MMI states one or two with exactly one raw IDENTIFY4 reply carrying a known serial and both configured and freshly identified types equal to KEYGL5. State three and addresses with zero or multiple raw replies—including repeated identical known replies and mixed known/unknown replies—receive no metadata reads and expose no stale values. Retained classfile order uses the captured OEM `09 00` route for parameter `0xFB` length 9 (`FirmwareVersion`), address 16 length 2 (`Application` and `Application2`), and parameter `0xFA` length 44 (`WidgetGroups`); cached `Version` remains IDENTIFY2. Optional failures keep earlier fresh values, invalidate the failed and later values, leave overall identity SYNC successful, and fault the exact-once programming lane until reconnect. Routed NET SYNC omits these source-address-only OEM reads because a Reply Network form has not been proven. Reconnect or transport loss invalidates an in-flight snapshot before commit and clears volatile caches on every imported network. Named scene recording persists physically observed lighting levels; playback uses confirmed zero-time ramps followed by status requests. Dynamic labels cover raw/text, icon, language, segmented UTF-8, and dynamic bitmap forms on lighting, Trigger, and Enable applications. Standard `LABEL CLEAR` sends exactly one native all-key or keyed point-to-point cache command and has PCI confirmation only; the KEYGL5 `CLEAREDLT` control separately requires PCI and source/tag-correlated unit acknowledgement. Neither those commands nor WidgetGroups provide physical dynamic-label cache readback. A Toolkit `.cbz` or bare XML project supplies human-readable network, application, group, and unit metadata; the embedded C-Gate service imports it into a persistent database. Physical programming also requires private decoded unit specifications supplied with `--cgate-unitspec`; SAVE supports captured `direct`, `edlt`, `paged`, `ncc`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and `goc2` methods with `none`/`checksum` protection and native unlock handling for supported `lock` fields. Specifications containing the vendor `ncc` method receive the C-Bus 3 Save-to-NVM EXECUTE/POLL sequence after changed ranges have been read back. The same programming lane provides protected physical unit readdressing with source/destination identity guards, a one-use unit challenge, exact-once STORE, and a destination-address acknowledgement. MQTT continues to receive bus events through the shared packet fanout during these transactions.

General inventory commands remain local: comments, OID, BROADCAST_EVENT,
SHOW, REPORT, TREE, and both TREE XML forms perform no PCI operation. SHOW
provides ordered discovery and value reads for `cgate`, project, C-Bus,
network, application, group, unit, and output-terminal objects, including
database-only units. Exact matrices cover the retained application classes,
caller-cased named reads, aliases, foreign projects, errors, and parser grammar.
TREE combines the latest explicitly observed physical cache with durable
database objects and renders the captured multi-application hierarchy; its
sync flags never initiate discovery. NEW creates only durable
UNIT/GROUP/PHANTOM records under the captured address, application-child, and
firmware-token bounds and cannot create physical presence. Runtime host/IP/JVM
metrics and scheduled timestamps are shape-validated and normalized only when
declared volatile by the native fixture. `CMQTT CAPABILITIES` publishes these
boundaries so clients do not mistake database inventory for fresh bus evidence.

The command endpoint also maintains a durable runtime NET catalogue, separate
from the imported tag database and live PCI ownership. CREATE, DELETE, FLUSH,
LOAD, RENAME and SAVE are local atomic-repository operations; DB and FILE
snapshots stay inside `cmqttd-json`. Direct NET LEARN and NETWORK LOCATE enter
the same serialized PCI command lane as other application writes, transmit
exactly once, wait for correlated confirmation and apply the generation guard.
They publish no MQTT state, so broker lighting paths keep using the same reader
and writer unchanged. OPEN, CLOSE, whole-network UNRAVEL, and TOPOLOGY EXPLORE
remain fail closed because they would conflict with the shared interface or
exceed the evidenced destructive algorithm.

`cbus-tools` calls the same protocol and project readers for one-shot work. `cbus-simulator` supplies a development PCI/CNI endpoint. `cbus-cgate` is an independent in-memory C-Gate protocol model exposed over TCP by `cgate-mock`.

The embedded C-Gate service uses the shared PCI generation and client pointer
as the ownership token for guarded volatile results. Those physical paths hold
one generation commit guard across their cache mutation, cache invalidation, or
success event. When reconnect wins after old physical confirmation but before
commit, the command returns 408; it cannot mutate the replacement generation's
physical, level, application, or observed-label caches or publish that success
event. See the C-Gate reference for the covered command families.

PP catalogue/XML queries, lock/session inventory, raw-memory edits and
diagnostics, LOAD_FROM_FILE, and PROGRAMMER queue metadata stay on the local
side of this boundary. Catalogue access is confined to `--cgate-unitspec`; raw
bytes belong to one owned staged session; PROGRAMMER queues are volatile and
discarded at restart. None of these operations sends PCI traffic or interrupts
MQTT. The two execution edges remain explicit: `PP WRITE_PATCH` and
`PROGRAMMER TRIGGER ... START` return 502 without changing state because cmqttd
has neither the proprietary patch executor nor an evidenced queued-instruction
scheduler.

The CONFIG family is a local compatibility subsystem inside the embedded
endpoint. Its 148-entry native 3.4 catalogue, scoped global/project/network
overrides, and bounded LOAD/SAVE snapshots live in the same atomic JSON
repository as other durable C-Gate state. CONFIG never opens caller-named
files, sends PCI traffic, or applies its values to the running cmqttd listener,
MQTT client, transport, or loggers. The optional LOGIN gate protects SET,
LOAD, SAVE, OBSET and OBRESET; catalogue help and reads stay open. The one
intentional protocol repair converts native's no-reply OBGET wrong-scope path
to 408 so a client cannot hang.

The complete maintained FILE family is another local compatibility subsystem.
Its directories, binary contents, modification times and `.0` replacement
backups live in the atomic `cmqttd-json` repository. The service exposes native
DIR/LS, recursive MKDIR, DELETE, multi-file SHA256, base64 DOWNLOAD and
here-document UPLOAD envelopes. Its relative-path guard and virtual
`%PROJECT%` namespace prevent access to arbitrary host or vendor project files.
FILE commands send no PCI traffic. The optional LOGIN gate protects UPLOAD,
DELETE and MKDIR; help and reads stay open.

The maintained PORT family is a separate host/network subsystem. LIST and
IFLIST enumerate local serial ports and non-loopback interfaces. CNISCAN uses
the retained legacy UDP-30718 query; CNISCAN2 follows it with the structured
CNI2 CCP UDP-20050 query. PROBE rejects the endpoint already owned by cmqttd,
then uses a separate temporary connection for the retained DC1/`@2104`
echo-and-serial exchange and guaranteed shutdown. EtherLite addresses run that
exchange over a configured FAS serial channel. These operations do not
replace the shared `PciClient` or pause MQTT. With LOGIN enabled, scans, probe,
and refresh are gated; local help and enumeration remain open.

The complete maintained ACCESS family is durable local security state in the
same atomic repository. User credentials are stored as one-way digests and
LIST substitutes `<redacted>` for the native plaintext field. SAVE/LOAD names
select internal snapshots and never host paths. Address resolution completes
before a row is inserted, and loopback recovery remains available after an
empty or unmatched policy. Fresh/pre-ACCESS repositories admit Docker/NAT
clients at Clipsal until interface/remote policy is explicitly changed. An
unmatched peer then gets 421, or a LOGIN/LOGOUT-only recovery session when the
high-entropy recovery token is configured. ACCESS commands send no PCI traffic.
The token also adds a mutation gate: ADD, DELETE, LOAD and SAVE need that token
or a Clipsal/Max ACCESS-user login, while LIST is available to an admitted
Clipsal/Max session.

The embedded C-Gate endpoint implements the eleven C-Gate 3.4 AIRCON commands
for application 172 on the configured direct network. Commands use the shared
PCI confirmation lane; incoming schedule, plant and zone report SALs stay on
the shared event fanout and do not complete a pending command. The endpoint
does not publish an invented MQTT HVAC state model. A successful command proves
PCI-confirmed broadcast delivery only; controller acceptance, resulting state,
physical persistence and bridged routing remain outside the retained evidence.

The endpoint also implements all 19 maintained C-Gate 3.4 AUDIO commands for
application 205 on the configured direct network. Strict grammar and exact SAL
come from an isolated native 3.4 oracle. Commands use the shared PCI
confirmation lane and the active-generation success guard; routed writes fail
closed. Incoming command SAL remains typed on the event fanout. The A0
label/load-icon decoder is an explicit repair for an evidenced native defect
that suppresses its advertised events, so it is not native fanout parity.
cmqttd defines no MQTT Audio state. A successful command proves
PCI-confirmed broadcast delivery only; audio-controller acceptance, resulting
state and physical persistence remain outside the retained evidence.

The same endpoint implements all seven maintained C-Gate 3.4 SECURITY
commands for application 208 on the configured direct network. They use the
shared PCI confirmation lane and reject malformed modes, escapes, message
lengths and zones before I/O. A post-confirmation generation check prevents a
retired CNI connection from returning success after replacement. Incoming
Security commands, events, fixed zone names and both packed zone-status reports
remain typed on the C-Gate event fanout. cmqttd publishes no MQTT Security
entity/state schema. A successful command proves PCI-confirmed broadcast
delivery only; alarm-panel acceptance, resulting state, persistence and
bridged routing remain outside the retained evidence.

The endpoint also implements all 21 maintained C-Gate 3.4 MEDIATRANSPORT
commands/reports for application 192 on the configured direct network. Exact
basic and extended name SALs are sent once through the PCI confirmation lane; malformed ranges,
reserved operations, oversized names and unsupported routes fail before I/O.
Incoming messages remain raw-byte-safe typed events and fan out to C-Gate
clients. cmqttd publishes no MQTT Media Transport state. A 200 proves
PCI-confirmed broadcast delivery from the active generation; media-device
acceptance, resulting state, persistence and bridged routing remain outside the
retained evidence.

The same shared PCI implements the maintained Identify application-251 OFF,
ON, RAMP and TERMINATERAMP leaves, Short Message application-173 REFRESH and
SEND, and Error Reporting application-206 MESSAGE on the configured direct
network. Commands validate selectors and native ranges before I/O, send once,
require correlated active-generation confirmation, and are never replayed
after an uncertain transport result. Incoming messages remain typed with their
source unit on C-Gate event fanout, and none creates an MQTT state model.
Short Message SEND is an explicit compatibility repair: native 3.4.0.2001
generates malformed text/length/flag fields and can still return success, while
cmqttd emits real UTF-8 and the coherent layout accepted by the native inbound
decoder. Unsupported applications and routed selectors fail closed.

Physical `NET CLOCKS` uses the synchronized unit inventory, IDENTIFY16 status,
and decoded direct `ClockGenEnable` fields for target counts and gateway
recovery. It retains native per-unit failure lines and requires write readback.

The embedded service also owns one atomic JSON state repository. Read it with
`REPOSITORY LIST` as the explicit `cmqttd-json` type. Secondary projects can be
renamed, archived to an explicit `cmqttd:KEY` internal key and restored from
that key. Secondary projects can also be copied with their durable database
OIDs or deleted; copies exclude runtime physical/level/network state, and the
configured hardware project cannot be renamed or deleted during service
operation. Archive keys never name host files. The bounded snapshot contains
project/network/unit records and unit fields, excluding opaque auxiliary maps
and all runtime bus state. TCP and TLS command sessions bound and drain native
here-document framing. Bounded CGL 1.1 import/export persists only modeled
network/application/group/level labels over known routes; it never programs a
controller or preserves unknown vendor metadata. DBSETXML remains 502 because
its typed-object semantics are unavailable. Schneider archive formats,
`PROJECT REPAIR`, `REPOSITORY USE`, and the five proprietary repository
transformations remain unavailable. These operations perform no PCI I/O, and
a real-daemon system regression verifies that MQTT commands continue through
the shared PCI after the administrative workflow.

## Source ownership

Toolkit modules live under `toolkit-cli/src/cbus_toolkit/`; its tests are under `toolkit-cli/tests/`. Its feature docs, compatibility ledger, and retained acceptance evidence describe supported workflows and profiles. The Rust workspace is organized as follows.

| Crate | Responsibility |
| --- | --- |
| `cbus-protocol` | Typed C-Bus packets, CAL, SAL (including Air-Conditioning, Audio, Security, Network Management and learn mode), reports, checksums, encoding, decoding, and stable JSON |
| `cbus-transport` | TCP/serial framing, PCI initialization, confirmations, retries, reconnection, and flow control |
| `cbus-mqtt` | MQTT topics and payloads, Home Assistant discovery, and CBZ/XML project metadata |
| `cmqttd` | Runtime orchestration between transport and MQTT |
| `cbus-tools` | Frame decoding, label export, and TCP unit interrogation |
| `cbus-simulator` | Fake PCI/CNI TCP endpoint |
| `cbus-cgate` | C-Gate parser, state model, persistent hardware service, and separate `cgate-mock` server |
| `cbus-vector-check` | Standalone JSONL compatibility-vector runner |
| `cbus-golden-tests` | Generated exact-vector and finite-domain tests |
| `cbus-test-support` | In-process MQTT broker, scripted PCI, process, and wait helpers |

Put new behavior in its owning crate. Avoid embedding byte-level rules in a binary or network behavior in the protocol crate.

## Protocol behavior

The protocol crate covers point-to-multipoint, point-to-point, device-management, install-MMI status, reset, confirmation, error, and special packets. CAL support includes identify, recall, reply, NAK, standard label-cache clear, and extended execute, poll, status reply, and legacy extended messages. SAL support includes lighting, Air-Conditioning commands and reports, all maintained Audio commands plus label/load-icon events, Security, Measurement, Media Transport, Telephony, Identify, Short Message, Error Reporting, Trigger Control, clock, Enable Control, temperature, dynamic labels, status requests and install-MMI requests. Strict decoding rejects malformed input; lenient decoding retains compatibility behavior for imperfect frames. Install-MMI response decoding is enabled only during its active transaction because its wire header is ambiguous with priority-three addressed traffic.

The transport reassembles bounded byte streams, initializes the PCI, assigns confirmation codes, retries unconfirmed frames, and gives interactive commands priority over background status sweeps. It supports TCP CNI and serial PCI connections.

For selected-serial commissioning, `cbus-transport::inventory` preserves every
IDENTIFY4 reply and the opening MMI vector. `cbus-transport::verify` validates a
version-one plan from its original bytes, performs a read-only serial-only
identity observation between complete MMI bookends, and classifies the full
identity/state snapshot. `cbus-transport::apply` requires a complete fresh
inventory equal to the plan's embedded `before`, immediately recalls live
local option 66 and requires `05`, durably records conservative send intent in
an exclusively created journal, submits the exact request once on the same
shared PCI connection, and runs a separate verify on that connection.
Recovery performs one bounded guarded journal read and only authorizes that
read-only verify. The in-process canonical plan guard covers equivalent JSON
encodings during one process lifetime; it is not persistent or global, so the
stable preserved journal path is the cross-process replay boundary. After a
restart, an equivalent reserialization at another path is not deduplicated.
The verify observation path holds both local commissioning lanes. Cancelled
writes that have not started are discarded and release their confirmation
allocations; started writes and retries retain their codes through a bounded
late-ack window. Caller timing replaces plan timing; ordinary SAL, raw sends
and external traffic remain outside the guard. An already-started socket write cannot be recalled, so a
deadline or external cancellation requires closing the old transport and
reconnecting before further I/O. The caller must exclusively own and bind the
supplied `PciClient`; the library layer does not prove endpoint binding,
movement cause, persistence or physical compatibility. The `cbus-tools` CLI
binds its numeric endpoint to the plan and exposes apply/verify, but its
scripted-loopback acceptance is not hardware parity evidence.

## MQTT behavior

Home Assistant discovery and state use `homeassistant/light/` and `homeassistant/binary_sensor/` topic families. Incoming light `/set` payloads are validated by `cbus-mqtt` before the bridge converts them to lighting commands. Project labels improve entity names; deterministic address-based names are used without a project file.

The MQTT command worker preserves FIFO through correlated PCI confirmation, including byte-identical retries and late confirmations. A QoS 1 PUBACK proves only broker-to-cmqttd delivery. After positive PCI confirmation, a light state echo with `cbus_source_addr: null` is published only if no newer physical observation for the same application/group arrived after actual command submission; per-group sequencing means unrelated observations do not suppress it. The echo remains requested-state data, not physical brightness evidence. Every confirmed command queues a level-status request for its application/block on the independent readback lane and publishes its command result even when the echo was suppressed; only the resulting bus report populates the embedded C-Gate live-level cache. `cmqttd/cbus/command_result` carries non-retained `confirmed`, `rejected`, `uncertain`, or pre-send rejection outcomes plus readback-request status. Timeout or disconnect is outcome-uncertain and is never automatically replayed on a fresh connection. The cmqttd meta binary sensor publishes retained `OFF` on C-Bus loss and `ON` after reconnect, when a forced configured sweep replaces invalidated observations.

`cmqttd` can periodically synchronize time, answer C-Bus clock requests, and request status updates. Set the corresponding interval to zero to disable periodic time or status work; use `--no-clock` to disable clock replies.

## Project data

Supported project inputs are a one-file `.cbz` zip archive or bare project XML. The reader extracts networks, applications, groups, units, serial/catalogue metadata, and group-address channel mappings. If `--cbus-network` is omitted, `cmqttd` uses the first network. Site project files are sensitive operational data and are ignored by Git.

## Test data and evidence

- `rust/testdata/vectors/` contains JSONL cases for checksums, frame encode/decode, native AIRCON, AUDIO, Security, Measurement, Telephony, Media Transport, Identify, Short Message and Error Reporting commands/events, native label-cache clear, ramp rates, MQTT topics, Home Assistant discovery, and strict selected-serial plan interchange.
- `rust/testdata/fixtures/` contains small non-production project and behavior fixtures, including sanitized disposable-native evidence for ACCESS, CONFIG, FILE, AIRCON, AUDIO, Security, Measurement, Telephony, Media Transport, Identify, Short Message, Error Reporting and project copy/delete behavior.
- `cbus-golden-tests` generates a named test per committed vector.
- `cmqttd` system tests run the real daemon against an in-process MQTT broker and scripted PCI, including ACCESS, CONFIG and FILE durability/no-PCI coverage, the maintained specialist application families' command/event correlation, authentication and MQTT continuity, plus dedicated continuity checks after project administration.
- `cgate-mock` integration tests cover framing, state, sessions, event fanout, here-documents, inventory reachability, and programming access.
- `toolkit-cli/tests/test_rust_cgate_interop.py` drives the Rust mock using the production Python C-Gate client and typed workflows.

Use exact vector evidence for byte and JSON claims. Use system tests for claims involving sockets, MQTT, child processes, concurrency, or reconnect behavior.

# System reference

## Data flow

`cbus-toolkit` is the Python project and commissioning application. Offline workflows edit XML/CBZ or plan device settings; online workflows use its C-Gate client and typed wrappers, or its direct PCI client. Native C-Gate supplies online server behavior. Rust `cgate-mock` can stand in for that server during tests. The Toolkit CLI is maintained independently of the Rust bridge.

`cmqttd` connects one C-Bus PCI/CNI endpoint to one MQTT broker and can also serve C-Gate clients through `--cgate-bind`. Both interfaces share one transport. Incoming C-Bus frames become typed protocol values, state publications, and Home Assistant discovery messages. Valid MQTT commands and supported C-Gate lighting, lighting and direct-network `DO` methods, named-scene playback, Trigger, Enable, clock, dynamic-label, standard label-cache clear, eDLT label-clear, install-MMI discovery, verified project-identity parameter-35 writes and physical PP LOAD/SAVE commands become C-Bus traffic. `DO` lighting and `SYNC` are aliases over the same physical backends and retain native `202 Done` replies; `DO ... UNRAVEL` is explicitly unavailable until a physical unravel backend exists. NET SYNC additionally reads native KEYGL5 metadata only for non-error present MMI states one or two with exactly one raw IDENTIFY4 reply carrying a known serial and both configured and freshly identified types equal to KEYGL5. State three and addresses with zero or multiple raw replies—including repeated identical known replies and mixed known/unknown replies—receive no metadata reads and expose no stale values. Retained classfile order uses the captured OEM `09 00` route for parameter `0xFB` length 9 (`FirmwareVersion`), address 16 length 2 (`Application` and `Application2`), and parameter `0xFA` length 44 (`WidgetGroups`); cached `Version` remains IDENTIFY2. Optional failures keep earlier fresh values, invalidate the failed and later values, leave overall identity SYNC successful, and fault the exact-once programming lane until reconnect. Reconnect or transport loss invalidates an in-flight snapshot before commit. Named scene recording persists physically observed lighting levels; playback uses confirmed zero-time ramps followed by status requests. Dynamic labels cover raw/text, icon, language, segmented UTF-8, and dynamic bitmap forms on lighting, Trigger, and Enable applications. Standard `LABEL CLEAR` sends exactly one native all-key or keyed point-to-point cache command and has PCI confirmation only; the KEYGL5 `CLEAREDLT` control separately requires PCI and source/tag-correlated unit acknowledgement. Neither those commands nor WidgetGroups provide physical dynamic-label cache readback. A Toolkit `.cbz` or bare XML project supplies human-readable network, application, group, and unit metadata; the embedded C-Gate service imports it into a persistent database. Physical programming also requires private decoded unit specifications supplied with `--cgate-unitspec`; SAVE supports captured `direct`, `edlt`, `paged`, `ncc`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and `goc2` methods with `none`/`checksum` protection and native unlock handling for supported `lock` fields. Specifications containing the vendor `ncc` method receive the C-Bus 3 Save-to-NVM EXECUTE/POLL sequence after changed ranges have been read back. The same programming lane provides protected physical unit readdressing with source/destination identity guards, a one-use unit challenge, exact-once STORE, and a destination-address acknowledgement. MQTT continues to receive bus events through the shared packet fanout during these transactions.

`cbus-tools` calls the same protocol and project readers for one-shot work. `cbus-simulator` supplies a development PCI/CNI endpoint. `cbus-cgate` is an independent in-memory C-Gate protocol model exposed over TCP by `cgate-mock`.

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
here-document framing, but completed DBSETXML/CGL documents return 502 without
mutation because their typed-object/vendor-format semantics remain unavailable.
Schneider archive/CGL formats, `PROJECT REPAIR`, and `REPOSITORY USE` remain unavailable. These
operations perform no PCI I/O, and a real-daemon system regression verifies
that MQTT commands continue through the shared PCI after the administrative
workflow.

## Source ownership

Toolkit modules live under `toolkit-cli/src/cbus_toolkit/`; its tests are under `toolkit-cli/tests/`. Its feature docs, compatibility ledger, and retained acceptance evidence describe supported workflows and profiles. The Rust workspace is organized as follows.

| Crate | Responsibility |
| --- | --- |
| `cbus-protocol` | Typed C-Bus packets, CAL, SAL, reports, checksums, encoding, decoding, and stable JSON |
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

The protocol crate covers point-to-multipoint, point-to-point, device-management, install-MMI status, reset, confirmation, error, and special packets. CAL support includes identify, recall, reply, NAK, standard label-cache clear, and extended execute, poll, status reply, and legacy extended messages. SAL support includes lighting, Trigger Control, clock, Enable Control, temperature, dynamic labels, status requests and install-MMI requests. Strict decoding rejects malformed input; lenient decoding retains compatibility behavior for imperfect frames. Install-MMI response decoding is enabled only during its active transaction because its wire header is ambiguous with priority-three addressed traffic.

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

`cmqttd` can periodically synchronize time, answer C-Bus clock requests, and request status updates. Set the corresponding interval to zero to disable periodic time or status work; use `--no-clock` to disable clock replies.

## Project data

Supported project inputs are a one-file `.cbz` zip archive or bare project XML. The reader extracts networks, applications, groups, units, serial/catalogue metadata, and group-address channel mappings. If `--cbus-network` is omitted, `cmqttd` uses the first network. Site project files are sensitive operational data and are ignored by Git.

## Test data and evidence

- `rust/testdata/vectors/` contains JSONL cases for checksums, frame encode/decode, native label-cache clear, ramp rates, MQTT topics, Home Assistant discovery, and strict selected-serial plan interchange.
- `rust/testdata/fixtures/` contains small non-production project and behavior fixtures, including sanitized disposable-native evidence for project copy/delete.
- `cbus-golden-tests` generates a named test per committed vector.
- `cmqttd` system tests run the real daemon against an in-process MQTT broker and scripted PCI, including dedicated MQTT-continuity coverage after project copy/delete and after other project/repository/document administration.
- `cgate-mock` integration tests cover framing, state, sessions, event fanout, here-documents, inventory reachability, and programming access.
- `toolkit-cli/tests/test_rust_cgate_interop.py` drives the Rust mock using the production Python C-Gate client and typed workflows.

Use exact vector evidence for byte and JSON claims. Use system tests for claims involving sockets, MQTT, child processes, concurrency, or reconnect behavior.

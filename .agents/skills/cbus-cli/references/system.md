# System reference

## Data flow

`cbus-toolkit` is the Python project and commissioning application. Offline workflows edit XML/CBZ or plan device settings; online workflows use its C-Gate client and typed wrappers, or its direct PCI client. Native C-Gate supplies online server behavior. Rust `cgate-mock` can stand in for that server during tests. The Toolkit CLI is maintained independently of the Rust bridge.

`cmqttd` connects one C-Bus PCI/CNI endpoint to one MQTT broker and can also serve C-Gate clients through `--cgate-bind`. Both interfaces share one transport. Incoming C-Bus frames become typed protocol values, state publications, and Home Assistant discovery messages. Valid MQTT commands and supported C-Gate lighting, Trigger, Enable, clock, install-MMI discovery and physical PP LOAD/SAVE commands become C-Bus traffic. A Toolkit `.cbz` or bare XML project supplies human-readable network, application, group, and unit metadata; the embedded C-Gate service imports it into a persistent database. Physical programming also requires private decoded unit specifications supplied with `--cgate-unitspec`; SAVE supports captured `direct`, `edlt`, `paged`, `ncc`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and `goc2` methods with `none`/`checksum` protection and native unlock handling for supported `lock` fields. Specifications containing the vendor `ncc` method receive the C-Bus 3 Save-to-NVM EXECUTE/POLL sequence after changed ranges have been read back. The same programming lane provides protected physical unit readdressing with source/destination identity guards, a one-use unit challenge, exact-once STORE, and a destination-address acknowledgement. MQTT continues to receive bus events through the shared packet fanout during these transactions.

`cbus-tools` calls the same protocol and project readers for one-shot work. `cbus-simulator` supplies a development PCI/CNI endpoint. `cbus-cgate` is an independent in-memory C-Gate protocol model exposed over TCP by `cgate-mock`.

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

The protocol crate covers point-to-multipoint, point-to-point, device-management, install-MMI status, reset, confirmation, error, and special packets. CAL support includes identify, recall, reply, NAK, and extended execute, poll, status reply, and legacy extended messages. SAL support includes lighting, Trigger Control, clock, Enable Control, temperature, status requests and install-MMI requests. Strict decoding rejects malformed input; lenient decoding retains compatibility behavior for imperfect frames. Install-MMI response decoding is enabled only during its active transaction because its wire header is ambiguous with priority-three addressed traffic.

The transport reassembles bounded byte streams, initializes the PCI, assigns confirmation codes, retries unconfirmed frames, and gives interactive commands priority over background status sweeps. It supports TCP CNI and serial PCI connections.

## MQTT behavior

Home Assistant discovery and state use `homeassistant/light/` and `homeassistant/binary_sensor/` topic families. Incoming light `/set` payloads are validated by `cbus-mqtt` before the bridge converts them to lighting commands. Project labels improve entity names; deterministic address-based names are used without a project file.

`cmqttd` can periodically synchronize time, answer C-Bus clock requests, and request status updates. Set the corresponding interval to zero to disable periodic time or status work; use `--no-clock` to disable clock replies.

## Project data

Supported project inputs are a one-file `.cbz` zip archive or bare project XML. The reader extracts networks, applications, groups, units, serial/catalogue metadata, and group-address channel mappings. If `--cbus-network` is omitted, `cmqttd` uses the first network. Site project files are sensitive operational data and are ignored by Git.

## Test data and evidence

- `rust/testdata/vectors/` contains JSONL cases for checksums, frame encode/decode, ramp rates, MQTT topics, and Home Assistant discovery.
- `rust/testdata/fixtures/` contains small non-production project and behavior fixtures.
- `cbus-golden-tests` generates a named test per committed vector.
- `cmqttd` system tests run the real daemon against an in-process MQTT broker and scripted PCI.
- `cgate-mock` integration tests cover framing, state, sessions, event fanout, here-documents, inventory reachability, and programming access.
- `toolkit-cli/tests/test_rust_cgate_interop.py` drives the Rust mock using the production Python C-Gate client and typed workflows.

Use exact vector evidence for byte and JSON claims. Use system tests for claims involving sockets, MQTT, child processes, concurrency, or reconnect behavior.

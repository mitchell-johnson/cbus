# System reference

## Data flow

`cmqttd` connects one C-Bus PCI/CNI endpoint to one MQTT broker. Incoming C-Bus frames become typed protocol values, state publications, and Home Assistant discovery messages. Valid MQTT light commands become C-Bus lighting commands. A Toolkit `.cbz` or bare XML project supplies human-readable network, application, group, and unit metadata.

`cbus-tools` calls the same protocol and project readers for one-shot work. `cbus-simulator` supplies a development PCI/CNI endpoint. `cbus-cgate` is an independent in-memory C-Gate protocol model exposed over TCP by `cgate-mock`.

## Workspace ownership

| Crate | Responsibility |
| --- | --- |
| `cbus-protocol` | Typed C-Bus packets, CAL, SAL, reports, checksums, encoding, decoding, and stable JSON |
| `cbus-transport` | TCP/serial framing, PCI initialization, confirmations, retries, reconnection, and flow control |
| `cbus-mqtt` | MQTT topics and payloads, Home Assistant discovery, and CBZ/XML project metadata |
| `cmqttd` | Runtime orchestration between transport and MQTT |
| `cbus-tools` | Frame decoding, label export, and TCP unit interrogation |
| `cbus-simulator` | Fake PCI/CNI TCP endpoint |
| `cbus-cgate` | C-Gate parser, command registry, state model, and `cgate-mock` server |
| `cbus-vector-check` | Standalone JSONL compatibility-vector runner |
| `cbus-golden-tests` | Generated exact-vector and finite-domain tests |
| `cbus-test-support` | In-process MQTT broker, scripted PCI, process, and wait helpers |

Put new behavior in its owning crate. Avoid embedding byte-level rules in a binary or network behavior in the protocol crate.

## Protocol behavior

The protocol crate covers point-to-multipoint, point-to-point, device-management, reset, confirmation, error, and special packets. CAL support includes identify, recall, reply, and extended messages. SAL support includes lighting, clock, enable control, temperature, and status requests. Strict decoding rejects malformed input; lenient decoding retains compatibility behavior for imperfect frames.

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

Use exact vector evidence for byte and JSON claims. Use system tests for claims involving sockets, MQTT, child processes, concurrency, or reconnect behavior.

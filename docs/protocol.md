# Protocol and data formats

## C-Bus packets

`cbus-protocol` models point-to-multipoint, point-to-point, routed point-to-point-to-multipoint, device-management, reset, confirmation, error, and special packet forms. It includes CAL identify, recall, reply, and extended messages; lighting, Air-Conditioning, clock, enable, temperature, and status-request SALs; binary and Manchester status reports; checksum helpers; ramp-rate conversion; and stable packet JSON.

Air-Conditioning application `0xAC` has typed encode/decode coverage for the
eleven commands registered by C-Gate 3.4: refresh, ward off/on, zone HVAC and
humidity modes, and upper/lower/setback limits for both measurements. The
native payload captures are in `rust/testdata/vectors/aircon.jsonl`. These are
broadcast SAL messages; a positive PCI confirmation proves interface delivery
only and carries no controller-level acceptance or state readback.

The same application decoder preserves the eight C-Gate 3.4 report forms for
HVAC/humidity schedule entries, plant status, zone temperature/humidity and
plant output levels. They have canonical `aircon_status` JSON and remain typed
transport events while a command confirmation is pending. Application dispatch
handles extended humidity schedule opcode `0xA9` before the generic dynamic
label prefix. Unknown opcodes, reserved bits and malformed ranges fail closed.

Strict decoding rejects malformed input. Lenient decoding retains compatibility behavior for imperfect frames. The golden-vector suite fixes the expected byte consumption, decoded JSON, and re-encoded bytes for representative and edge-case traffic.

## Framing and PCI behavior

`cbus-transport` reassembles byte streams with a bounded buffer, performs the PCI initialization sequence, assigns confirmation codes, retransmits unconfirmed frames, and prioritizes interactive commands over background status sweeps. It supports TCP CNI connections and serial PCI connections.

Network-interface discovery is a separate IPv4 UDP exchange. `cbus-tools
cni-discover` and `cbus-toolkit interface discover-cni` send the exact retained
19-byte query once and strictly decode fixed 30-byte CNI2/Wiser replies through
a bounded deadline. See the [discovery contract](../toolkit-cli/docs/cni-discovery.md).

The transport emits typed events to consumers and retains raw consumed bytes where tests or diagnostics need them.

Source-routed requests support one through six bridges. Outbound PTP and PPM
frames encode Network PCI stack headers `09`, `12`, …, `36`; smart-mode
responses decode the native Reply Network count `01` through `06`. Routed MMI
and IDENTIFY transactions require the expected first bridge, remaining route,
and terminal unit where applicable, so traffic from a direct or neighbouring
network cannot populate the requested network's cache. Exact native C-Gate and
CBUS-SIUG forms are pinned in `testdata/vectors/encode.jsonl` and
`decode_from_pci.jsonl`.

## MQTT convention

`cmqttd` publishes Home Assistant discovery and state under `homeassistant/light/` and `homeassistant/binary_sensor/` topic families. Incoming light `/set` payloads are parsed by `cbus-mqtt` and converted into C-Bus lighting commands. Project labels improve entity names; addresses provide deterministic fallback names.

MQTT command ordering extends through the correlated PCI confirmation rather than ending when bytes reach the socket. Positive confirmation produces the legacy null-source state echo only if no newer physical observation for the same application/group arrived after command submission. Per-group sequencing means an observation for another group cannot suppress the echo. Every confirmed command still queues one codeless level-status request and publishes its non-retained `cmqttd/cbus/command_result` receipt; the physical report is a separate observation. Negative confirmation produces no success echo. Timeout or connection loss is reported as outcome-uncertain and the command is not replayed after reconnect. The retained cmqttd binary-sensor state is `OFF` while the C-Bus transport is lost and `ON` after a replacement is installed; reconnect forces a configured status sweep.

## Project data

Project metadata can be read from a one-file `.cbz` zip archive or bare XML. The reader extracts networks, applications, groups, units, serial/catalogue metadata, and group-address channel mappings. Select a named network with `cmqttd --cbus-network ...`; otherwise the first network is used.

Project files are site-specific and are intentionally ignored by Git.

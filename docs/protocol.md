# Protocol and data formats

## C-Bus packets

`cbus-protocol` models point-to-multipoint, point-to-point, routed point-to-point-to-multipoint, device-management, reset, confirmation, error, and special packet forms. It includes CAL identify, recall, reply, and extended messages; lighting, Air-Conditioning, Media Transport, Audio, Security, Measurement, clock, enable, temperature, and status-request SALs; binary and Manchester status reports; checksum helpers; ramp-rate conversion; and stable packet JSON.

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

Audio application `0xCD` has typed encode/decode coverage for all 19 C-Gate
3.4 commands, both native address forms, and the retained rate-family opcode
overlaps. Canonical JSON uses `audio` for commands and `audio_event` for the
intended standard-label observations. Exact command and observation bytes are
in `rust/testdata/vectors/audio.jsonl`; the isolated C-Gate capture, boundary
grammar, Z-function transformations, and native label/icon decoder defect are
in `rust/testdata/fixtures/native_cgate_audio.json`. C-Gate 3.4.0.2001 silently
drops valid standard Audio label/icon frames because its decoder compares a
byte count with a hexadecimal character count. The Rust decoder implements
the intended retained A0 layout as an explicit repair and does not accept C0
Unicode as native Audio traffic.

Security application `0xD0` has typed encode/decode coverage for all seven
C-Gate 3.4 commands and every native event opcode from `0x80` through `0x98`.
It preserves the compact `01`/`79` boolean forms, `09`/`0A` command forms,
variable `E1`–`F3` observed display messages, fixed 11-byte zone names and both packed
two-bit zone-status reports. Canonical JSON uses `security` for commands and
`security_event` for observations. Unknown prefix/opcode combinations,
malformed lengths, invalid boolean values and zones outside 1–127 fail closed.
The 52 exact command/report cases are in
`rust/testdata/vectors/security.jsonl`; the retained native capture and class
hashes are in `rust/testdata/fixtures/native_cgate_security.json`.

Measurement application `0xE4` has typed encode/decode coverage for C-Gate
3.4's `MEASUREMENT DATA` broadcast. Its fixed SAL is `0E`, device, channel,
units, signed multiplier, then a signed big-endian 16-bit value. Canonical JSON
uses `measurement_data`. Exact native extremes and signed cases are pinned in
`rust/testdata/vectors/measurement.jsonl` and
`rust/testdata/fixtures/native_cgate_measurement.json`. Incoming samples remain
typed transport events and cannot satisfy a pending PCI confirmation.

Media Transport application `0xC0` has typed, lossless encode/decode coverage
for all 21 C-Gate 3.4 messages: playback controls, category/selection/track
selection, enumeration requests/reports, track totals, status requests, source
power, and fragmented names. Basic SAL lengths and extended `0x8x`, `0xAx`
and `0xCx` name lengths are validated before decode; signed-size fields,
reserved operations, page sizes and name lengths fail closed. Outbound WNI 3
and 4 remain reserved, while inbound decode follows native C-Gate and preserves
the full packed three-bit WNI range 0–7. Raw
name fragments use `text_hex` in canonical `mediatransport` JSON. Application
dispatch precedes the generic dynamic-label prefix check. The exact vectors
are in `rust/testdata/vectors/mediatransport.jsonl`, with retained native
C-Gate build/class hashes and parser evidence in
`rust/testdata/fixtures/native_cgate_mediatransport.json`. No MQTT player
state is derived from these bus observations.

Telephony application `0xE0` has typed encode/decode coverage for all five
maintained C-Gate 3.4 commands and the seven native device-event families.
Canonical JSON uses `telephony` for commands and `telephony_event` for device
observations. The decoder applies the native short-prefix low-three-bit and
extended-prefix low-five-bit length rules and rejects unknown modes,
directions, opcodes and truncated payloads. Exact command/event bytes,
including the retained native malformed non-ASCII diversion case, are pinned
in `rust/testdata/vectors/telephony.jsonl`; isolated-oracle grammar, hashes and
acceptance limits are in
`rust/testdata/fixtures/native_cgate_telephony.json`. Incoming Telephony
traffic stays a typed event and cannot satisfy a pending PCI confirmation.

DALI gateway control uses direct point-to-point extended CAL addressed to a
`SYS_DAL2` unit with device type `0xDA`. The retained controls are EXECUTE
`0x81`, POLL `0x82`, STATUS `0x83`, and CANCEL `0x84`; DALI uses priority class
zero and carries no PCI confirmation code. Completion therefore requires a
source-correlated extended reply from the gateway. AUTO sends EXECUTE exactly
once, then polls at most ten times at 1.5-second intervals while status is
IN_PROGRESS or FAIL_BUSY. Connection loss makes the result uncertain and the
request is not replayed. Exact request/reply and JSON cases are in
`rust/testdata/vectors/dali.jsonl`; native help evidence for all 128 maintained
DALI paths is in `rust/testdata/fixtures/native_cgate_dali_help.json`.

Strict decoding rejects malformed input. Lenient decoding retains compatibility behavior for imperfect frames. The golden-vector suite fixes the expected byte consumption, decoded JSON, and re-encoded bytes for representative and edge-case traffic.

## Framing and PCI behavior

`cbus-transport` reassembles byte streams with a bounded buffer, performs the PCI initialization sequence, assigns confirmation codes, retransmits unconfirmed frames, and prioritizes interactive commands over background status sweeps. It supports TCP CNI connections and serial PCI connections.

Network-interface discovery is a separate IPv4 UDP exchange. `cbus-tools
cni-discover` and `cbus-toolkit interface discover-cni` send the exact retained
19-byte query once and strictly decode fixed 30-byte CNI2/Wiser replies through
a bounded deadline. See the [discovery contract](../toolkit-cli/docs/cni-discovery.md).

C-Gate `PORT CNISCAN` and `PORT CNISCAN2` use related but distinct retained
protocols. The legacy scan binds UDP 30718, sends `00 00 00 F8`, accepts only
124-byte replies and reads the service port little-endian at offsets 24–25.
The CNI2 phase binds UDP 20050 and sends a CCP packet with a four-byte sequence,
read instructions for parameters 0, 1, 2, 3, 4, 5, 7, 9, 11–16, 29 and 30,
then `80 01 02` and a big-endian CRC-CCITT initialized to `0xFA50`. Its
variable response instructions provide device type, connected status, IP,
TCP port, MAC, packed serial and C-Bus unit address. Exact retained and
malformed cases are in `rust/testdata/vectors/cni_discovery.jsonl`; the native
command evidence is in `rust/testdata/fixtures/native_cgate_port.json`.

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

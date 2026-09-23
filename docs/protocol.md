# Protocol and data formats

## C-Bus packets

`cbus-protocol` models point-to-multipoint, point-to-point, device-management, reset, confirmation, error, and special packet forms. It includes CAL identify, recall, reply, and extended messages; lighting, clock, enable, temperature, and status-request SALs; binary and Manchester status reports; checksum helpers; ramp-rate conversion; and stable packet JSON.

Strict decoding rejects malformed input. Lenient decoding retains compatibility behavior for imperfect frames. The golden-vector suite fixes the expected byte consumption, decoded JSON, and re-encoded bytes for representative and edge-case traffic.

## Framing and PCI behavior

`cbus-transport` reassembles byte streams with a bounded buffer, performs the PCI initialization sequence, assigns confirmation codes, retransmits unconfirmed frames, and prioritizes interactive commands over background status sweeps. It supports TCP CNI connections and serial PCI connections.

The transport emits typed events to consumers and retains raw consumed bytes where tests or diagnostics need them.

## MQTT convention

`cmqttd` publishes Home Assistant discovery and state under `homeassistant/light/` and `homeassistant/binary_sensor/` topic families. Incoming light `/set` payloads are parsed by `cbus-mqtt` and converted into C-Bus lighting commands. Project labels improve entity names; addresses provide deterministic fallback names.

## Project data

Project metadata can be read from a one-file `.cbz` zip archive or bare XML. The reader extracts networks, applications, groups, units, serial/catalogue metadata, and group-address channel mappings. Select a named network with `cmqttd --cbus-network ...`; otherwise the first network is used.

Project files are site-specific and are intentionally ignored by Git.

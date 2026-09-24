# cmqttd C-Gate service

`cmqttd` provides an optional C-Gate command listener alongside MQTT. Both
interfaces share the same `PciClient`, writer, pacing, initialization and CNI
socket. Neither Windows nor Schneider's C-Gate process is required for the
operations listed here. `cgate-mock` remains a separate test server.

## Start and connect

```sh
rust/target/release/cmqttd --broker-address BROKER --broker-disable-tls \
  --tcp CNI:10001 --project-file house.cbz \
  --cgate-bind 127.0.0.1:20023 --cgate-state cmqttd-data/cgate.json
cbus-toolkit cgate --host 127.0.0.1 exec 'CMQTT CAPABILITIES'
```

Select the project network with `--cbus-network 'Network name'`. The initial
project import accepts XML or CBZ. An existing state file takes precedence
over the initial project contents and must contain the configured network.
Malformed state fails startup rather than discarding the database.

Docker Compose publishes port 20023 on the host loopback only (the container
listens on `0.0.0.0:20023` on its private bridge network) and mounts the named
`cmqttd_data` volume at `/var/lib/cmqttd`. `CMQTTD_CGATE_BIND=off` disables it.
The command listener currently has no TLS or authentication; keep its default
loopback binding. MQTT's existing TLS/authentication options remain independent.
Project files and the persistent database contain site information and must
not be committed or published.

## Implemented behavior

| Operation | Backend and verification |
| --- | --- |
| Tagged/untagged commands, per-client project selection, EVENT subscriptions | TCP service; 64 clients, 1 MiB command limit, bounded event queues and writer deadlines |
| Project list/use/load/save/new/close; database CRUD and database snapshots | Persistent JSON database; atomic replacement, restrictive permissions, failed-write rollback |
| Database PP locks, sessions, get/set/info/new/load/save | Existing programming model with connection ownership; staged sessions and locks are discarded on disconnect/restart |
| ON/OFF/RAMP/TERMINATERAMP and lighting variants | Actual shared PCI, negative confirmations return errors; successful delivery is distinct from observed physical brightness |
| GET group level | Real observed bus levels; unobserved levels return 408, never invented zero |
| Unit identification | Source-correlated CAL replies from the physical unit |
| OEM physical memory reads | Volatile 0x41 pointer selection plus segmented RECALL; no EEPROM writes |
| KEYGL5 5.5.00 static strings and lighting/scene widget labels | Python reader uses the service; checks physical identity, stable header and static-text CRC |

Runtime levels and physical presence are not persisted. The persistent data is
cmqttd's own database format, not a Schneider SQLite database. Database PP
editing does not program the corresponding physical unit. Optional
`--cgate-unitspec DIR` supplies privately installed vendor schemas for PP INFO
and defaults; no vendor specifications are distributed in this repository.

## Live label reads

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 30 \
  edlt-labels //PROJECT/254/p/5
```

The JSON includes the device identity, all 64 static strings, widget positions,
scene names, verification flags and a memory SHA-256. Identity is read from the
device; the display name comes from the imported database. Dynamic labels are
explicitly unverified. Other device families/configuration versions are rejected.

Physical string slots can retain old bytes after a shortened string's null
terminator. The reader reports whether the stored CRC matches the physical
bytes or Toolkit's zero-padded text projection; either must match before static
labels are accepted. The full physical-memory hash still includes those bytes.

These additional commands are **cmqttd extensions**, not claims about native
C-Gate syntax:

```text
CMQTT CAPABILITIES
CMQTT UNIT //PROJECT/254/p/5
UNIT IDENTIFY //PROJECT/254/p/5 1
UNIT READMEM //PROJECT/254/p/5 4096 256
```

`READMEM` uses decimal **physical** offsets and accepts 1–4096 bytes per command.
For the evidenced OEM mapping, a unit-spec logical offset of 256 or greater maps
to physical offset `logical - 256`. The CLI assembles smaller blocks. CAL
transactions are serialized, match the source unit and parameter, reject excess
data, and time out. After an incomplete/cancelled programming transaction, a
fresh PCI connection is required before another programming read: late untagged
fragments must not be mistaken for a new result. MQTT traffic is independent.

## Outstanding replacement work

The existing mock dispatches 431 command paths. That is **not** evidence that
all 431 have physical implementations in this service. `CMQTT CAPABILITIES`
returns `full_cgate_compatibility: false`; unimplemented physical operations
return 502. Full replacement still requires:

- Physical PP LOAD/SAVE with complete schema memory codecs, checksums,
  readback, device profiles, recovery and hardware acceptance.
- Network discovery/synchronization, bridged networks, serial addressing,
  readdressing, clock configuration and commissioning state transitions.
- Physical scenes, triggers, Enable, text/icon broadcasts, dynamic eDLT label
  cache reads, and specialist application families such as HVAC/audio/security.
- Native repository/archive/import/export formats, document commands,
  complete server configuration/access/TLS, firmware and deployment workflows.
- Command-by-command native interoperability and physical acceptance beyond
  the supported device profiles. Full Toolkit workflow parity remains tracked
  separately in `toolkit-cli/docs/implementation-status.md`.

## Tests

`cbus-transport` tests cover captured programming route bytes, source filtering,
segmented recall, interleaved lighting, incomplete transactions, and confirmation
success/failure. Exact incoming frames are retained in `rust/testdata/vectors/`.
`cbus-cgate` service tests cover durable reload, corrupt-file preservation,
rollback, session ownership, unsupported hardware rejection, fragmented command
input during events, disconnect cleanup and input bounds. The real cmqttd system
test sends commands through C-Gate and MQTT and verifies a single PCI connection.
`toolkit-cli/tests/test_cmqtt.py` tests synthetic eDLT decoding and read contracts.
None of these fixtures contains a user's project or labels.

On 24 September 2026, the Docker deployment was also checked against a real
KEYGL5 running 5.5.00. The CLI read all 64 static strings and the five visible
lighting/scene labels through cmqttd, with stable header and matching Toolkit
text CRC. A relay was switched through C-Gate, independently reported 255 then
0, and restored to its original OFF state. The container retained its database
across recreation and maintained one CNI socket alongside its MQTT connection.
These checks cover that device/profile and relay path; they do not establish
complete physical C-Gate acceptance. Site reports are private and excluded from Git.

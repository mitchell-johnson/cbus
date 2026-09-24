# cmqttd C-Gate service

`cmqttd` provides an optional C-Gate command listener alongside MQTT. Both
interfaces share the same `PciClient`, writer, pacing, initialization and CNI
socket. Neither Windows nor Schneider's C-Gate process is required for the
operations listed here. `cgate-mock` remains a separate test server.

## Start and connect

```sh
rust/target/release/cmqttd --broker-address BROKER --broker-disable-tls \
  --tcp CNI:10001 --project-file house.cbz \
  --cgate-bind 127.0.0.1:20023 --cgate-state cmqttd-data/cgate.json \
  --cgate-unitspec /private/decoded/unitspec
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
| Physical PP LOAD and subsequent GET/INFO | Identifies the live unit, selects its privately installed decoded schema, recalls standard CAL parameters, explicit pages for `paged`/`ncc`, OEM memory, and GOC parameter-`0xFF` memory through the shared PCI, decodes int/long/bit/string/sixbit arrays and `ArrayMap`, applies tag selection, and commits the session only after every read succeeds |
| Physical PP SAVE/SAVE_TO_SOURCE | Writes only dirty, tag-selected `direct`, `edlt`, `paged`, `ncc`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and `goc2` parameters with `none`/`checksum`/supported `lock` protection. Page-aware writes split at 256-byte boundaries; OEM methods use the selector/data path; GIU halts and resumes the unit; DALI observes the native settling interval; GOC methods use parameter `0xFF`, a big-endian address prefix, and their native block limits. The service validates the complete plan and live type/firmware first, preserves shared bits through pre-read/encode, requires source/parameter-matched acknowledgements, and reads every stored range back before success. Specifications containing the vendor `ncc` method are classified as C-Bus 3; after a changed save, the service runs native group-0 operation-4 EXECUTE/POLL until the NVM commit succeeds |
| ON/OFF/RAMP/TERMINATERAMP and lighting variants | Actual shared PCI, negative confirmations return errors; successful delivery is distinct from observed physical brightness |
| GET group level | Real observed bus levels; unobserved levels return 408, never invented zero |
| SCENE RECORD/PLAY | RECORD atomically persists the configured network's observed lighting levels under the named set/scene. PLAY sends a confirmed zero-time ramp for every stored level, invalidates the old cache, and schedules physical status readback. Unknown scenes retain the native 401 response |
| TRIGGER EVENT/INDICATORKILL | Actual Trigger Control SAL on application 202; incoming events update the live service cache and event stream |
| ENABLE SET/REMOVE and GET | SET sends actual Enable Control SAL on application 203; REMOVE follows C-Gate's server-side saved-value behavior; incoming values update the live cache |
| CLOCK DATE/TIME/REQUEST_REFRESH | Actual Clock and Timekeeping SAL on application 223, including `SYSTEM` date/time resolution and observed-value queries |
| TEMPERATURE BROADCAST | Actual Temperature Broadcast SAL on application 25 with decimal or `$19` addressing, native one-decimal input, range checks, quarter-degree wire conversion, incoming event delivery and disconnect-safe live caching |
| LIGHTING/TRIGGER/ENABLE LABEL and UNICODELABEL | Actual checksummed dynamic-label SAL on the selected application. Supports raw/text payloads, built-in icon references, language selection, native segmented UTF-8, and start/header/chunk/commit dynamic bitmap uploads. Every fragment requires positive PCI delivery confirmation; Enable Unicode and invalid native bounds fail before transmission |
| NET PINGU and GET network Units | Actual installation MMI request using cmqttd's negotiated PCI checksum mode; buffers blocks that a CNI forwards before its positive confirmation, accepts only confirmed contiguous coverage of all addresses 0–255, and reports the native sorted `302-Units=` form |
| NET SYNC and cached unit getters | Configured interface routing hint (physically revalidated) or BASIC discovery, complete installation MMI, then confirmed IDENTIFY1/2 probes and bounded IDENTIFY4 collection for every present address; routed and local bare-CAL replies are correlated, silent legacy/error addresses remain present with unknown identity fields, the live cache is replaced atomically, and native getters expose it |
| NET CHECKUNIT | Active confirmed IDENTIFY4 collection through the native two-second quiet interval, with the native no-unit, single-unit, duplicate-unit and identity-error result forms; `*` expands from a fresh complete MMI |
| `SET //PROJECT/NETWORK/p/UNIT Address DESTINATION` | Physical unit readdressing through native C-Gate's protected parameter-`0x20` exchange. The service proves one source identity and an empty destination, obtains the one-use challenge, sends exactly one special address STORE, requires both PCI confirmation and the unit ACK from the destination, moves only the observed physical cache, and leaves the database address unchanged |
| Unit identification | Source-correlated CAL replies from the physical unit |
| OEM physical memory reads | Volatile 0x41 pointer selection plus segmented RECALL; no EEPROM writes |
| KEYGL5 5.5.00 static strings and lighting/scene widget labels | Python reader uses the service; checks physical identity, stable header and static-text CRC |

Runtime levels and physical presence are not persisted. The persistent data is
cmqttd's own database format, not a Schneider SQLite database. Database PP
editing does not program the corresponding physical unit. Optional
`--cgate-unitspec DIR` supplies privately installed decoded vendor schemas for
PP INFO, defaults and physical PP LOAD; no vendor specifications are distributed
in this repository. Docker automatically passes `/etc/cmqttd/unitspec` when that
directory exists. Copying private specs into `cmqttd_config/unitspec/` includes
them in a local image build while Git ignores the directory.

Physical `PP LOAD session //PROJECT/NETWORK/p/UNIT [tags...]` is read-only.
`direct` uses standard CAL parameter numbers. `paged` and `ncc` carry the
logical page and low-byte parameter explicitly, splitting at page boundaries.
The evidenced eDLT path maps logical addresses at or above 256 to OEM physical
offset `logical - 256`.
Reads are bounded, coalesced, source-correlated and serialized with MQTT traffic.
Unknown schemas, unsupported layouts, incomplete replies and changed or ended
sessions fail without replacing the previously staged values.

Physical SAVE uses captured tagged direct STORE for standard parameters, native
page selection plus tagged STORE for `paged`/`ncc`, and the OEM `0x41` address
selector plus tagged `0x42` STORE for eDLT/GIU/SGIU/DALI memory. GIU is halted
and resumed around its stores; DALI observes the native one-second settling
interval. GOC methods use parameter `0xFF` with a big-endian address prefix and
their native per-method limits. Factory and special parameters follow native
behavior and are skipped by ordinary SAVE.
Supported `lock` fields and physical unit readdressing use the native
unchecksummed, PCI-confirmed unlock and one-byte unit challenge reply after
selecting the relevant page and before STORE. Readdressing uses the vendor's
fixed `A3 20 4E <destination> <challenge>` form and recognizes its fixed success
and rejection replies rather than treating them as ordinary variable-length CAL
messages. All dirty parameters are encoded
and physically pre-read before the first STORE. Each changed range is
acknowledged and read back. For a C-Bus 3 specification, a changed save then
sends `E3 81 00 04`, polls with `E3 82 00 04` at 500 ms intervals, and returns
success only after the unit replies with status zero. Busy, NAK, unexpected
status, timeout, or transport loss fail the save; an uncertain outcome faults
the programming lane until reconnect so a late reply cannot be assigned to a
later transaction. MQTT remains active through the shared packet fanout. An
unchanged or tag-filtered save issues no NVM command. A
transport failure can still leave earlier independently acknowledged ranges
written, so multi-range recovery and power-loss acceptance remain outstanding.

Dynamic-label commands use the same syntax produced by `cbus-toolkit` for
lighting applications 48–95, Trigger Control 202, and Enable Control 203.
Standard payloads retain the native 14-byte limit. Unicode payloads are checked
as UTF-8 and split into at most eighteen native fragments. Dynamic bitmap data
must exactly match `ceil(width * height / 8)` and uses the native control
sequence around six-byte chunks. A successful response establishes PCI delivery
of every fragment; it does not prove that a particular display rendered or
persisted the label.

Named scenes are server-side snapshots, distinct from scene tables programmed
into individual units through PP. Recording includes only lighting levels that
cmqttd has physically observed on its configured network; it does not invent
unknown values. Playback stops on the first failed delivery and reports how many
earlier actions were confirmed. Its 200 response proves PCI delivery, while
fresh status reports establish the resulting physical levels.

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

- Physical PP multi-range failure recovery, power-loss behavior, and hardware write acceptance for
  every programming method and unit family. LOAD has full decoded-catalogue
  layout coverage plus live KEYGL5 acceptance; SAVE audits every well-formed
  writable catalogue default and has fake-PCI direct/page-aware/OEM/GOC
  write-readback acceptance.
- Bridged-network synchronization, serial-address broadcasts, unravel,
  project identification and the remaining commissioning state transitions.
  Direct-network `NET PINGU`, `NET SYNC` identity population, duplicate-aware
  `NET CHECKUNIT`, and guarded single-unit physical readdressing are implemented.
- Device-resident scene triggering beyond PP table programming, dynamic eDLT label cache reads, and
  specialist application families such as HVAC, audio and security.
- Native repository/archive/import/export formats, document commands,
  complete server configuration/access/TLS, firmware and deployment workflows.
- Command-by-command native interoperability and physical acceptance beyond
  the supported device profiles. Full Toolkit workflow parity remains tracked
  separately in `toolkit-cli/docs/implementation-status.md`.

## Tests

`cbus-transport` tests pin direct routing for standard recall/tagged STORE,
page-aware recall, page selection, cross-page tagged STORE, the native
protected-parameter unlock request/reply phase, and
the separate programming route for segmented OEM recall/tagged STORE, plus the
protected unit-address challenge and special STORE, including
mandatory readback, plus the C-Bus 3 Save-to-NVM EXECUTE/POLL status sequence,
definitive rejection and uncertain-reply fault handling, source filtering,
interleaved lighting, complete and incomplete installation MMI,
MMI and IDENTIFY data that precedes its positive confirmation, the confirmed
two-second IDENTIFY collection window, duplicate replies, absence, and
confirmation success/failure. Exact Trigger, Enable, Clock, Temperature Broadcast, MMI and confirmed
IDENTIFY4 request or response bytes are pinned by vectors and the real-daemon
system test. Dynamic-label vectors pin exact encode/decode JSON and wire bytes;
the real-daemon test covers text, icon, Unicode, bitmap, language selection,
vendor-invalid rejection, and confirmed multi-frame delivery on the shared PCI.
The real-daemon scene case records an observed level, verifies durable storage,
plays it as the exact confirmed zero-time ramp, and verifies that acknowledgement
does not fabricate a level observation.
`cbus-cgate` service tests cover durable reload, corrupt-file preservation,
rollback, session ownership, unsupported hardware rejection, fragmented command
input during events, disconnect cleanup, schema layout decoding and input bounds.
The decoded vendor catalogue is optionally audited through `CBUS_UNITSPEC_DIR`.
The real cmqttd system test performs physical PP LOAD and SAVE against a scripted
PCI, checks standard and OEM values, dirty/tag selection, read-modify-write
encoding, acknowledgements, readback, and the exact C-Bus 3 NVM commit sequence,
and verifies that C-Gate and MQTT retain one PCI connection while lighting events
continue through the same transport. A separate real-daemon test verifies guarded physical
readdressing, exact-once STORE transmission, database/physical layer separation,
and MQTT event delivery on that same PCI during the move.
`toolkit-cli/tests/test_cmqtt.py` tests synthetic eDLT decoding and read contracts.
None of these fixtures contains a user's project or labels.

On 24 September 2026, the Docker deployment was also checked against a real
KEYGL5 running 5.5.00. The CLI read all 64 static strings and the five visible
lighting/scene labels through cmqttd, with stable header and matching Toolkit
text CRC. A physical `PP LOAD` also decoded all 64 `StaticText` parameters from
one 4 KiB OEM-memory range and loaded the six `Direct` parameters through
standard CAL recalls; `PP GET UnitAddress` returned the live address `0x5`.
A relay was switched through C-Gate, independently reported 255 then
0, and restored to its original OFF state. The container retained its database
across recreation and maintained one CNI socket alongside its MQTT connection.
The deployed service also completed a live three-block PINGU observation,
returned the physical address list, and exposed the same list through `GET Units`.
It then completed a whole-network `NET SYNC`, preserved the synchronized snapshot
across separate C-Gate reads, returned live type, version and serial fields, and
reported a selected address as a single unit through `NET CHECKUNIT`. The Toolkit
CLI's `cgate serials refresh` workflow completed against the same deployment with
the selected unit present, unique and healthy while MQTT remained connected.
These checks cover that device/profile and relay path; they do not establish
complete physical C-Gate acceptance. Site reports are private and excluded from Git.

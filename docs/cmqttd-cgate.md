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
The command listener speaks plaintext by default and offers optional TLS
transport via `--cgate-tls-cert`/`--cgate-tls-key` (both required together,
and only alongside `--cgate-bind`); a TLS configuration failure exits before
binding and before the state file is created. The TLS handshake times out
after 10 s so a stalled client cannot hold a connection slot. TLS here is
transport-only with no TLS client authentication, so keep the
default loopback binding unless TLS termination is understood.
MQTT's existing TLS/authentication options remain independent.

The command listener also offers an opt-in command-layer LOGIN gate via
`--cgate-auth-file <token-file>` (requires `--cgate-bind`; loopback-only
first slice, explicitly not native `access.txt` parity). The file holds one
high-entropy token on its first line (generate with
`python3 -c "import secrets; print(secrets.token_hex(32))"`) with mode
`0400` or `0600`; a missing/unreadable/short/whitespace-containing token or
group/other-accessible file fails closed at startup before bind and before the
state file is created. `CMQTT CAPABILITIES` reports `cgate_auth: false`
dormant by default and `true` once armed. Armed, each connection needs
`LOGIN <token>` (200) before PP mutating verbs (`PP LOCK/LOAD/SAVE/...`;
`PP GET/INFO/LIST` stay open), `PROJECT` lifecycle, `DB...` writes, `SET`,
`LABEL CLEAR/CLEAREDLT/KFIGET/KFISET`, `DO ... FactoryDefault`,
`NET SET_PROJECT_IDENTIFY`, and
`SCENE RECORD`; `GET`/`INFO`/`DBGET`-style reads,
bus-control SAL traffic, and `SCENE PLAY` stay open. Gated verbs attempted
without the flag answer `420 LOGIN required`; a wrong token answers
`420 LOGIN failed`; a malformed `LOGIN` with no token answers 400 and also
clears the flag (never `401`, which already means
absent-object/model-denied readings); when armed, `LOGOUT` answers 200 and
clears the per-connection flag (dormant `LOGIN`/`LOGOUT` remain the generic
502). There is no attempt cap in this slice: the
loopback bind plus high-entropy token makes online guessing infeasible, and
a cap is follow-up work.
Project files and the persistent database contain site information and must
not be committed or published.

## Implemented behavior

| Operation | Backend and verification |
| --- | --- |
| Tagged/untagged commands, per-client project selection, `EVENT`/`EVENTS` subscriptions | TCP/TLS service; native `e0s0c0` connection default, 64 clients, 1 MiB command limit, bounded event queues and writer deadlines |
| `SESSION_ID`, `SESSION_ID ALL`, `SESSION_ID TAG`, `QUIT`/`EXIT` | Volatile command-session registry with odd `cmdN` identifiers, peer origin, local connection time, one-shot application tags and native 300 envelopes. A successful 204 shutdown reply is flushed before the connection closes; no project, database or PCI state is changed |
| Project list/use/load/save/new/close; database CRUD and database snapshots | Persistent JSON database; atomic replacement, restrictive permissions, failed-write rollback |
| Database PP locks, sessions, get/set/info/new/load/save | Existing programming model with connection ownership; staged sessions and locks are discarded on disconnect/restart |
| `PP RESET_TO_DEFAULTS` | Replaces one owned loaded session with exactly the `DefaultValue` fields in its parsed unit specification. The result remains staged until an explicit save; missing or malformed specifications return 408 unchanged, with no PCI access |
| Physical PP LOAD and subsequent GET/INFO | Identifies the live unit, selects its privately installed decoded schema, recalls standard CAL parameters, explicit pages for `paged`/`ncc`, OEM memory, and GOC parameter-`0xFF` memory through the shared PCI, decodes int/long/bit/string/sixbit arrays and `ArrayMap`, applies tag selection, and commits the session only after every read succeeds |
| Physical PP SAVE/SAVE_TO_SOURCE | Writes only dirty, tag-selected `direct`, `edlt`, `paged`, `ncc`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and `goc2` parameters with `none`/`checksum`/supported `lock` protection. Page-aware writes split at 256-byte boundaries; OEM methods use the selector/data path; GIU halts and resumes the unit; DALI observes the native settling interval; GOC methods use parameter `0xFF`, a big-endian address prefix, and their native block limits. The service validates the complete plan and live type/firmware first, preserves shared bits through pre-read/encode, requires source/parameter-matched acknowledgements, and reads every stored range back before success. Specifications containing the vendor `ncc` method are classified as C-Bus 3; after a changed save, the service runs native group-0 operation-4 EXECUTE/POLL until the NVM commit succeeds |
| ON/OFF/RAMP/TERMINATERAMP and lighting variants | Actual shared PCI, negative confirmations return errors; successful delivery is distinct from observed physical brightness |
| `DO` lighting methods, direct-network `SYNC`, and KEYGL5 `FactoryDefault` | Lighting and synchronization aliases use their physical backends. FactoryDefault sends the captured OEM control once, requires PCI confirmation plus the source-correlated unit ACK, clears stale observed-label traffic, and returns `202 Done: object`; `DO ... UNRAVEL` remains an explicit 502 until its physical backend exists |
| GET group level | Real observed bus levels; unobserved levels return 408, never invented zero |
| SCENE RECORD/PLAY | RECORD atomically persists the configured network's observed lighting levels under the named set/scene. PLAY sends a confirmed zero-time ramp for every stored level, invalidates the old cache, and schedules physical status readback. Unknown scenes retain the native 401 response |
| TRIGGER EVENT/INDICATORKILL | Actual Trigger Control SAL on application 202; incoming events update the live service cache and event stream |
| ENABLE SET/REMOVE and GET | SET sends actual Enable Control SAL on application 203; REMOVE follows C-Gate's server-side saved-value behavior; incoming values update the live cache |
| CLOCK DATE/TIME/REQUEST_REFRESH | Actual Clock and Timekeeping SAL on application 223, including `SYSTEM` date/time resolution and observed-value queries |
| TEMPERATURE BROADCAST | Actual Temperature Broadcast SAL on application 25 with decimal or `$19` addressing, native one-decimal input, range checks, quarter-degree wire conversion, incoming event delivery and disconnect-safe live caching |
| LIGHTING/TRIGGER/ENABLE LABEL and UNICODELABEL | Actual checksummed dynamic-label SAL on the selected application. Supports raw/text payloads, built-in icon references, language selection, native segmented UTF-8, and start/header/chunk/commit dynamic bitmap uploads. Every fragment requires positive PCI delivery confirmation; Enable Unicode and invalid native bounds fail before transmission |
| Observed dynamic-label cache | Retains one network-wide ring of up to 4,096 exact incoming and confirmed outgoing label SAL payloads since the current connection, including source/direction and order. `CMQTT LABELS` exposes the bounded observations with network scope and an unverified recipient; a unit-shaped request is a compatibility alias for the same ring. The Toolkit CLI assembles standard text/icons, Unicode, language selection and dynamic bitmaps while reporting incomplete transactions. This is explicitly not eDLT device-cache readback |
| LABEL CLEAR | Sends native standard point-to-point label-cache controls for all keys (`A3 FF 00 27`) or one key 1–8 (`A4 FF 00 66 KEY`) to unit 0–255. It uses one generation-safe exact-once send and waits only for the correlated PCI confirmation; there is no unit ACK or device readback. Native C-Gate treats either confirmation outcome as completion, so success reports command acceptance without claiming cache erasure or persistence |
| LABEL CLEAREDLT | Sends the native KEYGL5 programming control through the shared PCI exactly once, requires both PCI confirmation and the source/tag-correlated unit ACK, and reports acceptance separately from physical erasure or persistence |
| LABEL KFIGET / KFISET | Operates on configured-network application paths for native label-capable applications 48–95, 202 and 203. The application token is only the native `LabelSupportingApplication` class/scope gate; it is not encoded into KFIGET's fixed selector `0x1c`. KFIGET performs three source-acknowledged volatile parameter-`0xFF` writes before IDENTIFY attribute `0x3D`; exactly one source-correlated `8D 3D 80` reply produces eight ordered `300` rows, while zero or multiple replies produce native 524 outcomes. KFISET accepts exactly eight values from 0 through 15, packs them low-nibble then high-nibble, and sends four source-acknowledged parameter-`0xFF` writes, stopping at the first failure. Every write and the GET IDENTIFY request is a generation-safe exact-once send with no transport replay. Both commands use the programming lane and optional LOGIN gate |
| `DO //PROJECT/NETWORK/p/UNIT FactoryDefault` | Sends native `A4 FF 43 B2 B2` exactly once for a database-classified KEYGL5 and reports the 202 receipt separately from post-reset defaults, reboot, address retention and persistence |
| NET PINGU and GET network Units | Actual installation MMI request using cmqttd's negotiated PCI checksum mode; buffers blocks that a CNI forwards before its positive confirmation, accepts only confirmed contiguous coverage of all addresses 0–255, and reports the native sorted `302-Units=` form |
| NET SYNC and cached unit getters | Configured interface routing hint (physically revalidated) or BASIC discovery, complete installation MMI, then confirmed IDENTIFY1/2 probes and bounded IDENTIFY4 collection for every present address; routed and local bare-CAL replies are correlated, silent legacy/error addresses remain present with unknown identity fields, the live cache is replaced atomically, and native getters expose it. Native KEYGL5 metadata additionally requires configured and fresh KEYGL5 types, MMI state exactly one, and exactly one known IDENTIFY4 serial. Only then does cmqttd run the metadata sequence over the captured OEM `09 00` route: parameter `0xFB` length 9 for NUL-terminated `FirmwareVersion`, OEM address 16 length 2 for decimal `Application`/`Application2`, then parameter `0xFA` length 44 for opaque decimal-CSV `WidgetGroups`. Ineligible addresses receive no metadata traffic and stale values are removed. Cached `GET` issues no bus I/O and `Version` remains IDENTIFY2. An address with multiple distinct serials emits `#e# net {network} sync duplicate {address} {serial...}` (sorted); scalar `SerialNumber` stays `""` while the sorted set of distinct serials is retained in the volatile live snapshot. The event is the wire-visible evidence and neither form survives restart. A PCI reconnect or transport loss invalidates an in-flight snapshot before commit, returns 408, and emits no sync-ok |
| NET SYNCNEW | Five complete MMI passes for direct networks. Targeted mode rejects an address already in the model, runs the native three duplicate challenges, and reads IDENTIFY1/2/4; general mode reports new identities and MMI state-3 duplicates. Results update the volatile physical cache and retain native progress/result codes without creating database units |
| NET SET_PROJECT_IDENTIFY | Uppercases and packs the 1–8 character native six-bit value, obtains a fresh complete MMI, and selects the first state-one unit that supplies valid IDENTIFY1 data plus exactly one valid known IDENTIFY4 serial in a complete quiet window. It stores the six bytes at parameter 35 and requires an exact RECALL before returning 200. Duplicate/error MMI states, multiple serial replies, unknown serials, and malformed identities are skipped; a failed or uncertain STORE/readback invalidates any older cached `ProjectName`. The database is not changed |
| NET CHECKUNIT | Active confirmed IDENTIFY4 collection through the native two-second quiet interval, with the native no-unit, single-unit, duplicate-unit and identity-error result forms; `*` expands from a fresh complete MMI |
| NET CLOCKS | Reads physical IDENTIFY16 summaries for the synchronized inventory. Target counts and gateway recovery use decoded `ClockGenEnable` layouts, read-modify-write CAL stores and mandatory readback; native-style per-unit failures remain visible in `120` lines even with final status 200 |
| `SET //PROJECT/NETWORK/p/UNIT Address DESTINATION` | Physical unit readdressing through native C-Gate's protected parameter-`0x20` exchange. The service proves one source identity and an empty destination, obtains the one-use challenge, sends exactly one special address STORE, requires both PCI confirmation and the unit ACK from the destination, moves only the observed physical cache, and leaves the database address unchanged |
| `NET UNRAVELUNIT //PROJECT/NETWORK 255 MATCHDB` | Bounded physical resolution of exactly two known serials colliding at address 255. The service requires two distinct matching database units at unique empty addresses, a direct network, and local PCI parameter 66=`05`; it sends one selected-serial broadcast per unit and accepts success only after per-destination identity checks and a complete final MMI/serial inventory. Other unravel shapes return 502 |
| Unit identification | Source-correlated CAL replies from the physical unit |
| OEM physical memory reads | Volatile 0x41 pointer selection plus segmented RECALL; no EEPROM writes |
| KEYGL5 5.5.00 static strings and label references | Python reader checks physical identity, stable header and static-text CRC. Its network form runs one fresh serial refresh, selects supported records in numeric order, brackets each memory snapshot with physical IDENTIFY4, attaches the inventory identity only when both serials match, reads configurations sequentially and preserves mismatches as per-unit errors |

Retained CBusEdlt classfile bytecode fixes the KEYGL5 order as `0xFB` firmware,
OEM applications, then `0xFA` WidgetGroups. The firmware request is one
OEM-routed `RECALL 0xFB 9`; decoding stops at the first NUL. The application
read sends one OEM selector STORE for address 16 (`41 10 00`) and one
parameter-1 RECALL of two bytes. WidgetGroups is one OEM-routed `RECALL 0xFA
44`. Responses must match source, selector tag or parameter, and exact total
length. No phase is replayed. A missing response faults the programming lane
until reconnect because a late untagged CAL response cannot be safely
attributed. These properties are optional for overall identity synchronization:
`NET SYNC` may still return 200, earlier values confirmed in the same sequence
remain fresh, and the failed value plus every later unrefreshed value is removed
instead of serving stale data. The database `FirmwareVersion` remains
persistent and separate from this volatile physical getter. `CMQTT
CAPABILITIES` reports `"edlt_extended_firmware": true`,
`"edlt_applications": true`, and `"edlt_widget_groups": true`. The 44-byte
mapping is not a query of dynamic-label cache contents, rendering, labels or
persistence.

The optional sequence runs only for MMI state one and one valid known
IDENTIFY4 serial. State two is retained as present but has no verified unique
meaning; state three is a native error flag. Neither state receives these
source-address-only reads, nor do zero-serial or multi-serial addresses. This
prevents one unit's response, or fragments from colliding units, from being
reported as another unit's metadata. The final cache commit is also bound to
the same connected PCI generation; reconnect invalidation wins over an older
in-flight synchronization.

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

`LABEL CLEAREDLT //PROJECT/NETWORK/p/UNIT` accepts a database unit classified
as KEYGL5, sends the native `A4 FF 43 C1 EA` programming control, and never
automatically retries it. A 200 response proves correlated command acceptance;
C-Bus provides no readback that can prove which cached dynamic labels the
firmware erased. Definitive PCI or unit rejection leaves the programming lane
available, while a timeout or transport loss faults it until reconnect so a
late reply cannot be assigned to a later command.

The standard native cache-clear forms are:

```text
LABEL CLEAR //PROJECT/NETWORK/APPLICATION UNIT
LABEL CLEAR //PROJECT/NETWORK/APPLICATION UNIT KEY
```

The application must be label-capable (48–95, 202 or 203), the unit is 0–255,
and the optional key is 1–8. The no-key form sends only `A3 FF 00 27`; the
keyed form sends only `A4 FF 00 66 KEY`. Each is a single confirmed
point-to-point frame and is never replayed. Decompiled native C-Gate considers
both the matching positive (`.`) and negative (`#`) PCI confirmation characters
complete. cmqttd preserves that response contract, then discards its
recipient-unverified observed-label ring because any retained entries may be
stale. No unit acknowledgement or label-cache query follows, so `200 OK`
establishes native command completion only. Native C-Gate publishes no event
from the label-clear handler, so cmqttd does not invent a label-specific success
event. Native's optional high-verbosity command/response audit events are
generic to all commands and are outside this domain-event contract. A missing
confirmation makes the outcome uncertain and faults the programming lane until
reconnect.

`DO //PROJECT/NETWORK/p/UNIT FactoryDefault` accepts a database unit classified
as KEYGL5 and sends the native `A4 FF 43 B2 B2` programming control. It uses the
same strict confirmation and source/tag-correlated ACK policy as `CLEAREDLT` and
never retries automatically. A `202 Done` response proves control acceptance,
not post-reboot defaults, address retention, rendering or power-cycle
persistence. The database record is not rewritten. The observed dynamic-label
ring is cleared because its entries may be stale after reset. Use the guarded
[`cbus-toolkit` workflow](../toolkit-cli/docs/edlt-factory-default.md) to bind the
request to a fresh complete inventory and expected serial.

`NET UNRAVELUNIT //PROJECT/NETWORK 255 MATCHDB` has a deliberately narrower
meaning than the native generic command. It runs only when address 255 contains
exactly two distinct known serials, every other present address contains one
known serial, each serial has one database destination in 2..254, both targets
are independently empty and unique, and the local PCI is outside the move with
parameter 66 equal to `05`. It inventories all present addresses before the
first write, sends each selected-serial broadcast exactly once, verifies the
serial at its destination after each move, then repeats the complete MMI and
serial inventory and checks the PCI option again. The receipt for a broadcast
is treated only as acceptance; the later observations prove the movement.
Timeout, transport loss, conflicting replies, or an incomplete final inventory
produce an uncertain 408 with the number of independently verified moves. The
service does not retry or roll back a selected-serial write. Whole-network
`NET UNRAVEL`, non-255 sources, subsets, operation without `MATCHDB`, occupied
destinations, larger duplicate sets, address cycles, and bridged networks remain
explicit 502 cases.

`NET SET_PROJECT_IDENTIFY //PROJECT/NETWORK NAME` applies the native Java-style
one-to-eight UTF-16-unit check, uppercase fold, and six-bit range validation.
The Toolkit typed wrapper applies the same checks, including Unicode folds
whose uppercase result enters the six-bit repertoire, and emits mK quoting for
spaces, quotes, and backslashes. cmqttd pads the decoded value to eight
characters and stores the resulting six bytes in unit parameter 35 using
C-Gate's fixed transaction tag `0x46`. Native C-Gate accepts the
matching unit ACK; cmqttd then adds a direct RECALL as a deliberate verification
step. Native C-Gate selects the first present unit it can identify; cmqttd also
requires MMI state one and exactly one valid known IDENTIFY4 reply over the
complete bounded quiet window before STORE. Success updates only the volatile
physical snapshot's `ProjectName` field by decoding the verified bytes,
including the native `?`/space alias, with eight-character padding. A failed
or uncertain STORE/readback removes an older cached `ProjectName` so GET cannot
serve stale physical state. It does not rename, select, create, or persist a
project. The separate `NET PROJECT_IDENTIFY`
topology-discovery workflow remains unimplemented. A valid target for another
loaded network fails closed with 502 rather than reporting a local success.

## Live label reads

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-labels --network //PROJECT/254
cbus-toolkit cgate --host 127.0.0.1 --timeout 30 \
  edlt-labels //PROJECT/254/p/5
```

The network form performs exactly one whole-network native serial refresh:
`NET SYNC` followed by `NET CHECKUNIT`. It classifies the fresh records and
selects exact supported KEYGL5 firmware 5.5.00 devices in numeric address order.
Known other families remain visible as `other_units`. Unsupported KEYGL5
firmware, unknown or ambiguous identities, successful device reads and
per-device failures are all retained in the report. Failed reads do not discard
earlier evidence. A selection, device-read or observation failure leaves
`complete=false`; the CLI still writes the JSON report and exits nonzero.
An address nominated by the fresh whole-network MMI but returning no IDENTIFY4
reply remains an unknown identity even though the native CHECKUNIT wording is
`No units detected`. The bounded inventory therefore stays incomplete instead
of excluding a possibly silent physical unit.

For each selected device, the JSON includes the live identity, all 64 static
strings and their widget, page and scene references, verification flags and a
memory SHA-256. Every configuration read checks the physical identity, a stable
header and the static-text CRC. Physical IDENTIFY4 reads bracket each selected
memory snapshot. The fresh inventory identity is
attached only when both physical serials equal its serial. Any initial or
before/after mismatch is retained as a per-unit read error, and no stale
inventory identity or failed snapshot is attached. Device snapshots are
necessarily sequential, so `network_snapshot_atomic=false` and none of the
output describes an atomic network state. The selected-device form keeps its
existing imported database name lookup and reads only that address.

After the network device reads, the CLI issues one `CMQTT LABELS` request for
the network. Standard text and icons, segmented Unicode, language selections,
and complete dynamic bitmap transactions are assembled from that bounded ring
at the inventory's top level. The records cover traffic observed during the
current cmqttd connection across the configured network. Their recipient is
not verified, they are never assigned to one of the selected devices, and they
reset on reconnect. The report therefore keeps `observations_complete=false`
and `device_dynamic_label_cache_readback=false`; C-Bus exposes no evidenced
query that inventories a display's pre-existing dynamic-label cache.

Physical string slots can retain old bytes after a shortened string's null
terminator. The reader reports whether the stored CRC matches the physical
bytes or Toolkit's zero-padded text projection; either must match before static
labels are accepted. The full physical-memory hash still includes those bytes.

The native physical KFI command shapes are:

```text
LABEL KFIGET //PROJECT/NETWORK/APPLICATION UNIT
LABEL KFISET //PROJECT/NETWORK/APPLICATION UNIT KFI1 KFI2 KFI3 KFI4 KFI5 KFI6 KFI7 KFI8
```

The application must be on the configured direct network and must be in the
native label-capable ranges 48–95, 202 or 203. The unit must fit in one byte;
each KFISET value must be 0–15. KFIGET returns `300-kfi1=...` through final
`300 kfi8=...`; KFISET returns `200 OK` only after all four writes are acknowledged.
Zero or multiple valid KFIGET replies return `524 No response.` or
`524 Too many responses.`; setup, write and transport failures use the native
application-scoped 408 envelope. `CMQTT CAPABILITIES` reports
`label_clear: true` and `label_kfi: true`.

The application token implements native `LabelSupportingApplication`
admission and command-address scoping only. It is not placed in the physical KFI
sequence: KFIGET uses the same fixed `0x1c` selector for every admitted
application.

Despite its name, KFIGET is a programming operation: its three volatile
parameter-`0xFF` selector writes happen before the physical read. Do not run it
casually on live hardware. Neither KFI command reads the dynamic-label cache,
and `dynamic_label_device_readback: false` remains authoritative. The parser
does not prove a modeled KEYGL5 unit type, and this path has no live-hardware
acceptance evidence yet.

All KFI parameter-`0xFF` writes and the GET IDENTIFY request are
generation-safe exact-once sends and never enter the automatic retry table. A
lost confirmation makes the transaction uncertain and faults the programming
lane until reconnect. Late confirmations or identical untagged unit ACKs
therefore cannot advance a later selector, and replaying GET cannot manufacture
response multiplicity.

These additional commands are **cmqttd extensions**, not claims about native
C-Gate syntax:

```text
CMQTT CAPABILITIES
CMQTT UNIT //PROJECT/254/p/5
CMQTT LABELS //PROJECT/254
CMQTT LABELS //PROJECT/254/p/5
UNIT IDENTIFY //PROJECT/254/p/5 1
UNIT READMEM //PROJECT/254/p/5 4096 256
```

`CMQTT LABELS` accepts the configured network (including the bare `254` and
`PROJECT/254` forms) or exactly one unit on it (`//PROJECT/254/p/5` — four
path parts, no more). Attribute-suffixed paths, foreign projects, and other
networks are rejected with 400 rather than answered or invented. Its network-wide
observation ring is volatile, resets on reconnect, and is cleared after an
accepted standard or eDLT clear request so pre-clear observations are not
carried across the action.
The unit-shaped request is only a compatibility alias: it returns the same
network ring and records the requested address, `observation_scope="network"`
and `recipient_verified=false`. It does not filter by, or attribute traffic to,
the addressed unit. Neither form infers what a display received before cmqttd
connected or whether a display rendered or persisted a confirmed broadcast.

`READMEM` uses decimal **physical** offsets and accepts 1–4096 bytes per command.
For the evidenced OEM mapping, a unit-spec logical offset of 256 or greater maps
to physical offset `logical - 256`. The CLI assembles smaller blocks. CAL
transactions are serialized, match the source unit and parameter, reject excess
data, and time out. After an incomplete/cancelled programming transaction, a
fresh PCI connection is required before another programming read: late untagged
fragments must not be mistaken for a new result. MQTT traffic is independent.

`PP RESET_TO_DEFAULTS SESSION` is admitted only for a loaded session whose unit
type has an exact decoded specification. It replaces the staged parameters with
that specification's declared `DefaultValue` fields and marks them dirty. The
operation performs no PCI or database write; persistence or hardware transfer
still requires the later explicit save command. Missing and malformed
specifications return 408 and leave the session unchanged.

## Outstanding replacement work

The existing mock dispatches 431 command paths. That is **not** evidence that
all 431 have physical implementations in this service. `CMQTT CAPABILITIES`
returns `full_cgate_compatibility: false`; unimplemented physical operations
return 502. The enumerable gap tracker is the executable capability matrix in
`cbus-cgate::capability_matrix` (pinned by `rust/cbus-cgate/tests/capability_matrix.rs`): 35
physical, 42 local/session, 353 fail-closed 502, and 1 obsolete 400 over the
431 inventoried paths, plus a separately asserted 6-row supplement for
non-inventoried service commands. Full replacement still requires:

- Physical PP multi-range failure recovery, power-loss behavior, and hardware write acceptance for
  every programming method and unit family. LOAD has full decoded-catalogue
  layout coverage plus live KEYGL5 acceptance; SAVE audits every well-formed
  writable catalogue default and has fake-PCI direct/page-aware/OEM/GOC
  write-readback acceptance. STORE failures report `after N confirmed write(s)`
  with the count of independently acknowledged ranges, and Save-to-NVM failures
  carry the same confirmed-count evidence. Factory/special parameters clear
  silently without a write while tag-filtered parameters stay dirty for a later
  matching-tags SAVE; a bare 200 covers the tag-selected subset only.
- Bridged-network synchronization, general serial-address commissioning,
  topology-wide `NET PROJECT_IDENTIFY` discovery, and the remaining
  commissioning state transitions. The distinct physical
  `NET SET_PROJECT_IDENTIFY` parameter-35 write is implemented with readback.
  Direct-network `NET SYNCNEW` is implemented in both native forms: five
  merged installation MMI passes, the targeted unit form's three exact CAL
  Unlock duplicate challenges, IDENTIFY1/2/4 population of the volatile live
  cache, and native `120`/`303`/`408` response envelopes. It does not add the
  discovered unit to the persistent project database.
  The bounded direct-network two-serial collision at address 255 is implemented
  by `NET UNRAVELUNIT ... 255 MATCHDB`, including full inventory and independent
  verification. Whole-network `NET UNRAVEL`, other UNRAVELUNIT shapes,
  occupied-address displacement, larger duplicate sets, cycles, and bridges
  remain 502. `DO ... UNRAVEL` also remains 502.
  Direct-network `NET PINGU`, `NET SYNC` identity population, `DO ... SYNC`,
  duplicate-aware `NET CHECKUNIT`, and guarded single-unit physical
  readdressing are implemented. `DO` lighting methods also use the physical
  lighting backend; `DO ... UNRAVEL` is rejected until unravel is implemented.
  Direct-network clock inspection, target-count changes and gateway recovery are
  implemented for units whose decoded schema exposes a supported direct
  `ClockGenEnable` field; electrical arbitration remains outside software
  verification.
- Device-resident scene triggering beyond PP table programming, a physical
  eDLT operation that can query pre-existing dynamic-label cache contents, and
  specialist application families such as HVAC, audio and security.
- Native repository/archive/import/export formats, document commands,
  complete server configuration/access/TLS, firmware and deployment workflows.
  C-Gate TLS is transport-only: no TLS client authentication is performed,
  no client certificates are requested, and ACCESS/ACCESS_CONTROL
  paths remain fail-closed 502. (Command-layer access control is only the
  separate opt-in LOGIN gate described above.)
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
vendor-invalid rejection, confirmed multi-frame delivery, exact observed-cache
retention for sent and received SAL, cache invalidation after clear, and the
shared PCI connection.
Transport tests pin the eDLT clear control bytes, positive PCI and unit replies,
source filtering, MQTT fanout and definitive NAK recovery. The real-daemon case
verifies exact-once delivery through the same PCI connection.
`rust/testdata/vectors/kfi.jsonl` pins the three-selector-write plus IDENTIFY
sequence, the four-write SET sequence, exact native bytes and low/high nibble
ordering. `rust/cbus-vector-check/src/main.rs` checks that corpus directly;
`rust/cbus-golden-tests/build.rs` generates the corresponding cases consumed by
`rust/cbus-golden-tests/tests/golden_vectors.rs` and validated by
`rust/cbus-golden-tests/src/lib.rs`. `cbus-transport` and
`rust/cbus-cgate/src/service/tests.rs` cover source-correlated confirmations
and unit ACKs, NAK and timeout handling, first-failure abort, exact reply
validation, zero/multiple-reply 524 outcomes, application/value bounds and the
eight-row GET envelope. Transport tests also pin the generation-safe exact-once
path: lost confirmations cause no write or IDENTIFY replay, fault the
programming lane and cannot reuse a late confirmation or ACK for another
selector. `rust/cmqttd/tests/system_cgate.rs` exercises both
commands through the shared PCI connection. This is scripted acceptance, not
live KFI hardware acceptance.
Selected-serial transport tests pin the exact SRCHK request, positive
confirmation plus source/route/serial-correlated receipt, the quiet interval,
zero replay, interleaved lighting fanout, definite rejection recovery, and
ambiguous-reply lane faulting. A paused-time service test exercises the complete
two-unit MATCHDB inventory, move and final verification sequence through a real
`PciClient` over a duplex fake PCI. A real-daemon system test also drives that
workflow through the TCP C-Gate endpoint, checks both exact selected-serial
requests are sent once, and verifies that C-Gate and MQTT keep one shared PCI
connection throughout the operation.
The public `cbus-transport::inventory` collector combines complete contiguous
MMI coverage with bounded IDENTIFY1/2/4 probes, preserves every duplicate serial
reply and its raw bytes, and marks silent or malformed unit observations partial.
Its duplex integration tests cover duplicate identities, silent units, MMI
rejection, and addressed MMI blocks.
The real-daemon scene case records an observed level, verifies durable storage,
plays it as the exact confirmed zero-time ramp, and verifies that acknowledgement
does not fabricate a level observation.
`cbus-cgate` service tests cover durable reload, corrupt-file preservation,
rollback, session ownership, unsupported hardware rejection, fragmented command
input during events, native-shaped command-session enumeration/tagging,
`EVENTS` alias state, reply-before-close `QUIT`/`EXIT`, disconnect cleanup,
specification-backed staged reset success/failure/ownership/persistence,
schema layout decoding and input bounds. The retained owned C-Gate 3.4.0.2001
[session capture](../toolkit-cli/research/experiments/2026-09-25/cgate-session-native-acceptance.json)
pins those statuses, envelopes, aliases and closure semantics on disposable
loopback listeners with no project or physical network configured.
The decoded vendor catalogue is optionally audited through `CBUS_UNITSPEC_DIR`.
The real cmqttd system test performs physical PP LOAD and SAVE against a scripted
PCI, checks standard and OEM values, dirty/tag selection, read-modify-write
encoding, acknowledgements, readback, and the exact C-Bus 3 NVM commit sequence,
and verifies that C-Gate and MQTT retain one PCI connection while lighting events
continue through the same transport. The same test pins `DO` lighting methods to
their physical SAL packets, exercises `DO ... SYNC`, and verifies that unsupported
`DO ... UNRAVEL` cannot report simulated success. It also pins source-correlated
IDENTIFY16 clock summaries and their native `120` response fields while MQTT
shares the PCI. A separate real-daemon test verifies guarded physical
readdressing, exact-once STORE transmission, database/physical layer separation,
and MQTT event delivery on that same PCI during the move.
`toolkit-cli/tests/test_cmqtt.py` tests synthetic eDLT decoding, static-reference
coverage and selected-device read contracts.
`toolkit-cli/tests/test_cmqtt_inventory.py` pins one fresh network refresh,
numeric device ordering, exact supported-profile selection, one network
observation query, partial-evidence retention and CLI scope parsing.
`rust/cbus-cgate/src/service/tests.rs` and the real-daemon system test pin the
network provenance fields and prove that unit-shaped `CMQTT LABELS` requests
return the same network ring without claiming a verified recipient.
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
After the physical `DO` backend was added, the deployed service also changed the
garage relay from its observed level 255 to 0 with `DO ... OFF`, observed the
result from the bus, restored it with `DO ... ON`, and observed level 255 again.
Both commands returned native `202 Done: object` responses while MQTT remained
connected and the container remained restart-free.
The deployed service also completed a live three-block PINGU observation,
returned the physical address list, and exposed the same list through `GET Units`.
It then completed a whole-network `NET SYNC`, preserved the synchronized snapshot
across separate C-Gate reads, returned live type, version and serial fields, and
reported a selected address as a single unit through `NET CHECKUNIT`. The Toolkit
CLI's `cgate serials refresh` workflow completed against the same deployment with
the selected unit present, unique and healthy while MQTT remained connected.
These checks cover that device/profile and relay path; they do not establish
complete physical C-Gate acceptance. Site reports are private and excluded from Git.

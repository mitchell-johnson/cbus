# C-Bus Toolkit CLI and Rust tools

Manage Clipsal/Schneider C-Bus projects from the terminal and connect C-Bus lighting to MQTT and Home Assistant.

This repository has two main applications:

- **[`cbus-toolkit`](toolkit-cli/README.md)** — a Python CLI for Toolkit-style project editing, commissioning, unit configuration, scenes, and diagnostics. It works with project files offline and connects to C-Gate or a CNI for online operations. JSON output makes it usable from scripts and AI agents.
- **[`cmqttd`](docs/configuration.md)** — a Rust daemon providing MQTT/Home Assistant support and an embedded C-Gate service over one shared C-Bus connection. It runs without Schneider C-Gate, Windows, or the Toolkit application. Its [C-Gate replacement status](docs/cmqttd-cgate.md) distinguishes implemented hardware operations from outstanding compatibility work.

The Rust workspace also provides protocol tools, a PCI simulator, and a C-Gate compatibility server for development and testing. Install the application you need; the Python CLI and Rust bridge can be used independently.

## Which program do I need?

| I want to… | Use |
| --- | --- |
| Create, inspect, edit, validate, or export Toolkit XML/CBZ projects | `cbus-toolkit project` |
| Manage native C-Gate projects, configure supported units, control groups, or commission a network | `cbus-toolkit cgate` |
| Plan supported keypad, sensor, eDLT, scene, or unit-conversion settings offline | `cbus-toolkit keys`, `sensors`, `edlt`, `scene`, and `unit-conversion` |
| Query a CNI directly or inspect routed PCI messages | `cbus-toolkit pci` and `pci-route` |
| Discover CNI2/Wiser interfaces without opening them | `cbus-toolkit interface discover-cni` or `cbus-tools cni-discover` |
| Connect C-Bus lights to MQTT and Home Assistant | `cmqttd` |
| Inventory live eDLT labels without Windows, while MQTT keeps running | `cbus-toolkit cgate edlt-labels --network //PROJECT/NETWORK`, connected to `cmqttd` |
| Decode a frame, export project labels, or interrogate a unit | `cbus-tools` |
| Test a C-Gate client without a vendor server or hardware | `cgate-mock` |
| Test PCI/CNI protocol traffic without hardware | `cbus-simulator` |

## Toolkit CLI

### Install

Requires **Python 3.13 or newer**. From the repository root, on macOS or Linux:

```sh
python3.13 -m venv toolkit-cli/.venv
toolkit-cli/.venv/bin/python -m pip install -e ./toolkit-cli
source toolkit-cli/.venv/bin/activate
cbus-toolkit --help
```

On Windows, use `py -3.13 -m venv toolkit-cli/.venv`, then run `toolkit-cli\.venv\Scripts\python.exe -m pip install -e ./toolkit-cli` and `toolkit-cli\.venv\Scripts\cbus-toolkit.exe --help`.

The base package has no external Python dependencies. Optional serial and USB features have separate extras; see the [Toolkit CLI guide](toolkit-cli/README.md).

### Try it without hardware

Create a project, add a network and lighting group, then inspect it:

```sh
cbus-toolkit project new demo.cbz --name DEMO
cbus-toolkit project add demo.cbz --kind network --address 254 --name Local
cbus-toolkit project add demo.cbz --kind application --parent /254 --address 56 --name Lighting
cbus-toolkit project add demo.cbz --kind group --parent /254/56 --address 1 --name Lounge
cbus-toolkit project inspect demo.cbz
cbus-toolkit project export demo.cbz demo.xml --format xml
```

Project editing preserves unknown XML and opaque programming fields. Use `--output` on an edit to write a separate copy. Native C-Gate 3 SQLite projects are managed through `cbus-toolkit cgate project` instead of the offline XML/CBZ editor.

### Connect to C-Gate

Point the CLI at your C-Gate server. This example reads the project list:

```sh
cbus-toolkit cgate --host 192.168.1.20 --port 20023 project list
```

Replace the example address and port with your server's values. Use `cbus-toolkit cgate --help` for project, network, database, unit, addressing, scene, and control commands. The transport supports verified TLS and client certificates. Advanced parameter workflows may require vendor unit specifications; those files are supplied separately.

For an exact C-Gate command, use `cbus-toolkit cgate exec 'PROJECT LIST'`. For a file of commands that must share one session, use `cbus-toolkit cgate run commands.txt`. Add the same connection options as above; command batches stop at the first failure.

Results are JSON on stdout; operation errors are JSON on stderr and return a nonzero exit status. Put `--compact` before the command for single-line JSON. Event monitoring emits JSON lines.

To find a CNI2 or Wiser endpoint first, run `cbus-toolkit interface
discover-cni`. It sends one bounded IPv4 UDP query and reports the source
address plus advertised TCP port without opening the interface. A zero-reply
result does not prove that no interface exists. The Rust tools expose the same
wire codec and JSON boundary as `cbus-tools cni-discover`; see the [discovery
contract](toolkit-cli/docs/cni-discovery.md).

### Toolkit compatibility and current status

The CLI targets **C-Bus Toolkit 1.18.0.2754 and C-Gate 3.4.0.2001**, with full Toolkit functionality as the goal. Implemented workflows include offline project editing, native project management, supported unit programming and addressing, keypad presets, scenes, CGL exchange, and substantial eDLT configuration. Device and firmware support is documented per workflow.

For the bounded KEYGL5 5.5.00 parent transaction, the CLI composes 11 admitted
configurable non-MRA widget panels—Measurement, Lighting, Enable, Fan,
HVAC, Multi Level, Room Courtesy, Scene, Shutter, Time/Date and Timer—and the
activation, General, Display, Standby, Colours, Navigation, Quick Status and
Page Control settings panels. It validates ordered editability, complete byte
ownership and application/group/dynamic-label dependencies before one retained
save. The CLI can derive those application/group/scene-level/dynamic-variant/
static-label facts from one exact native project snapshot and plan missing
database metadata before the retained multi-edit.
See the [automatic parent metadata contract](toolkit-cli/docs/edlt-parent-metadata.md)
for the closed-project guards and the non-atomic PP/project save boundary.
The retained SceneManager can also derive complete existing application/group
lists and safe Trigger action text directly from the same exact project
snapshot. See [automatic SceneManager metadata](toolkit-cli/docs/edlt-scene-metadata.md);
it plans and can create a missing Trigger Control application, exact trigger
groups, and exact action levels with a retained project backup, then records
the separate PP and project-save boundaries. Interactive blank Add dialogs,
image-dependent labels, and complete form binding remain outside that bounded
workflow. MRA parent composition, Applications/Corridor cache dialogs,
Blank/Reset, SceneManager parent binding, original full-form execution and
physical acceptance remain outstanding.

**Full Toolkit parity is not complete.** The feature ledger currently records 38 areas: 17 implemented, 19 in progress, and 2 pending. These categories are not a percentage of Toolkit functionality. Check the current machine-readable status with:

```sh
cbus-toolkit coverage --require-complete
```

This intentionally returns exit status `1` while parity remains unfinished. The [completed functions and outstanding work](toolkit-cli/docs/implementation-status.md) describe supported profiles, test evidence, and remaining work. The [Toolkit CLI guide](toolkit-cli/README.md) contains detailed command examples.

## MQTT and Home Assistant bridge

Build the Rust tools with a current stable Rust toolchain, from the repository root:

```sh
cargo build --manifest-path rust/Cargo.toml --release --workspace
```

The binaries are written to `rust/target/release/`. Run the bridge against your MQTT broker and CNI, replacing these example addresses:

```sh
rust/target/release/cmqttd \
  --broker-address 192.168.1.20 \
  --broker-disable-tls \
  --tcp 192.168.1.10:10001
```

`cmqttd` publishes Home Assistant discovery and lighting state, and forwards MQTT light commands to C-Bus. `/set` commands remain FIFO until each command receives its correlated PCI confirmation. After positive confirmation, cmqttd publishes the compatibility state echo only when no newer physical observation for that application/group arrived while delivery was pending; observations for other groups do not suppress it. The echo's `cbus_source_addr: null` records requested state. Every confirmed command still queues a physical level report request and publishes its non-retained delivery/readback receipt on `cmqttd/cbus/command_result`; a source-bearing bus event or status report is the physical observation. The retained `homeassistant/binary_sensor/cbus_cmqttd/state` topic changes to `OFF` during C-Bus transport loss and `ON` after reconnect. Add `--project-file house.cbz` for names from your Toolkit project and `--cbus-network 'Main Network'` to select a network. TLS is enabled by default; omit `--broker-disable-tls` when using a TLS broker. Serial and ESP32 bridge connections are also supported.

For Docker, copy `.env.example` to `.env`, configure your broker and C-Bus endpoint, then run `docker compose up --build`. See [bridge configuration](docs/configuration.md) for authentication, certificates, project files, time synchronization, and status updates.

### Use cmqttd as the CLI's server

Enable `--cgate-bind 127.0.0.1:20023` together with `--project-file house.cbz`. The daemon imports your project into a persistent database and serves the Toolkit CLI while continuing MQTT on the same PCI/CNI connection. Docker Compose enables this listener and stores the database in the `cmqttd_data` volume.

```sh
cbus-toolkit cgate --host 127.0.0.1 project list
cbus-toolkit cgate --host 127.0.0.1 exec 'CMQTT CAPABILITIES'
cbus-toolkit cgate --host 127.0.0.1 exec 'CONFIG GET *'
cbus-toolkit cgate --host 127.0.0.1 exec 'CONFIG INFO sync-time'
cbus-toolkit cgate --host 127.0.0.1 exec 'FILE'
cbus-toolkit cgate --host 127.0.0.1 exec 'FILE DIR'
cbus-toolkit cgate --host 127.0.0.1 exec 'FILE SHA256 exports/project.cgl'
cbus-toolkit cgate --host 127.0.0.1 exec 'PORT ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'PORT LIST'
cbus-toolkit cgate --host 127.0.0.1 exec 'PORT IFLIST'
cbus-toolkit cgate --host 127.0.0.1 --timeout 15 exec 'PORT CNISCAN2 192.0.2.10 192.0.2.255 FAST'
cbus-toolkit cgate --host 127.0.0.1 --timeout 30 exec 'PORT PROBE cni 192.0.2.20:10001'
cbus-toolkit cgate --host 127.0.0.1 exec 'LOGIN'
cbus-toolkit cgate --host 127.0.0.1 exec 'ACCESS LIST'
cbus-toolkit cgate --host 127.0.0.1 exec 'ACCESS'
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 network sync-new //PROJECT/254 --unit 6
cbus-toolkit cgate --host 127.0.0.1 network set-project //PROJECT/254 PROJECT
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 edlt-labels --network //PROJECT/254
cbus-toolkit cgate --host 127.0.0.1 edlt-labels //PROJECT/254/p/5
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 edlt-widget-groups //PROJECT/254/p/5
cbus-toolkit cgate --host 127.0.0.1 label cache-clear //PROJECT/254/56 5 --key 2
cbus-toolkit cgate --host 127.0.0.1 exec 'AIRCON ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'AIRCON SET_ZONE_HVAC_MODE //PROJECT/254/172 1 0,1 3 0 1 0 1 255 230 64'
cbus-toolkit cgate --host 127.0.0.1 exec 'AUDIO ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'AUDIO REQUEST_CURRENT_FEED //PROJECT/254/205 1 2'
cbus-toolkit cgate --host 127.0.0.1 exec 'AUDIO SET_FEED //PROJECT/254/205 1 2 4 0'
cbus-toolkit cgate --host 127.0.0.1 exec 'SECURITY ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'SECURITY STATUS_REQUEST //PROJECT/254/208 1'
cbus-toolkit cgate --host 127.0.0.1 exec 'SECURITY ARM //PROJECT/254/208 away'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEDIATRANSPORT ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEDIATRANSPORT STATUS_REQUEST //PROJECT/254/192 2'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEDIATRANSPORT PLAY //PROJECT/254/192 2'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEASUREMENT ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEASUREMENT DATA //PROJECT/254/228/1/1 10234 -2 2'
cbus-toolkit cgate --host 127.0.0.1 exec 'TELEPHONY ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'TELEPHONY RECALL_LAST_NUMBER_REQUEST //PROJECT/254/224 out'
cbus-toolkit cgate --host 127.0.0.1 exec 'TELEPHONY DIVERT //PROJECT/254/224 021234567'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI KNOWN EXEC //PROJECT/254/p/20 A'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI EMERGENCY STATUS EXEC //PROJECT/254/p/20 A 3'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI ERROR_REPORTING STORE_OPTION //PROJECT/254/p/20'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI GATEWAY PAGED_RECALL //PROJECT/254/p/20 521 1'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI SESSION NEW commissioning'
```

The embedded endpoint implements the complete maintained C-Gate 3.4 CONFIG,
FILE, and ACCESS command families. CONFIG provides help, GET, INFO, SET, scoped
OBGET/OBSET/OBRESET and LOAD/SAVE over durable compatibility state. FILE
provides DIR/LS, recursive MKDIR, DELETE, SHA256, base64 DOWNLOAD and native
here-document UPLOAD, including the native `.0` replacement backup. FILE data
lives in a sandboxed virtual root inside cmqttd's atomic JSON repository; FILE
paths never access the host filesystem and `%PROJECT%` is a virtual namespace.
Mutating FILE commands require LOGIN when the optional command gate is armed.
ACCESS provides ADD/DELETE/LIST/LOAD/SAVE, native role filtering and
username/password LOGIN over durable rows. User passwords are digest-only and
LIST prints `<redacted>`. LOAD/SAVE use sandboxed repository snapshots rather
than host files; invalid hostnames and missing snapshots fail without changing
the active policy. Fresh and pre-ACCESS repositories preserve Docker-published
CLI access until an operator changes interface/remote policy. Thereafter an
unmatched peer receives 421, or a LOGIN/LOGOUT-only recovery session when the optional
token is configured. Mutating ACCESS commands require either that recovery-token
LOGIN or a Clipsal/Max ACCESS-user LOGIN when the gate is armed.
Query `CMQTT CAPABILITIES` for these explicit boundaries and see the
[C-Gate replacement guide](docs/cmqttd-cgate.md) for wire examples,
persistence, native evidence, and the remaining compatibility gaps.

It also implements the complete maintained C-Gate 3.4 `PORT` command family.
`PORT LIST` and `PORT IFLIST` enumerate the cmqttd host, `CNISCAN` uses the
legacy UDP-30718 exchange, and `CNISCAN2` follows that with the native CNI2
CCP query on UDP 20050. `PORT PROBE` opens a separate temporary connection,
sends the retained DC1/`@2104` echo-and-serial exchange, reports the returned
PCI serial text, and always closes it. It refuses cmqttd's active endpoint with
431 so MQTT is not interrupted. C-Gate 3.4 automatically updates
serial devices, so `PORT REFRESH` retains its observed deterministic 408 reply.
When LOGIN is configured, scans, probe, and refresh require authentication;
help and local enumeration stay readable.

Replace the example project, network and unit with your actual addresses. The
network form performs one fresh `NET SYNC` plus `NET CHECKUNIT` serial refresh,
then reads every exact supported KEYGL5 5.5.00 record in numeric address order.
It brackets each selected memory snapshot with physical IDENTIFY4 reads and
attaches the fresh inventory identity only when both physical serials match the
fresh inventory serial. A mismatch remains a per-device read error; it never
attaches a stale inventory identity to the snapshot.
It reports unsupported, unknown or ambiguous identities and per-device read
failures alongside any successful static configurations. An incomplete report
is still emitted and the command exits nonzero.

Each selected device read verifies its live identity, stable configuration
header and static-text CRC, and includes the 64 stored strings plus widget,
page and scene references. Those physical snapshots are sequential, so the
inventory is not an atomic view of the network. After the device reads, the
CLI requests `CMQTT LABELS` once for the network. The resulting dynamic-label
observations are network-wide, transient, recipient-unverified and kept only at
the report's top level; they are never assigned to a device. A unit-shaped
`CMQTT LABELS` request is only a compatibility alias for that same network ring.
Physical dynamic-label cache readback remains unavailable, so the observation
view is always marked incomplete and `device_readback` remains false.

The embedded service also runs physical `NET CLOCKS` inspection, target-count
configuration, and gateway recovery after `NET SYNC`, using source-correlated
status reads and schema-backed writes with mandatory readback. It retains a
bounded current-connection history of incoming and confirmed outgoing dynamic
label traffic for Toolkit CLI inspection. Command connections also implement
native-shaped `SESSION_ID` enumeration and one-shot tags, the `EVENTS` alias,
and `QUIT`/`EXIT` reply-before-close behavior. It also exposes the exact
four-channel `EVENT_CHANNEL` catalogue with connection-local SUB/UNSUB state,
session-owned advisory `LOCK`/`UNLOCK`, the native `PROJECT` help and
`PROJECT DIRFULL` repository view, and the three read-only `DBGETJSON` NAC
projections. cmqttd does not retain vendor NAC object-list definitions, so its
object and routing JSON are explicitly empty; TAGMAP covers the durable local
network, application, group and level tags. Query `CMQTT CAPABILITIES` before
depending on that bounded JSON scope.

Programming sessions also implement specification-backed
`PP RESET_TO_DEFAULTS`: declared defaults replace only the staged session
values, with no database or PCI write until the caller explicitly saves.
Missing or malformed unit specifications fail unchanged.

Local C-Gate compatibility now includes PP catalogue/spec queries, lock and
session inventory/cancellation, staged raw-memory get/set/debug,
`LOAD_FROM_FILE`, and runtime PROGRAMMER queue creation, inspection and
cancellation. Catalogue files are confined to `--cgate-unitspec`, and these
administrative operations send no PCI traffic. Queued execution and patching
remain honest boundaries: `PROGRAMMER TRIGGER ... START` and `PP WRITE_PATCH`
return 502 without changing state or claiming a device operation.

The embedded service also supports native physical `LABEL KFIGET` and
`LABEL KFISET`. The application token admits only a native
`LabelSupportingApplication`; it is a scope/class gate and is not encoded into
KFIGET's fixed selector `0x1c`. KFIGET first sends three volatile
parameter-`0xFF` writes, so it is a programming operation rather than a
dynamic-label cache read. Every KFI write and the GET IDENTIFY request is sent
exactly once with generation-safe confirmation handling and no transport
replay. A lost confirmation faults the programming lane until reconnect.

Native `LABEL CLEAR //PROJECT/NETWORK/APPLICATION UNIT [KEY]` is also
hardware-backed. The Toolkit CLI exposes it as `cgate label cache-clear` so it
cannot be confused with `cgate label clear`, which broadcasts an empty group
label, or `cgate edlt-label-clear`, which runs the guarded KEYGL5
`CLEAREDLT` workflow. The no-key command clears all label keys with native CAL
`A3 FF 00 27`; a key from 1 through 8 uses `A4 FF 00 66 KEY`. cmqttd sends the
point-to-point command exactly once and waits only for its correlated PCI
confirmation. Native C-Gate treats either confirmation outcome as command
completion, and there is no unit ACK or cache readback, so a 200 response does
not prove erasure, rendering or persistence.

`NET SYNC` also populates the native KEYGL5 synchronization properties. A unit
must have non-error present MMI state one or two, exactly one raw IDENTIFY4
reply carrying a known serial, and KEYGL5 types
in both the configured database and fresh physical IDENTIFY1. Eligible units
follow retained C-Gate classfile order over the OEM `09 00` route: parameter
`0xFB` length 9 supplies the NUL-terminated `FirmwareVersion`, memory address
16 length 2 supplies decimal `Application` and `Application2`, and parameter
`0xFA` length 44 supplies `WidgetGroups` as opaque comma-separated decimal
bytes. `Version` remains the separate IDENTIFY2 value. Read the cached values
with `GET //PROJECT/NETWORK/p/UNIT PROPERTY`; these GETs issue no new bus I/O.
Repeated identical known replies and mixed known/unknown replies do not qualify
for metadata reads, even though the live serial cache keeps its established
distinct-known-serial representation.
The synchronization leaves persistent configuration unchanged, but the OEM
application read writes a volatile address-16 selector on the unit before its
recall. The typed `edlt-widget-groups` command reports that distinction in its
JSON evidence.
Each physical request is exact-once and source/parameter/length correlated. An
optional failure does not fail an otherwise valid identity sync, but clears
that value and every later unrefreshed value and faults the programming lane
until reconnect. Ambiguous addresses receive no metadata traffic and expose no
stale values. A reconnect or transport loss invalidates an in-flight snapshot,
returns 408, and emits no sync-ok. These properties are separate from the unsupported dynamic
label-cache query.

`AIRCON ?` lists the complete C-Gate 3.4 AIRCON command family. The eleven
commands use application 172 on the configured direct network. With
`--cgate-auth-file`, the ten state-changing commands require `LOGIN`; `REFRESH`
remains open. A 200 response means the PCI confirmed the broadcast. It does not
establish controller acceptance or the resulting HVAC state. Incoming AIRCON
reports are available to C-Gate event clients; cmqttd does not expose an MQTT
HVAC state schema.

`AUDIO ?` lists all 19 maintained C-Gate 3.4 Audio commands for application
205. Both multiplexer/zone and `Z function` forms use the retained wire
encoding, including native low-bit transformations and the native 0..7 error
code range. Read/report requests remain open under the optional LOGIN gate;
amplifier, feed, ramp, mute and common-control operations require `LOGIN` when
the gate is armed. Success requires a correlated confirmation on the current
PCI generation. Routed Audio writes remain fail closed because no retained
routed-write capture exists. Incoming Audio command traffic reaches C-Gate
event clients. C-Gate 3.4 advertises Audio `label` and `load_icon` events, but
the retained build silently drops valid standard frames because of a decoder
length bug; cmqttd decodes the intended retained A0 layout as an explicit
repair and does not claim byte-for-byte native event behavior for those two
events. No MQTT Audio state schema is invented.

`SECURITY ?` lists all seven maintained C-Gate 3.4 Security commands for
application 208 on the configured direct network. `STATUS_REQUEST` and
`REQUEST_ZONE_NAME` remain open under the optional LOGIN gate; arm, tamper,
alarm, keypad and display-message control require `LOGIN` when the gate is
armed. A 200 response means the shared PCI confirmed the broadcast; it does
not establish alarm-panel acceptance or resulting state. Incoming Security
events, zone names and packed status reports reach C-Gate event clients.
cmqttd publishes no invented MQTT alarm-panel state.

`MEASUREMENT ?` exposes the complete maintained C-Gate 3.4 Measurement
family. `MEASUREMENT DATA` sends the exact application-228 device/channel
sample and waits for PCI confirmation. Incoming samples reach C-Gate event
clients and populate native-shaped application/device/channel GET properties;
cmqttd does not publish them as MQTT state.

`MEDIATRANSPORT ?` lists all 21 maintained C-Gate 3.4 Media Transport
commands and reports for application 192 on the configured direct network.
Playback, navigation, enumeration, status, track totals and fragmented names
use exact native SAL, one send, and positive PCI confirmation. With
`--cgate-auth-file`, status and enumeration requests remain open while controls
and report injection require `LOGIN`. The typed decoder and canonical JSON
preserve raw name bytes, and incoming messages reach C-Gate event clients;
cmqttd publishes no invented MQTT player state. A 200 response does not prove
media-device acceptance or resulting state.

`TELEPHONY ?` exposes all five maintained C-Gate 3.4 Telephony commands for
application 224: clear diversion, divert, secondary-outlet isolation,
last-number recall, and incoming-call rejection. Exact native token grammar,
including the captured non-ASCII diversion defect, is retained. Incoming
line, call, ringing, number and Internet-request events reach C-Gate event
clients. A 200 proves active-generation PCI-confirmed broadcast delivery; it
does not prove telephone acceptance, call state or persistence. cmqttd does
not invent an MQTT Telephony state schema.

`DALI ?` exposes all 128 maintained DALI paths. For a configured `SYS_DAL2`
gateway, 103 leaves have physical backends: 48 core, 14 emergency, and 41
specialized gateway, error-reporting, measurement, or session operations. The
remaining 25 paths are local: six exact retained group-help roots and 19
catalogue, gateway-view, and commissioning-session operations. Physical work
uses the shared PCI, source or programming-reply correlation, reconnect
generation guards, and no replay after an outcome-uncertain write. Paged
stores are read back before success; saved sessions use cmqttd's atomic JSON
repository. `EXT_ONLY` session extraction/deployment is physical. The retained
typed `DALI_ONLY`/`FULL` plans and related extraction selectors fail before I/O
until their full model codec is evidenced, so `dali_full_compatibility` remains
false. There is no invented DALI MQTT state contract. See the
[DALI command guide](docs/cgate-dali.md).

**Full C-Gate replacement is the target, not the current completion claim.**
Hardware-backed lighting, all eleven maintained AIRCON/HVAC commands, all 19 maintained
AUDIO commands, all seven maintained SECURITY commands, the complete maintained
MEASUREMENT and TELEPHONY families, and all 21 maintained MEDIATRANSPORT commands
and reports on the configured direct network are implemented. All 128 retained
DALI command paths dispatch: 103 physical leaves and 25 local/help paths. The
typed-device selectors inside SESSION EXTRACT/DEPLOY remain a documented
fail-before-I/O boundary beyond the physical `EXT_ONLY` plan. The complete
maintained `PORT` discovery, host enumeration, refresh, and probe family is
implemented independently of the shared MQTT connection. The same endpoint
implements C-Gate ACCESS ADD/DELETE/LIST/LOAD/SAVE with durable digest-only
credentials and sandboxed snapshots, the complete CONFIG and FILE families
over local durable compatibility state, local project/NAC JSON inventory,
deploy-queue event-channel subscriptions and session-owned advisory locks,
and C-Gate
`DO` object methods for lighting, direct and bridged read-only synchronization,
guarded KEYGL5 FactoryDefault, persistent named-scene record/playback, Trigger Control,
Enable Control, clock, Temperature Broadcast, native text/icon/Unicode/dynamic-bitmap
label commands, standard label-cache clear, eDLT dynamic-label clear, complete-coverage
`NET PINGU`, identity-populating `NET SYNC`, five-pass general `NET SYNCNEW`,
shared-interface read-only `NET PROJECT_IDENTIFY`, verified physical `NET SET_PROJECT_IDENTIFY` parameter-35 writes,
duplicate-aware `NET CHECKUNIT`, guarded physical unit readdressing, the bounded two-unit
`NET UNRAVELUNIT ... 255 MATCHDB` workflow, unit identity, schema-driven physical `PP LOAD`, verified physical
`PP SAVE` for `direct`, `edlt`, `paged`, `ncc`, `giu`,
`sgiu`, `dali`, `goc`, `gocbyt`, and `goc2` parameters,
extended-memory access, live observations, and persistent database operations while MQTT
continues on the same CNI connection. `DBNETWORKPATH` resolves native compact and OID
routes, and `NET PINGU`, `NET SYNC`, general `NET SYNCNEW`, `DO ... SYNC`, and `NET CHECKUNIT`
support source routes through one to six bridges with strict Reply Network correlation
and per-network volatile caches. Direct targeted `NET SYNCNEW` also runs the three native
duplicate challenges. AIRCON, AUDIO, SECURITY, MEASUREMENT, TELEPHONY and
MEDIATRANSPORT success means the broadcast received a positive PCI confirmation;
physical controller, alarm-panel, measurement-device, telephone-device or media-device
acceptance and resulting state have not been validated. Routed AIRCON, AUDIO, SECURITY,
MEASUREMENT, TELEPHONY and MEDIATRANSPORT, routed
writes, routed OEM eDLT metadata, routed targeted `SYNCNEW`, and bridged commissioning
mutations remain unavailable. When `--cgate-auth-file` is configured, log in before
an AIRCON, AUDIO, SECURITY or Telephony mutation, `MEASUREMENT DATA`, or gated
`MEDIATRANSPORT` traffic; the Telephony last-number request remains open. `NET SYNCNEW` and
`NET SET_PROJECT_IDENTIFY` update the volatile physical cache and do not create persistent project
units. The unravel backend requires exactly two known serials at address 255, two unique
empty database destinations, and a direct network; broader unravel cases remain
unavailable. FactoryDefault acceptance proves the one-shot unit ACK but does not yet
prove post-reset readback, reboot, retained address or persistence. Scene recording
captures observed lighting levels on the configured network; playback sends confirmed
zero-time ramps and requests physical readback. Direct and page-aware lock-protected
fields and unit readdressing use the native one-use challenge phase; GIU uses native
halt/store/resume, GOC-family programming uses its address-prefixed
parameter-`0xFF` transport, and changed C-Bus 3 saves complete the native
Save-to-NVM EXECUTE/POLL sequence before reporting success. Physical programming
requires privately installed decoded unit specifications. Unsupported protection modes
return explicit errors instead of simulated success. See the [supported operations and remaining work](docs/cmqttd-cgate.md).

## Development tools and simulation

`cbus-tools` provides small inspection commands:

```sh
rust/target/release/cbus-tools decode 05013800790148
rust/target/release/cbus-tools dump-labels --pretty 2 rust/testdata/fixtures/project.xml
rust/target/release/cbus-tools serial-verify \
  --pci 192.0.2.10:10001 --plan selected-plan.json
rust/target/release/cbus-tools serial-apply \
  --pci 192.0.2.10:10001 --plan selected-plan.json \
  --journal /operator/recovery/selected-plan-attempt.json
```

The selected-serial commands consume a strict plan produced by the Toolkit workflow. Each `--pci` invocation opens a direct TCP socket and requires exclusive ownership of the CNI; stop `cmqttd` or any other current owner before running it. Verify performs bounded read-only classification. Apply completes the exact bookended fresh-before inventory, immediately rechecks local option 66=`05`, durably records send intent in a new journal, sends once on that same PCI connection, and independently verifies afterward. Preserve one stable journal path and use `serial-verify --journal` after any interruption or uncertain result; recovery never authorizes replay. These guarantees are covered with scripted loopback peers and do not claim physical-unit compatibility or persistence.

To exercise the Toolkit CLI against the Rust C-Gate model, start the server in one terminal:

```sh
rust/target/release/cgate-mock --bind 127.0.0.1:20033
```

Then, with the Python environment activated, use another terminal:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 project new DEMO
cbus-toolkit cgate --host 127.0.0.1 --port 20033 project list
```

`cgate-mock` implements all **431 unique command paths** in the maintained C-Gate inventory. It supports shared project state, per-client project selection, tagged replies, events, and programming sessions. This is complete command coverage in an in-memory test server; it does not establish full Toolkit workflow parity or physical-device behavior. State is lost when the server stops. See [C-Gate compatibility](docs/cgate.md).

For a PCI/CNI test endpoint, run `rust/target/release/cbus-simulator 127.0.0.1 10001`. This is a separate protocol from C-Gate: point PCI clients at the simulator and C-Gate clients at `cgate-mock`.

## Documentation and AI agents

- [Toolkit CLI guide](toolkit-cli/README.md) and [feature status](toolkit-cli/docs/implementation-status.md)
- [Architecture](docs/architecture.md), [command reference](docs/commands.md), and [protocols](docs/protocol.md)
- [MQTT bridge configuration](docs/configuration.md), [C-Gate compatibility](docs/cgate.md), and [physical DALI commands](docs/cgate-dali.md)
- [Testing and development](docs/testing.md)
- [AI skill](.agents/skills/cbus-cli/SKILL.md) with command, system, and workflow references; [repository agent guidance](AGENTS.md)

## Repository layout

```text
toolkit-cli/             Python cbus-toolkit application, tests, and feature docs
rust/                    Rust MQTT bridge, protocol libraries, and supporting tools
rust/testdata/           committed protocol vectors and system-test fixtures
docs/                    shared architecture, configuration, and development docs
.agents/skills/cbus-cli/ AI skill and operational references
cmqttd_config/           optional local Docker configuration
```

## License

GNU Lesser General Public License v3.0 or later. See [COPYING](COPYING) and [COPYING.LESSER](COPYING.LESSER).

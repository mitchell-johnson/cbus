# C-Bus Toolkit CLI and Rust tools

Manage Clipsal/Schneider C-Bus projects from the terminal and connect C-Bus lighting to MQTT and Home Assistant.

This repository has two main applications:

- **[`cbus-toolkit`](toolkit-cli/README.md)** — a Python CLI for Toolkit-style project editing, commissioning, unit configuration, scenes, and diagnostics. It works with project files offline and connects to C-Gate or a CNI for online operations. JSON output makes it usable from scripts and AI agents.
- **[`cmqttd`](docs/configuration.md)** — a Rust daemon providing MQTT/Home Assistant support and an embedded C-Gate service over one shared C-Bus connection. It runs without Schneider C-Gate, Windows, or the Toolkit application. Its [C-Gate replacement status](docs/cmqttd-cgate.md) distinguishes implemented hardware operations from outstanding compatibility work.

The Rust workspace also provides protocol tools, a PCI simulator, and a C-Gate compatibility server for development and testing. Install the application you need; the Python CLI and Rust bridge can be used independently.

## Compatibility at a glance

| Product | Compatibility measure | Current state |
| --- | --- | --- |
| `cbus-toolkit` | Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001 workflow parity | The strict ledger has 38 areas: **17 implemented, 19 in progress, and 2 pending**. `coverage` reports `complete: false` and `census_complete: false`; the categories are not a percentage of Toolkit functionality. |
| `cmqttd --cgate-bind` | Primary routing for the maintained C-Gate command inventory | **431 paths: 230 physical, 199 local/session, 0 blanket fail-closed 502, and 2 native-obsolete.** All 429 non-obsolete primary paths are routed and `full_cgate_command_path_coverage` is `true`. `full_cgate_compatibility` remains `false` because selector-specific, vendor-format, device/topology/timing, and physical-acceptance boundaries remain. |
| `cgate-mock` | In-memory C-Gate command surface | All **431** maintained paths parse and dispatch with deterministic protocol-shaped behavior. It does not provide persistent vendor storage, physical C-Bus effects, or device timing. |

Raw `cgate exec` and `cgate run` can forward the command surface exposed by the selected server. That reach does not create a typed Toolkit workflow, reproduce Toolkit GUI state, prove native-server semantics, or verify a physical effect.

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
| Create or compare a serial-bound eDLT label baseline | `cbus-toolkit cgate edlt-label-audit //PROJECT/NETWORK` |
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

For an exact C-Gate command or a batch that must share one session, use:

```sh
cbus-toolkit cgate --host 192.168.1.20 --port 20023 exec 'PROJECT LIST'
cbus-toolkit cgate --host 192.168.1.20 --port 20023 run commands.txt
```

Command batches stop at the first failure. These raw routes expose the selected server's command surface; typed CLI commands add workflow-specific validation and evidence, so raw forwarding is not typed Toolkit parity.

Results are JSON on stdout; operation errors are JSON on stderr and return a nonzero exit status. Put `--compact` before the command for single-line JSON. Event monitoring emits JSON lines.

To find a CNI2 or Wiser endpoint first, run `cbus-toolkit interface
discover-cni`. It sends one bounded IPv4 UDP query and reports the source
address plus advertised TCP port without opening the interface. A zero-reply
result does not prove that no interface exists. The Rust tools expose the same
wire codec and JSON boundary as `cbus-tools cni-discover`; see the [discovery
contract](toolkit-cli/docs/cni-discovery.md).

### Toolkit compatibility and current status

The CLI targets **C-Bus Toolkit 1.18.0.2754 and C-Gate 3.4.0.2001**, with full Toolkit functionality as the goal. Implemented workflows include offline project editing, native project management, supported unit programming and addressing, keypad presets, scenes, CGL exchange, and substantial eDLT configuration. Device and firmware support is documented per workflow.

For the bounded KEYGL5 5.5.00 parent transaction, the CLI composes 14 admitted
configurable widget panels—Measurement, Lighting, Enable, Fan, HVAC, Multi
Level, Room Courtesy, Scene, Shutter, Time/Date, Timer and all three MRA
models—and the activation, General, Display, Standby, Colours, Navigation,
Quick Status, Page Control and distributed MRA-global operations. It validates
ordered editability, complete byte and shared MRA-bit
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
workflow. Applications/Corridor cache dialogs, Blank/Reset, SceneManager
parent binding, original full-form execution and
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
cbus-toolkit cgate --host 127.0.0.1 exec 'HELP BROADCAST_EVENT'
cbus-toolkit cgate --host 127.0.0.1 exec 'BROADCAST_EVENT SP maintenance started'
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
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 edlt-label-audit //PROJECT/254 --write-baseline labels.json
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 edlt-label-audit //PROJECT/254 --baseline labels.json --mode configuration
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

`BROADCAST_EVENT` is local command-session traffic: it sends one native
timestamped level-three `703 cmdN - broadcast_event` line to clients subscribed
with `EVENT e3s0c0` (or a higher event level), without writing C-Bus, MQTT, or
the persistent database. The optional LOGIN gate protects event injection.

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
administrative operations send no PCI traffic. `PROGRAMMER TRIGGER ... START`
acknowledges an INIT queue immediately, then runs TEST, PP_COPY, PP_SAVE,
PP_SET, PP_END, PP_UNLOCK, DALI_READ, DALI_PROGRAM and public DALI commands in
priority order through cmqttd's existing local or physical backends. STATUS
reports the active queue count and TEST countdown. The worker stops on the
first failed receipt and never automatically replays an uncertain bus command.
`PP WRITE_PATCH` executes a strict operator-supplied
`cmqttd.pp-patch/v1` manifest uploaded to
`%PROJECT%/patchsets/cmqttd-patches.json` through the controlled `FILE`
namespace. It checks the saved and live type/firmware, requires an admitted
current patch version for a normal run, then holds one physical programming
lane across the recovered disable, block-write, full second verification,
version and re-enable sequence. The live preflight requires exactly one type
and firmware reply. Firmware bounds use native case-sensitive lexical ordering,
an optional catalogue selector requires equal saved metadata, and non-overlapping
blocks may occupy at most the effective 136 bytes in ranges 114–241 and
247–254. The version parameter is native `0xF2`; target `FF` is reserved, while
`FF` may be deliberately admitted as a current version for manual recovery.
Ordinary blocks use STORE tag `0x73`; parameter `0xF7`
uses the returned unlock challenge as its tag. An already-target unit is
accepted only after every block and control `0x70` are verified, with enable
repaired only when necessary. A successful physical reply identifies one of
three dispositions: full pipeline, repaired enable only, or verified read only.
Every write is read back and an incomplete
transaction is never replayed automatically. `SIMULATE` validates and prints
the complete plan and its SHA-256 without PCI traffic; pass that digest as
`EXPECT_SHA256=<64hex>` on the physical command to bind the reviewed plan.
Successful completion persists the decimal patch version and manifest
provenance. The proprietary
Schneider `patchset.zip` container is not ingested; `CMQTT CAPABILITIES`
reports that boundary explicitly.

The five-command `DEPLOY_QUEUE` family is wired to that volatile PROGRAMMER
worker. LIST, DELETE and typed DELETE_ALL return the retained native JSON/status
envelopes. ADD registers an INIT task, returns immediately, and publishes the
native `updated-entries`, `started` and terminal `ended` channel envelopes.
The first instruction failure leaves the entry in ERROR and publishes a
structured `debug` receipt. RETRY is accepted only for a queued STOPPED or
ERROR task and is the sole operation that deliberately reinitializes and
re-executes it. Queue state and subscriptions disappear on restart; physical
PP/DALI commands share cmqttd's CNI and MQTT continues to use it throughout.

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

The maintained `IDENTIFY` control leaves (`OFF`, `ON`, `RAMP`, and
`TERMINATERAMP`) drive application 251 groups on the configured direct
network. They use the native lighting-shaped SAL, including byte or percentage
levels, native duration suffixes, and optional `FORCE`. cmqttd accepts only
application 251: the retained native build falsely reports success without
sending a packet for other applications, so that unsafe behavior fails before
I/O. Incoming Identify traffic reaches C-Gate event clients and retains its
source unit; no MQTT Identify state is created.

`SHORTMESSAGE REFRESH` and `SHORTMESSAGE SEND` implement application 173.
Refresh retains the native 0..63 information-type field. Send validates the
fragment total/index, optional number and symbol, information type, and a
14-byte UTF-8 payload before I/O. C-Gate 3.4.0.2001 emits malformed SEND SAL:
it writes text as PCI hex characters, overstates the extended length, swaps
the number/symbol flags, and can still return 200. cmqttd deliberately repairs
SEND with real UTF-8 bytes, an exact extended length, and the layout accepted
by the native inbound decoder. This is protocol-compatible repaired behavior,
not byte-for-byte reproduction of the vendor defect.

`EREPORT MESSAGE` implements application 206 Error Reporting messages with
the native type aliases, category and `y`/`n` or `1`/`0` status flags,
severity, unit, and optional data bytes. Identify, Short Message, and Error Reporting commands are
sent once and require a correlated PCI confirmation on the active connection;
they are never replayed after an uncertain transport outcome. Mutating forms
require `LOGIN` when the optional gate is armed. Incoming Short Message and
Error Reporting SAL fans out to C-Gate event clients, while cmqttd defines no
MQTT state schema for either application.

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

Command discovery also matches the retained parent envelopes for fourteen
application and administration families, including `CLOCK`, `LIGHTING`,
`TRIGGER`, `SHORTMESSAGE`, `CGL`, and `TRANSFORM`. Bare, literal `?`, and
`HELP` forms are local and do not touch the C-Bus network. Each listed child
still follows its own capability classification; showing native help does not
turn an unsupported child operation into a simulated success.

General C-Gate clients can use silent untagged `#`/`//` comments, 301 `OID`,
local `BROADCAST_EVENT`, native object discovery and reads through `SHOW`, and
native-shaped `REPORT`, `TREE`, `TREEXML`, and `TREEXMLDETAIL`. `SHOW`
implements ordered `?`/`??` property catalogues and `*`/named reads for
`cgate`, projects, project C-Bus, project, network, application, group, unit,
and output-terminal objects. The application and child-object schemas cover
the retained Temperature, Lighting, Air Conditioning, Media Transport,
Trigger, Enable, Audio, Security, Clock, Telephony, Measurement, and generic
application classes represented by application IDs 25, 48, 95, 172, 192,
202, 203, 205, 208, 223, 224, 228, and 238. Named fields are
case-insensitive while preserving the caller's field spelling in the reply;
foreign-project lookup, canonical terminal aliases, object errors, and the
captured GET/SHOW trailing-token grammar are also pinned.

The exact native evidence includes the 62-command base object transcript
[`native_cgate_show_objects.json`](rust/testdata/fixtures/native_cgate_show_objects.json),
the 69-row casing/error audit
[`native_cgate_show_audit.json`](rust/testdata/fixtures/native_cgate_show_audit.json),
the 78-row application matrix
[`native_cgate_show_appclasses.json`](rust/testdata/fixtures/native_cgate_show_appclasses.json),
and the 18-row parser matrix
[`native_cgate_show_parser.json`](rust/testdata/fixtures/native_cgate_show_parser.json).
Tagged response order, status, fields, and framing are compared exactly.
Runtime host/IP/JVM metrics and scheduled timestamps vary by process, so the
replay validates their native shape and normalizes only values explicitly
declared volatile by a fixture before comparison.

`NEW UNIT/GROUP/PHANTOM` creates durable, idempotent database objects without
pretending that a unit exists on the bus. Its address, application-child, and
known/unknown firmware-token boundaries are pinned by the 25-row
[`native_cgate_new_bounds.json`](rust/testdata/fixtures/native_cgate_new_bounds.json)
transcript. Tree output combines those records with physical units already
observed by an explicit sync; TREE flags do not trigger a hidden physical scan.
The multi-application hierarchy, application labels, `Groups` versus `Net
Vars`, object states, and XML detail framing are pinned by
[`native_cgate_tree_appclasses.json`](rust/testdata/fixtures/native_cgate_tree_appclasses.json).
`CMQTT CAPABILITIES` reports these inventory and object-creation boundaries
for clients that need to distinguish database state from live C-Bus evidence.
When the optional C-Gate authentication gate is enabled, NEW and
BROADCAST_EVENT require an authenticated session.

**All maintained non-obsolete C-Gate command paths now have a primary route.**
The executable inventory contains 431 paths: 230 physical, 199 local/session,
zero blanket `FailClosed502` paths, and the two native-obsolete `NET
CHECK_UNRAVEL` and `NET STATE_INTERVAL` paths. This closes command-path routing;
it does not make `full_cgate_compatibility` true. Individual handlers still
reject unsupported selectors before I/O, and confirmed delivery is not proof of
a downstream device's state, timing, persistence, or behavior on every firmware
and topology.

The embedded endpoint includes the full maintained CONFIG, FILE, ACCESS, PORT,
and DEPLOY_QUEUE families; local repository selection and repair; all five
portable TRANSFORM leaves; legacy local and physical database lifecycle; native
parent help; the physical application, DALI, network, label, scene, and PP
routes described below; and a verified `PP WRITE_PATCH` path for the explicit
`cmqttd.pp-patch/v1` manifest. DEPLOY_QUEUE ADD and RETRY run admitted
PROGRAMMER PP/DALI work asynchronously, stop at the first fault, and never
replay an uncertain command automatically. Direct-network UNRAVEL handles the
whole safe inventory plan, including address 255 and larger duplicate sets,
with exact-once moves and a generation-bound final proof.

Compatibility boundaries remain explicit. Routed mutations and some
selector-specific DALI session plans refuse before I/O; the private Schneider
`patchset.zip`, repository/archive formats, and SQLite/XML schemas are not
reconstructed; cmqttd transforms only its versioned portable SQLite container
inside the controlled FILE namespace. Its ACCESS policy is a safer digest-only
local model, TLS has no client-certificate identity mapping, and the exact
native per-handler access-level matrix is unfinished. Device-family coverage,
unusual bridges and adapters, electrical/timing behavior, power-loss recovery,
and hardware acceptance beyond the evidenced profiles still require validation.
The Toolkit CLI's separate 17/19/2 workflow ledger remains incomplete.
See the [supported operations and remaining work](docs/cmqttd-cgate.md).

The NET runtime catalogue is separate from the imported tag database, matching
C-Gate's lifecycle boundary. Its active definitions and `DB`/`FILE` snapshots
are atomic `cmqttd-json` state; `FILE` is an internal snapshot and never opens a
caller-selected host path. `NET LEARN` and `NETWORK LOCATE` support only the
configured direct shared PCI, send exact SAL once, wait for its correlated
confirmation, and never replay an uncertain write. `NET OPEN`/`NET CLOSE` and
`PROJECT START`/`PROJECT STOP` change runtime state and clear volatile caches
without disconnecting cmqttd's shared PCI or MQTT. Direct `NET UNRAVEL`,
`NET UNRAVELUNIT`, and `DO ... UNRAVEL` use a complete known-serial inventory,
preflight every unique empty destination, send selected-serial writes once, and
verify the final inventory; routed or uncertain plans fail before mutation.
`TOPOLOGY EXPLORE` reuses the active endpoint (including socket/CNI aliases) or
opens each other supported descriptor transiently, reports physical MMI/project
identity results, and closes temporary transports before returning.

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

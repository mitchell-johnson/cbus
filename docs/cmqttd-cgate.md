# cmqttd C-Gate service

`cmqttd` provides an optional C-Gate command listener alongside MQTT. Both
interfaces share the same `PciClient`, writer, pacing, initialization and CNI
socket. Neither Windows nor Schneider's C-Gate process is required for the
operations listed here. `cgate-mock` remains a separate test server.

The executable primary-routing matrix covers all 431 maintained paths: 230 are
physical, 199 are local/session, none is a blanket fail-closed 502 path, and
`NET CHECK_UNRAVEL` plus `NET STATE_INTERVAL` retain their native obsolete 400
behavior. All **429/429 non-obsolete** paths therefore have a primary route.
The rejected class is also empty. `CMQTT CAPABILITIES` reports
`full_cgate_command_path_coverage: true` and the seven inventory/class counters;
it still reports `full_cgate_compatibility: false` because a
path can contain selector-specific refusals and because private vendor formats,
device/topology/timing behavior, and broad physical acceptance remain separate
requirements.

The same capability document reports live transport health as
`pci_generation`, `pci_connected`, and `programming_lane_state` (`ready` or
`reconnect-required`). An incomplete source-correlated programming exchange
reports its unit/parameter and fragment progress, plus block/offset for
fragmented memory reads, then permanently retires that generation and signals
connection loss. cmqttd reconnects a fresh generation through its existing
connection manager; it never replays, resumes, or reuses the partial snapshot.

`DBGETXML //PROJECT` now returns a read-only modeled
`Installation/Project/Network` snapshot for an existing loaded project,
independently of the connection's current project selection. It composes the
same Network subtrees returned by direct network reads, including modeled
applications, groups, labels, units and PP fields, in numeric network order.
This enables Toolkit CLI CSV export for a unit, network or entire project
through cmqttd. The native selector and hierarchy are backed by
[11 retained original project reads](../toolkit-cli/research/fixtures/native-cgate-project-xml-shape.json).
The minimal wrapper omits unmodeled native Installation/Project OIDs,
timestamps and metadata; it is **not a lossless Schneider project export**,
and numeric network order is local service behavior. The read neither
selects a project nor performs PCI I/O. Missing projects return 401. Other
project selector aliases, exact native error wording, complete original
wrapper metadata and original Toolkit report-manager order remain unverified.

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
and only alongside `--cgate-bind`). `--cgate-tls-client-ca <bundle.pem>` adds
mandatory mutual TLS: a client without a certificate chaining to that bundle
is rejected during the handshake before it receives a C-Gate greeting. A TLS
configuration failure exits before binding and before the state file is
created. The TLS handshake times out after 10 s so a stalled client cannot
hold a connection slot. Certificate admission is separate from C-Gate
ACCESS/LOGIN authorization. In an owned native C-Gate 3.4 loopback probe, a
trusted certificate whose subject matched an Admin `ACCESS user` row still
started at the interface's Clipsal level; username/password `LOGIN` raised it
to Admin, and `LOGOUT` and reconnect restored Clipsal. A missing certificate
received no greeting. cmqttd reproduces this observed sequence; broader
certificate-name mapping and other native TLS configurations are not yet
established. See `rust/testdata/fixtures/native_cgate_tls_authorization_probe.json`.
MQTT's existing TLS/authentication options remain independent.

The command listener implements native-shaped `LOGIN`, `LOGOUT`, and the full
maintained `ACCESS ADD/DELETE/LIST/LOAD/SAVE` family. It also offers an
opt-in operator recovery token via `--cgate-auth-file <token-file>` (requires
`--cgate-bind`). The file holds one
high-entropy token on its first line (generate with
`python3 -c "import secrets; print(secrets.token_hex(32))"`) with mode
`0400` or `0600`; a missing/unreadable/short/whitespace-containing token or
group/other-accessible file fails closed at startup before bind and before the
state file is created. `CMQTT CAPABILITIES` reports `cgate_auth: false`
dormant by default and `true` once armed. Armed, each connection needs either
`LOGIN <token>` (200) or a Clipsal/Max `LOGIN <username> <password>` (211)
before PP mutating verbs (`PP LOCK/LOAD/SAVE/CANCEL_LOCK/LOAD_FROM_FILE/
SET_RAW_DATA/RELOAD_CATALOG/...`; `PP GET/INFO/LIST` stay open), PROGRAMMER
queue creation/deletion/add/cancel/test/trigger, `PROJECT` lifecycle, `DB...`
writes, `SET`, advisory `LOCK`/`UNLOCK`, `EVENT_CHANNEL SUB`/`UNSUB`,
`DEPLOY_QUEUE ADD`/`DELETE`/`DELETE_ALL`/`RETRY`,
`NEW UNIT/GROUP/PHANTOM`, `BROADCAST_EVENT`,
`ACCESS ADD/DELETE/LOAD/SAVE` (ACCESS help and LIST stay open to a Clipsal or
Max session), `CONFIG SET/LOAD/SAVE/OBSET/OBRESET` (CONFIG help, GET, INFO and OBGET stay
open), `FILE UPLOAD/DELETE/MKDIR` (FILE help, DIR/LS, SHA256 and DOWNLOAD stay
open),
`LABEL CLEAR/CLEAREDLT/KFIGET/KFISET`, `DO ... FactoryDefault`,
`NET CREATE`/`DELETE`/`FLUSH`/`LEARN`/`LOAD`/`RENAME`/`SAVE`,
`NETWORK LOCATE`, `NET SET_PROJECT_IDENTIFY`, and
`SCENE RECORD`, the ten state-changing `AIRCON` subcommands, the thirteen
state-changing `AUDIO` subcommands, Security arm/tamper/alarm/keypad/display
control, the four Telephony mutation forms, `MEASUREMENT DATA`, and Media
Transport controls/reports, all four `IDENTIFY` controls, `SHORTMESSAGE SEND`,
and `EREPORT MESSAGE`; `GET`/`INFO`/`DBGET`-style reads, other bus-control
SAL traffic, AIRCON, AUDIO, SECURITY, MEASUREMENT, TELEPHONY and MEDIATRANSPORT
help, `AIRCON REFRESH`, the six AUDIO request/report forms,
`SECURITY STATUS_REQUEST`, `SECURITY REQUEST_ZONE_NAME`,
`TELEPHONY RECALL_LAST_NUMBER_REQUEST`, `MEDIATRANSPORT STATUS_REQUEST`,
`MEDIATRANSPORT ENUMERATE`, `SHORTMESSAGE REFRESH`, and `SCENE PLAY` stay open. Gated verbs attempted
without authenticated session state answer `420 LOGIN required`; a wrong token answers
`420 LOGIN failed`. Native `LOGIN` with no arguments returns `210 Access
level: ...`; `LOGIN <username> <password>` returns 211 on a matching ACCESS
user row or 422 on failure, and uses the first duplicate match. Without a
recovery token, `LOGOUT` returns the native 211 result after re-evaluating the
connection. When the recovery-token gate is armed it retains the established
`200 OK` LOGOUT contract and clears the per-connection mutation flag. There is
no attempt cap in this slice: the
loopback bind plus high-entropy token makes online guessing infeasible, and
a cap is follow-up work.
The native ACCESS role and the optional recovery-token gate are independent.
Seven owned C-Gate 3.4 probes captured 418 command invocations at all nine ACCESS
levels (38 earlier, 58 additional, 40 programming/queue, 44 media/security,
22 administrative, 24 application and 192 DALI forms). cmqttd checks 345 evidenced command
entry paths before handler execution:
Connect for `NOOP`; Monitor for `APIVER`, `HELP`, `EVENT`, `GET`, `DBGET` and
`DBGETXML`; Operate for `BROADCAST_EVENT`, `SESSION_ID`, `DBSET`, three Lighting
forms, `SCENE PLAY`, and the probed Aircon, Audio, Security and Error Reporting
forms; Admin for `PROJECT LIST/USE/NEW`, `CONFIG GET/SET` and `DBSETXML`;
Program for `NET LIST/PINGU`, `FILE DIR/MKDIR`, `CGL EXPORT` and
`DALI SESSION LIST`; and Clipsal for `PP LOCK`. The expansion covers ten more
`PROJECT` leaves at Admin, eleven database leaves split between Operate and
Admin, seven `NET` leaves and two `PORT` leaves at Program, and `TREE`,
`TREEXML`, `TREEXMLDETAIL`, `SHOW OBJECTS` and `GETSTATE` at Monitor.
`REPOSITORY LIST/USE` and `CONFIG INFO/OBGET` need Admin; `LOCK/UNLOCK`, `SET`,
`DO`, `LIGHTING RAMP`, `ENABLE SET`, `CLOCK TIME`, `TEMPERATURE BROADCAST`,
`MEDIATRANSPORT STATUS_REQUEST` and `SHORTMESSAGE REFRESH` need Operate at
handler entry. The probed `TRIGGER EVENT`, `EVENT_CHANNEL LIST/SUB/UNSUB`,
`DALI CATALOG LIST`, `CGL IMPORT`, `FILE LS/SHA256`, and `PORT LIST/IFLIST`
need Program.
The fourth probe covers 18 additional Audio leaves, six Security leaves and
20 Media Transport leaves. All 44 exact invocations require Operate at handler
entry; they target an absent project, so these responses establish neither
device-level permission nor a successful bus send. The retained
[`native media role fixture`](../rust/testdata/fixtures/native_cgate_media_authorization_probe.json)
is reproduced by
[`native_media_authorization_probe.py`](../rust/cbus-cgate/research/native_media_authorization_probe.py).
The fifth probe adds 22 exact handler floors: four CONFIG and two PROJECT
forms at Admin, two FILE, nine NET and four LABEL forms at Program, and
`MEASUREMENT DATA` at Operate. In particular, native C-Gate requires Program
for `FILE DOWNLOAD` and `LABEL KFIGET` even though they read data. The
[`native administrative role fixture`](../rust/testdata/fixtures/native_cgate_admin_authorization_probe.json)
and its [reproducer](../rust/cbus-cgate/research/native_admin_authorization_probe.py)
capture all nine roles on an owned disposable process without a C-Bus endpoint.
The sixth probe adds all ten Aircon setters, two Clock, two Enable, two
Lighting, Short Message SEND, all five Telephony and two Trigger label forms.
Twenty-two enter at Operate and Trigger label forms enter at Program. On absent
Telephony targets, all five reach object lookup at Operate; cmqttd now returns
the native 401 there. Configured Telephony targets retain the later Program
guard until successful native delivery below Program is independently tested.
The [application role fixture](../rust/testdata/fixtures/native_cgate_application_authorization_probe.json)
and [reproducer](../rust/cbus-cgate/research/native_application_authorization_probe.py)
bind the nine-role comparison and source hashes.
The seventh probe covers 126 additional DALI paths, including catalogue,
gateway, error reporting, emergency, measurement and session handlers. It
also repeats 66 mode-bearing paths with the native `poll` selector, for 192
invocations and 1,728 role responses. All captured invocations require Program
at entry. The [DALI role fixture](../rust/testdata/fixtures/native_cgate_dali_authorization_probe.json)
and [reproducer](../rust/cbus-cgate/research/native_dali_authorization_probe.py)
bind those observations to the original help, capture engine and owned
loopback harness. Missing CDG objects and the private `PROJECT_CUSTOM` syntax
error are later handler outcomes; the probe does not establish object-specific
permission, a successful DALI operation or parity for other selectors.
The programming probe establishes Clipsal for all 28 maintained PP leaves
(the earlier `PP LOCK` plus 27 additional leaves), and Program for all eight
`PROGRAMMER` and five `DEPLOY_QUEUE` leaves. Its 360 role/invocation pairs ran
in one disposable native process with no C-Bus endpoint. Absent sessions and
units establish entry authorization, not later object ownership or successful
physical execution. A user who logs down to Program cannot read, edit or end
an owned PP session; denial preserves that session and its lock. LOGOUT
restores the connection role, while another connection still cannot take over
the PP session merely by having the required role. The report is
[`native_cgate_programming_authorization_probe.json`](../rust/testdata/fixtures/native_cgate_programming_authorization_probe.json),
with its [reproducer](../rust/cbus-cgate/research/native_programming_authorization_probe.py).
A lower session receives
`420 Access denied.` before local mutation or PCI dispatch, including
here-document `DBSETXML`. `EVENTS` follows the same Monitor floor as its
`EVENT` alias. `ACCESS` retains its separate Clipsal/Max family check.
For the two probed Telephony forms, `CLEAR_DIVERSION` and
`RECALL_LAST_NUMBER_REQUEST`, an Operate or Admin session now receives the
native 401 absent-object response before the retained Program physical-send
gate; a target that exists still needs Program. The probe used absent
physical devices, so it establishes entry floors, not later object-specific
authorization; `CMQTT CAPABILITIES` exposes the exact covered paths under
`access_native_handler_probe_levels` and keeps
`access_global_command_level_matrix: false`. The retained native role and
TLS probes are in `rust/testdata/fixtures/native_cgate_authorization_probe.json`,
`native_cgate_authorization_expansion_probe.json`, and
`native_cgate_programming_authorization_probe.json`,
`native_cgate_media_authorization_probe.json`, and
`native_cgate_admin_authorization_probe.json`,
`native_cgate_application_authorization_probe.json`, and
`native_cgate_dali_authorization_probe.json`, alongside
`native_cgate_tls_authorization_probe.json`. The expansion used absent
objects or local commands on an owned loopback child with no C-Bus endpoint;
its 420/non-420 thresholds do not establish authorization for later successful
physical sends or every selector under a command family.
An unmatched non-loopback peer in token-only recovery mode receives 420 for
`EVENT`/`EVENTS` queries and setters until token login; a denied setter does
not alter its connection-local subscription.

`CGL IMPORT` and `REPOSITORY USE` are also denied before dispatch while
unauthenticated. After LOGIN, CGL import may update only the bounded local CGL
1.1 label model described below. Repository index 1 is an idempotent local
selection; other or malformed indexes retain their explicit errors.
Project files and the persistent database contain site information and must
not be committed or published.

MQTT lighting commands and C-Gate share the PCI but retain separate response
contracts. The MQTT worker keeps commands FIFO through correlated positive or
negative PCI confirmation, including bounded byte-identical retries. A positive
confirmation publishes the existing `cbus_source_addr: null` requested-state
echo only if no newer physical observation for the same application/group
arrived while delivery was pending. Per-group sequencing keeps unrelated
observations from suppressing that echo. Every confirmed command still queues
one level-status request for the affected block on an independent readback lane
before advancing to the next MQTT command and still publishes its result. The
echo does not populate C-Gate's live cache; only an incoming lighting or status
report does. Negative confirmation has no success echo, and timeout or transport
loss is outcome-uncertain and is never replayed after a reconnect. Non-retained diagnostics are published on
`cmqttd/cbus/command_result`. The retained cmqttd binary sensor changes to
`OFF` on C-Bus loss and `ON` when a fresh transport is installed; reconnect
also forces a configured status sweep to replace invalidated observations.

The embedded C-Gate endpoint binds volatile commits from the physical operations
listed below to the shared PCI generation and client that performed the I/O. A
reconnect that wins after confirmation but before commit returns 408: the old
operation cannot repopulate or clear the replacement generation's physical,
level, application, or dynamic-label observations, and cannot emit its success
event. The guarded paths include lighting and scene cache invalidation,
Trigger/Enable/clock/temperature state echoes, dynamic-label append and clear,
FactoryDefault label invalidation, and final `NET`/`DO` unravel inventory/event
commits.

## Implemented behavior

The project-administration success envelope and data-readback boundary below
are grounded in the retained native
[`PROJECT ARCHIVE`/`RESTORE`/`RENAME` acceptance](../toolkit-cli/docs/native-project-acceptance.json).
The repository row grammar is grounded in the retained
[repository inventory evidence](../toolkit-cli/docs/repositories.md). The
bounded application-catalogue, calculator, CGL, repository-selection, and
transform boundaries are grounded in
[`native_cgate_repository_transform.json`](../rust/testdata/fixtures/native_cgate_repository_transform.json).
Those captures and the disposable native
[`PROJECT COPY`/`DELETE` evidence](../rust/testdata/fixtures/native_cgate_project_copy_delete.json)
do not establish Schneider archive bytes, arbitrary server-file behavior, or
vendor SQLite/XML interoperability. cmqttd therefore confines selection to its
single repository and confines repair/transforms to its atomic JSON state and
versioned portable container.

| Operation | Backend and verification |
| --- | --- |
| Tagged/untagged commands, per-client project selection, `EVENT`/`EVENTS` subscriptions | TCP/TLS service; native `e0s0c0` connection default, first-token case-insensitive mode parsing, 64 clients, 1 MiB command limit, bounded event queues and writer deadlines. Numeric status/config levels 0–9 are echoed. Native loopback evidence confirms that `s1`, `s2` and `s9` all receive the same status line, while `s0` receives none. The pinned native `BA`/`BG` bytecode shows config levels above zero use the same direct fanout; a native config-change trigger has not been captured. See `rust/testdata/fixtures/native_cgate_event_fanout.json` |
| `BROADCAST_EVENT event-class [event-text]` | Local native-compatible event injection. In retained help, `SP` denotes the required whitespace before `event-class`, not a separate argument. Build 2001 accepts arbitrary event-class tokens and the minimal `BROADCAST_EVENT SP` form, where `SP` is the class and event text is empty; quoted text uses native mK dequoting. Success is exactly `200 OK.` and publishes both `#e# YYYYMMDD-HHMMSS.mmm 703 cmdN - broadcast_event ...` and `#s# broadcast_event ...` to eligible subscribers. `703` is reporting level 3, so `e2...` filters it and `e3...` admits it; any nonzero `s` level admits the status line. The minimal form retains the native trailing space. It performs no PCI or MQTT operation and is not persisted. The optional LOGIN gate protects it. Exact evidence is `rust/testdata/fixtures/native_cgate_broadcast_event.json` and `native_cgate_event_fanout.json`; mock, embedded-service and real-daemon tests cover fanout and timeouts |
| `SESSION_ID`, `SESSION_ID ALL`, `SESSION_ID TAG`, `QUIT`/`EXIT` | Volatile command-session registry with odd `cmdN` identifiers, peer origin, local connection time, one-shot application tags and native 300 envelopes. `QUIT`/`EXIT` ignore trailing words; a successful 204 shutdown reply is flushed before the connection closes. No project, database or PCI state is changed |
| `EVENT_CHANNEL LIST/SUB/UNSUB` | Exact four-row C-Gate 3.4 deploy-queue channel catalogue and per-command-connection subscription state, including native 200/201/400/451 reply shapes. SUB and UNSUB require LOGIN when the optional gate is armed. Queue transitions publish untagged `updated-entries`, `started`, and `ended` JSON envelopes only to sessions subscribed to that channel, independently of `EVENT` mode. A first instruction fault publishes one structured cmqttd `debug` receipt with instruction identity, status and replay context; its content is explicitly not claimed as native diagnostic-string parity |
| Advisory `LOCK OBJECT`, `UNLOCK OBJECT` | Resolves durable project/database objects and enforces command-session ownership with native 225/425/226/426 replies. Locks are volatile and released by successful credential-changing LOGIN, LOGOUT, disconnect, or owning UNLOCK. They are separate from PP locks, never persisted, and perform no PCI I/O |
| Project list/use/load/save/new/close; database CRUD and database snapshots | Persistent JSON database; atomic replacement, restrictive permissions, failed-write rollback |
| Bare `PROJECT`/`PROJECT ?`, `PROJECT DIRFULL` | Exact retained 18-line help and native 123 project/description rows. cmqttd's repository has no separate unloaded disk layer, so every modeled project is durable and appears in DIRFULL; an empty model returns native 124 |
| Native parent help for application and administration families | Bare, literal `?`, and `HELP` forms return the exact retained C-Gate 3.4 envelopes for `APPLICATIONS`, `CALCULATOR`, `CGL`, `CLOCK`, `ENABLE`, `EREPORT`, `IDENTIFY`, `LIGHTING`, `REPOSITORY`, `SHORTMESSAGE`, `TEMPERATURE`, `TEST_SPAM`, `TRANSFORM`, and `TRIGGER`. Help is local and performs no PCI I/O. It only describes the native command surface; every child retains its own physical, local/session, or native-obsolete classification and its own selector limits. See `rust/testdata/fixtures/native_cgate_family_help.json` |
| `APPLICATIONS GET_CATALOG` | Streams the operator-supplied `applications.xml` under `--cgate-unitspec` in the retained 343/347/344 XML envelope. The file is bounded, containment-checked, and XML-validated. cmqttd does not bundle, reconstruct, or claim Schneider's proprietary application catalogue |
| `CALCULATOR TEST` | Reproduces the retained 134 result envelope from durable database unit records and the operator-supplied bounded `cbusunits.xml`. The arithmetic reports current supply, current consumption, impedance, and known/unknown unit counts; it performs no physical measurement or PCI I/O |
| `CGL IMPORT`, `CGL EXPORT` | Bounded CGL 1.1 JSON over known database routes. Import preserves existing application/group/level names, creates missing labels atomically, persists them in `cmqttd-json`, and reports unroutable networks with the retained incomplete 380 result. Export supports network/application filters and retains the selected network shell. The contract covers modeled network, application, group, and level labels only; it does not program automation controllers or preserve unknown vendor metadata |
| Comments, `OID`, `BROADCAST_EVENT`, `SHOW`, `REPORT`, `TREE`, `TREEXML`, `TREEXMLDETAIL`, `NEW` | Untagged `#` and `//` command-file comments are consumed without a reply; tagged markers retain the captured syntax-error behavior. `OID` returns a fresh native 301 version-1 UUID that is deliberately not registered as a database object. `BROADCAST_EVENT` fans its caller-supplied event class/text to subscribed C-Gate clients without PCI traffic. `SHOW` implements ordered `?`/`??` catalogues and `*`/named reads for `cgate`, projects, project C-Bus, project, network, application, group, unit, and output-terminal objects. It includes caller-cased named fields, canonical terminal aliases, foreign-project lookup, native object/parameter errors, and the retained application and child schemas for IDs 25, 48, 95, 172, 192, 202, 203, 205, 208, 223, 224, 228, and 238. `REPORT`/`TREE` use native 320 hierarchy framing; XML uses 343/347/344 framing and escapes retained text. Their parser admits the captured plain TREE/REPORT tails while keeping XML and `NET TREE` flags strict. The hierarchy renders the already observed physical cache plus durable database objects; `WITHSYNC`, `WITHPSYNC`, and `WITHQSYNC` do not start a hidden scan. `NEW UNIT/GROUP/PHANTOM` is durable and idempotent under an existing selected network; its address, application-child, and known/unknown firmware-token bounds follow native evidence and never invent physical presence. Exact tagged evidence is in `rust/testdata/fixtures/native_cgate_general_tree.json`, `native_cgate_show_objects.json` (62 commands), `native_cgate_show_audit.json` (69 rows), `native_cgate_show_appclasses.json` (78 rows), `native_cgate_show_parser.json` (18 rows), `native_cgate_new_bounds.json` (25 rows), and `native_cgate_tree_appclasses.json` (three rows). Runtime host/IP/JVM metrics and scheduled timestamps are shape-validated and normalized only where declared volatile by those fixtures. `rust/cmqttd/tests/system_cgate_general_tree.rs` verifies the daemon boundary and no command-induced PCI traffic. |
| `PROJECT ARCHIVE`, `PROJECT RESTORE`, secondary-project `PROJECT RENAME` | Exact retained native success envelope (`200 OK.`), optional LOGIN gating, and atomic durable commit/rollback. Archive tokens must use the explicit `cmqttd:KEY` namespace and address snapshots inside cmqttd's JSON state repository; other tokens return 408 and are never opened as filesystem paths. These are not Schneider ZIP/GZ/DB files. Snapshots retain modeled project/network/unit records and their unit fields; opaque auxiliary database maps are outside this bounded snapshot contract. Runtime physical presence, levels, and network state are excluded. The configured hardware project cannot be renamed while the service is running and returns 408 because the PCI/MQTT binding is immutable |
| `PROJECT COPY SOURCE DESTINATION`, `PROJECT DELETE NAME` | Exact native success envelope (`200 OK.`), strict named grammar, optional LOGIN gating, and atomic durable commit/rollback. COPY preserves durable project/network/unit/level data and database OIDs while excluding physical presence, observed levels, and open network state; the source remains selected. A shared copied OID resolves only when the connection's effective selected project owns it; an unrelated selection returns 401. DELETE is limited to secondary projects, clears the deleting connection's selection, and removes only the target's durable records. The configured hardware project returns 408. Native C-Gate separates on-disk repository projects from loaded projects; cmqttd has one loaded atomic JSON model, so copies are immediately selectable and deletes take effect immediately. This is an explicit lifecycle difference, not vendor repository-file parity |
| `REPOSITORY LIST/USE`; `PROJECT REPAIR` | LIST returns one native-grammar `123 index=1 type=cmqttd-json path=... current=yes` record for `--cgate-state`. USE accepts only numeric index 1 as an idempotent selection, rejects unknown indexes with 408 and malformed values with 400, and never synthesizes a host path or hidden repository. PROJECT REPAIR performs a complete serialize/parse/restore validation of cmqttd's atomic JSON repository, preserves runtime physical caches, commits atomically, and rolls back on failure. These are cmqttd repository semantics rather than Schneider SQLite repository-file parity |
| `TRANSFORM MIGRATE_SQL/PROJECT/SQL_TO_XML/SQL_TO_XML_CGATE2/XML_TO_SQL` | All five leaves operate only in the controlled FILE namespace. XML_TO_SQL creates a real versioned `cmqttd-portable-project-v14` SQLite container after bounded XML validation; SQL_TO_XML and SQL_TO_XML_CGATE2 integrity-check that exact schema and recover its byte-preserved XML; MIGRATE_SQL upgrades that portable schema with a `.0` backup; PROJECT maps its default operation to cmqttd-json repair and admits bounded non-networked XSLT with DTD, `document()`, include/import, and extension rejection. `--test` validates without writing. Private Schneider SQLite/XML schemas remain rejected and no transform opens an arbitrary host path |
| `DBGETJSON NAC_OBJECTS_LIST/NAC_ROUTING_TABLE/NAC_TAGMAP` | Exact root help and native JSON envelopes over a validated durable unit. The importer does not retain vendor `NACObjectList` definitions, so object and routing projections are explicitly empty and `database_json_nac_object_definitions` is false. TAGMAP emits the durable local network, supported application, group and level tags available in cmqttd's model. These reads perform no PCI I/O; see `rust/testdata/fixtures/native_cgate_local_admin.json` |
| `DBADD`; `DBCOPY`; `DBNEW`; `DBTAGLIST`; `DBSET`; secondary-project `DBRENAMENET`/`DBRENAMENETSAFE` | Selected-project local database lifecycle grounded in `rust/testdata/fixtures/native_cgate_legacy_database.json`. DBADD creates durable typed objects before compulsory fields exist; OID DBGET reports native nulls and DBSET atomically materializes the object after Address and TagName arrive. DBCOPY assigns fresh OIDs throughout the subtree, clears Address and TagName throughout a same-project copy, and retains them for a cross-project copy. DBNEW atomically leaves the selected Installation/Project blank while cmqttd retains its configured interface as a non-durable runtime shell. DBTAGLIST, unsafe DBSET and both network-rename spellings retain their selected-project, atomic-persistence and corruption-repair contracts. These local commands never send PCI traffic. |
| `DBCREATE`; `DBUPDATE`; `DBVERIFY` | Physical database lifecycle over the configured shared CNI. Every operation first uses generation-guarded `NET SYNC`; an incomplete, disconnected or stale refresh fails before database mutation. DBCREATE replaces the selected tag database with fresh network/unit OIDs and `[default]` compulsory names where the network supplies none. DBUPDATE accepts a network or unit and optional exact `UnitDelete`, preserves existing OIDs and database names, updates physical identity, and removes absent database units only when requested. DBVERIFY compares database and physical presence plus nonblank type, firmware and serial identity, returning ordered 345 Difference rows and a counted final 408 or 200 when equal. Successful mutations commit atomically and survive restart. |
| `DBSETXML` | Scalar-field documents and complete `Unit`, `Level`, `NetVar`, `Group`, `Application`, and `Network`/`Interface` documents are supported, including a complete Network composed with Unit and Application children. Complete forms validate the entire document, selected-project path/OID target, required Unit scalars and PP ownership, the captured Application/Unit, two-Unit, repeated leaf-Application, and repeated Application with independent Group/NetVar children shared-OID shapes, other OID conflicts, and sibling application/unit address conflicts on a staged clone, then atomically replace the old subtree and return `301 OID=<submitted-root-oid>`. Modeled readback keeps scalar and PP values in native schema order; fresh complete replacements discard observed comment, processing-instruction and unknown namespaced additions at the Network/Interface/Application/Unit layers, and nested decoration under known Unit fields becomes direct text or an empty scalar; state survives copy, rename, archive/restore, and restart with no PCI traffic. The configured live Network accepts a replacement only at the same address and with the same interface type/address binding; runtime physical inventory, levels, state, and retry count remain intact. A move or rebind rolls back with 408. Owned native C-Gate 3.4.0.2001 cases pin a combined Network/Application/Unit `301` root receipt, schema-ordered plain Unit readback and missing-`UnitName` `446` without mutation. The [combined](../toolkit-cli/docs/native-cgate-dbsetxml-combined-vm.md) and [direct-Unit](../toolkit-cli/docs/native-cgate-dbsetxml-unit-mapper-vm.md) disposable-VM oracles pin acceptance and omission of two unknown namespaced Unit additions, with 12/12 scoped Unit mapper comparisons plus 2/2 full combined Network readbacks for each Rust server. Successful single-row `DBGETXML` replies now use the captured native `343/347/344` TCP envelope with an LF-only declaration row on both Rust servers; the [fresh framing oracle](../toolkit-cli/docs/native-cgate-dbgetxml-framing-vm.md) pins address/OID/error and pipeline cases. The [replacement-edge oracle](../toolkit-cli/docs/native-cgate-dbsetxml-replacement-edges.md) pins seven Rust vector transactions with 11 exact mapper readbacks and saved omission of optional Unit fields. The [duplicate-OID oracle](../toolkit-cli/docs/native-cgate-dbsetxml-duplicate-oids.md) pins independent scalar/PP readback, save/reload and path-targeted mutation for an Application/Unit or two Units sharing one OID. cmqttd retains those captured Unit-containing shapes with address-keyed metadata and matches ten exact vector readbacks. The [same-OID Application oracle](../toolkit-cli/docs/native-cgate-dbsetxml-duplicate-applications.md) captures two leaf Applications through save/reload, direct replacement and OID-targeted TagName/DBSETXML mutation. The [order/count extension](../toolkit-cli/docs/native-cgate-dbsetxml-application-shapes.md) captures reversed pairs, triples and quadruples; C-Gate retains submission order and selects the final submitted Application by OID. Rust replays the 114-request capture, compares all scoped DBSETXML and readback responses (excluding three synthetic DBCREATENET setup receipts), persists the order through service restart, and keeps direct and OID-targeted replacement scoped to the selected path. The [nested-Application oracle](../toolkit-cli/docs/native-cgate-dbsetxml-nested-applications.md) captures 67 original requests with Group and NetVar children under same-OID Applications, including direct replacement and save/reload. Rust compares the scoped exact readbacks and persists those children through repository restart. Other duplicate typed-container shapes and cross-network Unit-OID collisions still return 409 pending native and model evidence. Ambiguous Unit-containing OID mutations return 409 without changing either object; use a Unit path. Uncaptured duplicate-Application field and delete operations also return 409. Broader combined forms and private Schneider XML/repository formats remain outside the established native contract. |
| Nested Levels under same-OID Applications | The [owned oracles](../toolkit-cli/docs/native-cgate-dbsetxml-nested-levels.md) add distinct Level grandchildren under independent Group or NetVar children. Exact replay retains both paths and final-submitted Application OID selection, adds empty Level `TagsDLT` only on load after save/close, and preserves the documented direct NetVar/Level `DBGETXML` 500 while OID Level reads succeed. A 108-request follow-up proves the empty Level `TagsDLT` can be submitted again in Network, Group, NetVar and Level XML and survives another lifecycle. A 24-request capture establishes a nonempty Level text label with generated TagDLT OID, explicit-OID edit, save/load and complete Network replacement. A 34-request Group-label capture adds generated identity, explicit edit, second flavour, empty-collection removal, Network replacement, and durable save/load. Broader label and XML shapes remain outside the admitted slice. |
| Here-document framing | TCP and TLS recognize native `COMMAND << DELIMITER` framing and apply the optional LOGIN gate. Lines are limited to 1 MiB and bodies to 16 MiB; an oversized body is drained to its delimiter and returns tagged 400 so the connection remains synchronized, while EOF before the delimiter returns tagged 400 and closes the connection. `CGL IMPORT` validates and atomically applies only the bounded CGL 1.1 label model above. `DBSETXML` uses the same bounded transport for its scalar-field and evidenced complete typed-object scope. |
| `DBNETWORKPATH` | Resolves Bridge `InterfaceAddress` topology using the standard far-side network-address convention, requires the corresponding source-network bridge unit, limits paths to six bridges, and returns native single-line `136` COMPACT or multi-line `137` network-OID results without PCI I/O. Returned OIDs resolve through `DBGET !oid/OID` in the selected project. The final `/p/<interface-unit>` component may differ from the child network; it validates as an interface address but does not replace the far-side route byte, and path discovery does not require that suffix unit to exist. Native zero-hop `START == END` requests return `408 ... No path found`; only a literal `COMPACT` selects compact output, while another mode token defaults to OID and later tokens are ignored |
| `NET`, `NETWORK`, `TOPOLOGY`; `NET CREATE/DELETE/FLUSH/LIST/LOAD/RENAME/SAVE` | Exact retained build-2001 root/subcommand help and a runtime network-definition catalogue in the atomic `cmqttd-json` repository. CREATE accepts a bounded definition but never opens another interface. RENAME changes the runtime definition while preserving its immutable optional shared-PCI binding and does not rename the tag-database object. DELETE refuses an operating bound definition with native 468. FLUSH clears only volatile observations. SAVE/LOAD use internal `DB` or `FILE` snapshots; `FILE` is not a host path, and LOAD rejects duplicate names with the observed 408 before mutation. Their retained optional project token resolves the named project even when another project is selected; cross-project tests pin isolation and a missing project returns native 401. Mutations require LOGIN when armed and send no PCI traffic |
| `NET LEARN`, `NETWORK LOCATE` | Exact retained learn-mode and locate-yourself SAL on the configured direct network or a topology-resolved one-to-six-bridge PPM route. LEARN validates application, grades 1/2/128–131 and group, including its inner checksum. LOCATE supports UNIT, APP, GROUP and manufacturer/native-serial selectors with OFF/ON/byte modes on application 208. Each command enters the shared command lane, transmits once, waits only for its correlated PCI confirmation, checks the active PCI generation, and never replays an uncertain outcome or invents remote readback. A 200 proves interface delivery only. Unbound, foreign and unroutable definitions fail before I/O. Incoming frames fan out to C-Gate event clients and do not create MQTT state. See `rust/testdata/fixtures/native_cgate_net_lifecycle.json`, `rust/testdata/vectors/network_management.jsonl`, `rust/testdata/vectors/encode.jsonl`, and the service/daemon regressions. |
| `NET STATE_INTERVAL` | Exact unconditional native obsolete 400 directing callers to `set projects NetStateInterval X`; no state or PCI I/O |
| `NET OPEN/CLOSE`, `PROJECT START/STOP` | Runtime lifecycle over the durable NET catalogue and imported project model. OPEN/START admit the configured bound network and its reachable imported routes; CLOSE/STOP clear volatile physical and level observations and mark the affected runtime networks closed. cmqttd retains its shared PCI/CNI and MQTT ownership throughout, so these commands never manufacture a second connection. An unbound CREATE-only definition returns 408 because it has no cmqttd runtime binding |
| `NET UNRAVEL`, `NET UNRAVELUNIT`, `DO ... UNRAVEL` | Physical direct or topology-resolved one-to-six-bridge planner over a complete route-correlated MMI and known-serial inventory. Healthy singletons stay in place; address 255 is fully split and each other duplicate keeps one deterministic unit. `MATCHDB` prefers one unique empty database address for that serial, then the lowest independently verified empty address on the target network. The service resolves the full route, proves all targets and local PCI option 66=`05` before the first selected-serial write, sends every move once, requires the exact direct receipt or Reply Network route/remote-unit/serial receipt, verifies each destination, and accepts success only after an exact final target-network inventory under the same PCI generation. Unknown or ambiguous routes, unknown serials, insufficient unique targets, reconnects, and uncertain replies fail safely; no write is replayed or rolled back. Only the addressed network cache/state commits. `DO` returns native 202 framing over the same backend. Scripted PCI and daemon acceptance do not establish physical bridge delivery or power-cycle persistence |
| `TOPOLOGY EXPLORE` | Parses CNI/socket/Wiser/serial descriptors, performs physical installation MMI plus parameter-35 project identity discovery, and returns native-shaped 321/323/324 progress. The active endpoint is recognized across socket/CNI aliases and reused through cmqttd's generation guard, preserving MQTT. Other supported endpoints are reset and explored through a temporary transport that is always shut down. Bad descriptors and open/MMI failures retain 470/472/473 evidence |
| `CONFIG` and `CONFIG GET/INFO/SET/OBGET/OBSET/OBRESET/LOAD/SAVE` | Complete maintained C-Gate 3.4 CONFIG family with its exact parent help, case-sensitive parameter names, 148 registered parameters, 142 queryable INFO records, 122 wildcard GET records, six obsolete registrations, and retained 303/304/error/mixed-status envelopes. Legacy GET/SET use global/project inheritance; object forms model global, selected-project and network inheritance, including project resets that remove descendant network overrides. Values and named global/project snapshots commit atomically inside `cmqttd-json`; caller filenames are bounded snapshot identities and are never opened on the host. Three global catalogue keys now have native-observed restart effects. The listener emits level-1 `761 cmdN - Command: ...` events; startup `command.show-responses=yes` (the native default) additionally emits one level-6 `766 cmdN - Response: ...` event per reply line, including multiline replies and errors. Setting it to `no` suppresses only 766 events after a restart. Startup `command.show-time=yes` emits level-7 `767 cmdN - commandId=<tag> time=<milliseconds>` events after completed replies. Startup `event-millis=yes` (the native default) retains `.mmm` in the timestamp of 761, 766, 767 and local 703 `BROADCAST_EVENT` lines; `no` omits that suffix. CONFIG reads reflect SET/LOAD immediately, while the running listener retains all three startup settings. Credential-bearing command and response event payloads are redacted as a deliberate security difference from native C-Gate. Other CONFIG values remain stored metadata and do not reconfigure the listener, PCI, MQTT, logging or other daemon settings. With LOGIN armed, all five mutating verbs require authentication. Native 3.4 sends no response for an unknown or wrong-scope OBGET; cmqttd deliberately returns deterministic 408 so the connection remains live. See `rust/testdata/fixtures/native_cgate_config.json`, `native_cgate_config_command_show_time.json`, `native_cgate_config_command_show_responses.json`, `native_cgate_config_event_millis.json`, and `rust/cmqttd/tests/system_cgate_config.rs` |
| `FILE DIR/LS/MKDIR/DELETE/SHA256/DOWNLOAD/UPLOAD` | Complete maintained C-Gate 3.4 FILE family over a sandboxed virtual filesystem in `cmqttd-json`: exact nine-line parent help, 304/305 listings, recursive MKDIR, empty-directory/file deletion, multi-file 302 SHA256 rows, native 345/347/346 download framing with 76-character base64 rows, base64 here-document upload, and `.0` replacement backups. Ordinary relative paths reject leading separators, `~`, `..`, and `:`; `%PROJECT%/path` accepts the namespace separator for a known project and stays in a separate virtual root. No FILE path opens an arbitrary host or vendor project file and no FILE command sends PCI traffic. With LOGIN armed, UPLOAD, DELETE and MKDIR require authentication. See `rust/testdata/fixtures/native_cgate_file.json` and `rust/cmqttd/tests/system_cgate_file.rs` |
| `PORT` and `PORT LIST/IFLIST/CNISCAN/CNISCAN2/PROBE/REFRESH` | Complete maintained C-Gate 3.4 PORT family. Bare/`?` returns exact retained help. LIST reports local serial names without `/dev/` and marks cmqttd's selected serial `inuse`; IFLIST excludes loopback addresses. CNISCAN sends the exact four-byte legacy request from UDP 30718, accepts only 124-byte replies and optionally tests the little-endian advertised TCP port. CNISCAN2 runs that legacy scan and the retained variable CCP request from UDP 20050 with the native CRC, parameter set and five-second window, returning extended type/MAC/serial/unit 129 rows. PROBE accepts serial/socket/CNI/Wiser/EtherLite grammar, refuses the active cmqttd endpoint with 431, uses a separate temporary connection for the retained DC1/`@2104` echo-and-serial exchange, returns the filtered PCI serial text and closes it. Direct serial uses native software flow, modem control and six-rate PCI baud detection. EtherLite uses its native FAS heartbeat, unit inquiry, serial setup and framed byte stream. Native build 2001 makes REFRESH inapplicable because its port list is automatic; cmqttd returns the exact observed 408. LOGIN gates scans, probe and refresh. See `rust/testdata/fixtures/native_cgate_port.json`, `rust/testdata/vectors/cni_discovery.jsonl`, and `rust/cmqttd/tests/system_cgate_port.rs` |
| `ACCESS ADD/DELETE/LIST/LOAD/SAVE`, `LOGIN`, `LOGOUT` | Complete maintained C-Gate 3.4 ACCESS grammar, exact parent/subcommand help, ordered levels from None through Max, case-sensitive user login, first-match duplicate users, role-filtered 135 LIST rows, 1-based filtered DELETE, and session-local elevation retained until LOGOUT. Active rows, admission mode, and named SAVE/LOAD snapshots commit atomically in `cmqttd-json`; snapshot names are bounded identities and never host paths. cmqttd deliberately stores only credential digests and prints `<redacted>` where native C-Gate exposes plaintext. It validates interface/remote names before mutation and returns non-mutating 408 for missing LOAD snapshots. Fresh and pre-ACCESS repositories admit Docker/NAT peers at Clipsal until an operator adds, deletes, or loads interface/remote policy. Thereafter an unmatched non-loopback peer gets 421 without a recovery token; with the token configured it gets a restricted LOGIN/LOGOUT-only session so the token can repair policy. Loopback retains a Clipsal recovery path. With the recovery-token gate armed, ADD/DELETE/LOAD/SAVE require either its one-token LOGIN or a Clipsal/Max ACCESS-user LOGIN from an admitted connection. 345 native-probed handler entry floors are enforced and reported under `access_native_handler_probe_levels`; object-specific checks and the remaining native matrix are incomplete, so `access_global_command_level_matrix` remains false. See `rust/testdata/fixtures/native_cgate_access.json`, `native_cgate_dali_authorization_probe.json`, and `rust/cmqttd/tests/system_cgate_access.rs` |
| `ACCESS_CONTROL CLOSE/LOCK` | Physical application-213 commands. They validate the native zone and point byte ranges, encode the retained CLOSE (`0x02`) or LOCK (`0x0A`) SAL, send exactly once through the shared PCI, and require the correlated active-generation confirmation. A 200 proves interface delivery, not door/controller state or persistence. The configured network and topology-resolved routes through one to six bridges use exact-once delivery with no controller readback; TLS-client-certificate identity mapping remains outside the evidenced scope |
| Database PP locks, sessions, get/set/info/new/load/save | Existing programming model with connection ownership; staged sessions and locks are discarded on disconnect/restart |
| `PP CANCEL_LOCK/LIST_LOCK/UNITS`, `GET_RAW_DATA/SET_RAW_DATA/DEBUG`, `LOAD_FROM_FILE` | Native 121/122 inventory, address cancellation, bounded session memory and nine-row memory diagnostics. Raw edits and file loads change only an owned staged session. `LOAD_FROM_FILE` accepts one bare `.xml` filename under `--cgate-unitspec`; it cannot open an arbitrary host path. Cancelling a lock leaves its session visible with `address=null`, matching retained native behavior |
| `PP CATALOG_INFO/GET_UNIT_CATALOG/GET_UNIT_SPEC/LIST_CATALOG_NUMBERS/RELOAD_CATALOG/PATCH_VERSION` | Native catalogue, XML and status envelopes over optional private `cbusunits.xml` and decoded unit specs under `--cgate-unitspec`. Catalogue matching follows its own decoded unit-spec rules; WRITE_PATCH manifest firmware bounds separately use native case-sensitive lexical comparison. Reload invalidates the bounded parsed caches. PATCH_VERSION returns status 301 and the version from a fully valid controlled-FILE patch manifest; DEBUG projects manifest-order native-shaped patch/block rows. Without a manifest it retains the native 408 missing-patchset response |
| `PROGRAMMER CREATE/DELETE/LIST/STATUS/TEST/ADD_INSTRUCTION/CANCEL_INSTRUCTION/TRIGGER` | Runtime-only native queues with case-insensitive names in creation order, quoted task fields, priorities and instruction IDs. START acknowledges immediately and asynchronously runs TEST, PP_COPY, PP_SAVE, PP_SET, PP_END, PP_UNLOCK, DALI_READ, DALI_PROGRAM and public DALI command tails through the existing service dispatch. STATUS excludes the active instruction from queueCount, retains totalCount and exposes the TEST countdown. PAUSE/RESUME/STOP/ERROR are observed between commands and during TEST. A physical receipt failure stops the queue in ERROR; START cannot replay a terminal queue and no failed/uncertain command is retried automatically. Queues are discarded on restart |
| `DEPLOY_QUEUE ADD/DELETE/DELETE_ALL/LIST/RETRY` | Dedicated runtime queue over PROGRAMMER task groups with retained help, 450/451/501/502 errors, TaskGroupSummary JSON field order/timestamps, ALL/PENDING/FAILED/COMPLETED bulk deletion, per-entry 120/501 rows, and all four event channels. ADD validates/registers an INIT task and acknowledges before asynchronous execution. The first instruction fault stops in ERROR and emits a structured cmqttd debug receipt before ended; this does not claim native diagnostic-string equivalence. RETRY admits only a queued STOPPED/ERROR task, refreshes the reinitialized timestamps/countdown and deliberately re-executes it. LIST, terminal DELETE and DELETE_ALL remain local. Queue state is never persisted. PP/DALI work uses the shared cmqttd CNI and preserves MQTT operation. See `rust/testdata/fixtures/native_cgate_deploy_queue.json` and `rust/cmqttd/tests/system_cgate_pp_programmer.rs` |
| `PP WRITE_PATCH` | Physical execution from a strict operator-supplied `cmqttd.pp-patch/v1` manifest in the controlled FILE namespace. The retained unit/hex-version/optional-SIMULATE grammar selects by exact saved unit type, native case-sensitive lexical firmware range, optional catalogue and target patch version; cmqttd deliberately rejects a catalogue-constrained selector when saved catalogue metadata is absent. Blocks are 1–12 bytes, non-overlapping, wholly inside 114–241 or 247–254, for an effective maximum of 136 bytes. The patch-version parameter is native F2 (`0xF2`); target `FF` is reserved and may only be explicitly admitted as a current version for manual interrupted-write recovery. Before mutation cmqttd requires exactly one live type and firmware reply and checks the current patch-version byte. One programming lane then runs native 0x70 disable (`85:ffff`), temporary F2 version (`86:ff`), ordinary block STOREs with tag `73` and F7 STOREs with the returned unlock challenge, immediate readback, a distinct full verification pass, target F2 version, 0x70 enable (`85:9d40`) and final version readback. Already-target recovery is read-only when blocks/control match or repairs only enable when needed. A 200 reports full-pipeline, repaired-enable-only, or verified-read-only disposition. SIMULATE exposes a SHA-256; optional `EXPECT_SHA256=<64hex>` binds physical execution. Failed writes are never automatically retried and require reconnect. Proprietary Schneider `patchset.zip` ingestion remains unsupported and is reported by capabilities |
| `PP RESET_TO_DEFAULTS` | Replaces one owned loaded session with exactly the `DefaultValue` fields in its parsed unit specification. The result remains staged until an explicit save; missing or malformed specifications return 408 unchanged, with no PCI access |
| Physical PP LOAD and subsequent GET/INFO | Identifies the live unit, selects its privately installed decoded schema, recalls standard CAL parameters, explicit pages for `paged`/`ncc`, OEM memory, and GOC parameter-`0xFF` memory through the shared PCI, decodes int/long/bit/string/sixbit arrays and `ArrayMap`, applies tag selection, and commits the session only after every read succeeds. The same methods work on a resolved one-to-six-bridge target. Every selector acknowledgement, identity and parameter reply must match the exact Reply Network, unit, parameter, tag and total count, and only the owned target-network session is updated on the captured PCI generation |
| Physical PP SAVE/SAVE_TO_SOURCE | Direct and resolved one-to-six-bridge targets write dirty, tag-selected `direct`, `edlt`, `paged`, `ncc`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and `goc2` parameters with `none`/`checksum` and supported `lock` protection. Routed page/memory selectors, pre-read, exact-once tagged STORE acknowledgement, and complete readback must match Reply Network, unit, parameter, tag, and count. Lock protection for `direct`, `paged`, and `ncc` additionally requires a one-byte challenge from that exact route/unit/parameter plus the allocated PCI confirmation before STORE. A changed C-Bus 3 specification then runs route/unit/group/operation-correlated Save-to-NVM EXECUTE/POLL exchanges. No routed programming request is replayed; the owned session commits only on the captured PCI generation |

| ON/OFF/RAMP/TERMINATERAMP and lighting variants | Actual shared PCI for the configured network and for a topology-resolved route through one to six bridges. Confirmed direct commands schedule an immediate physical level request. A direct nonzero RAMP additionally requests the same block after the native table-snapped ramp duration plus 500 ms, so an early intermediate report does not remain the last cached observation. A later confirmed direct command for that application/group cancels its pending final request; other groups retain independent deadlines, including groups in the same status block. Only received reports update the live level; the requested target is never copied into the cache. The deferred request is skipped if its PCI generation has already been replaced. A reconnect racing after that check can still leave a read-only request on the old captured PCI; it cannot send on the replacement. Zero-duration ramps and other direct lighting commands request only the immediate report. Routed Lighting composes the retained standard SAL with the evidenced PPM source-route envelope, sends it exactly once, and accepts only its allocated PCI confirmation. It invalidates only the target network's older level on the captured PCI generation and deliberately issues no routed status request; confirmation is distinct from observed physical brightness or controller action |
| `DO` lighting methods, direct/bridged `SYNC`, `UNRAVEL`, and KEYGL5 `FactoryDefault` | Lighting aliases use the same direct or one-to-six-bridge exact-once physical backend and retain native `202 Done: object` framing. Routed SYNC uses the same strict Reply Network correlation as `NET SYNC`. UNRAVEL uses the guarded direct or one-to-six-bridge planner described above, with exact routed receipts and final target inventory. FactoryDefault sends the captured OEM control once, requires PCI confirmation plus the source-correlated unit ACK, clears stale observed-label traffic, and returns `202 Done: object` |
| GET group level | Real observed bus levels; unobserved levels return 408, never invented zero |
| SCENE RECORD/PLAY | RECORD atomically persists the configured network's observed lighting levels under the named set/scene. PLAY preflights every stored address and route before its first write, then sends a confirmed zero-time ramp for every direct or one-to-six-bridge level. Direct actions schedule physical status readback; routed actions are exact-once and deliberately do not invent one. A failed preflight sends nothing, while a later failure reports the exact completed action count. Unknown scenes retain the native 401 response |
| TRIGGER EVENT/INDICATORKILL | Actual Trigger Control SAL on application 202 for the configured network or a topology-resolved one-to-six-bridge target. Routed commands are sent once, accept only the exact PCI confirmation, and commit the selector/event to only the target network on the captured generation. No application-level reply or remote device state is claimed |
| ENABLE SET/REMOVE and GET | SET sends actual Enable Control SAL on application 203 directly or over a topology-resolved one-to-six-bridge route. Routed SET is exact-once, accepts only the exact PCI confirmation, and commits the value/event to only the target network on the captured generation. REMOVE follows C-Gate's local saved-value behavior and performs no routed physical operation; incoming values update the live cache |
| CLOCK DATE/TIME/REQUEST_REFRESH | Actual Clock and Timekeeping SAL on application 223, including `SYSTEM` date/time resolution and observed-value queries. Direct and topology-resolved one-to-six-bridge targets are supported. Routed writes are exact-once, use only the allocated PCI confirmation, and do not populate the configured network's clock cache; direct confirmed echoes remain generation-bound |
| TEMPERATURE BROADCAST | Actual Temperature Broadcast SAL on application 25 with decimal or `$19` addressing, native one-decimal input, range checks, quarter-degree wire conversion, and incoming event delivery. Direct and topology-resolved one-to-six-bridge targets are supported. A routed send is exact-once and emits a target-qualified event without polluting configured-network state |
| `AIRCON` and all 11 subcommands | The bare and `?` forms return the captured native 101 help envelope. `REFRESH`, ward on/off, zone HVAC/humidity mode, and all HVAC/humidity upper/lower/setback limit commands encode the C-Gate 3.4 application-172 SAL exactly and wait for the correlated PCI confirmation. The parser preserves native ward, zone, mode, boolean, type, level, limit and auxiliary-level bounds, including duplicate/empty zone tokens and the native saturating plant type; invalid input performs no I/O. With the optional LOGIN gate armed, the ten state-changing subcommands require authentication and `REFRESH` stays open. Incoming schedule, plant status/level and zone measurement SALs fan out to event clients without completing a pending command; no MQTT HVAC state contract is claimed. A 200 proves only confirmed broadcast delivery to the PCI, not HVAC-controller acceptance or resulting state. The configured network and topology-resolved routes through one to six bridges are supported; routed delivery is exact-once and has no application or controller readback. See `rust/testdata/fixtures/native_cgate_aircon.json` and `rust/testdata/vectors/aircon.jsonl` |
| `AUDIO` and all 19 subcommands | The bare and `?` forms return the captured native 101 help envelope. Every maintained application-205 command uses the exact observed SAL layout and strict native integer, range and arity grammar. This includes the native low-bit masking of Z-address functions, omitted/`-1` sentinels for output-common-control and output-device-status requests, the accepted output-error-code range 0–7, and the native mixed 400/200 response for mute modes 8–254. Invalid input performs no PCI I/O. With LOGIN armed, the thirteen state-changing forms require authentication; current-feed, output status/error and descriptor/feed-label requests remain open. Incoming command SAL fans out to event clients. The label/load-icon decoder repairs an observed native 3.4 defect: native advertises these events but its impossible byte-length/hex-length comparison suppresses valid A0 frames. cmqttd decodes the evidenced wire fields and marks this as an extension rather than native fanout parity. AUDIO does not define MQTT state. A 200 means correlated confirmed broadcast delivery on the active PCI generation, not audio-controller acceptance or state. The configured network and topology-resolved routes through one to six bridges are supported; routed delivery is exact-once and has no application or controller readback. See `rust/testdata/fixtures/native_cgate_audio.json` and `rust/testdata/vectors/audio.jsonl` |
| `SECURITY` and all 7 subcommands | The bare and `?` forms return the captured native 101 help envelope. `STATUS_REQUEST`, `ARM`, `TAMPER`, `RAISE_ALARM`, `EMULATE_KEYPAD`, `DISPLAY_MESSAGE`, and `REQUEST_ZONE_NAME` encode exact C-Gate 3.4 application-208 SAL and wait for correlated PCI confirmation. Application, arity, signed-integer, mode, 17-byte encoded-message, escape and zone 1–127 checks run before I/O; the native out-of-range zone array crash fails closed as 405. Native keypad values outside byte range map to `FF`. With LOGIN armed, status and zone-name requests stay open while the five control forms require authentication. All native events `0x80`–`0x98`, fixed 11-byte zone names, and both packed status reports fan out to event clients; no MQTT Security state contract is claimed. A 200 proves only confirmed broadcast delivery on the active PCI generation, not alarm-panel acceptance or resulting state. Topology-resolved routes through one to six bridges use exact-once PPM delivery and expose no application or panel readback. See `rust/testdata/fixtures/native_cgate_security.json` and `rust/testdata/vectors/security.jsonl` |
| `MEASUREMENT` and `MEASUREMENT DATA` | The bare and `?` forms return the exact native help envelope. `DATA NETWORK/228/DEVICE/CHANNEL VALUE MULTIPLIER UNITS` accepts the captured signed 16-bit value, signed 8-bit multiplier and byte unit/device/channel ranges, emits exact application-228 SAL, and waits for a correlated positive PCI confirmation. With LOGIN armed, DATA requires authentication. Incoming samples lazily create the native application/device/channel object tree, fan out code-702-shaped events, and support application `State`/`Devices`, device `State`/`Channels`, and channel `State`/`Data` GETs. Data is `value,multiplier,units,age-ms`, or `0,0,0,-1` for an existing channel without a sample. There is no MQTT Measurement state contract. A 200 proves interface delivery only, not physical sensor acceptance. Topology-resolved routes through one to six bridges use exact-once delivery with no application-level readback. See `rust/testdata/fixtures/native_cgate_measurement.json`, `rust/testdata/vectors/measurement.jsonl`, and `system_cgate_measurement.rs` |
| `IDENTIFY OFF/ON/RAMP/TERMINATERAMP` | The four maintained child paths accept application-251 groups on the configured network or a topology-resolved route through one to six bridges. OFF, ON, terminate-ramp, and native table-snapped ramp SAL are sent exactly once and require a correlated confirmation on the active PCI generation. Level accepts 0..255 or 0%..100%; duration accepts a nonnegative native signed-32-bit seconds value, an `s` suffix, or bounded minutes with `m`; `FORCE` is accepted in the native optional positions. Invalid arity, range, network, application, and route fail before I/O. Native 3.4 can return false 200 success without a packet for another dynamically accepted application; cmqttd refuses that selector. All four commands require LOGIN when armed. Incoming Identify traffic retains its source unit and fans out without defining MQTT state. See `rust/testdata/fixtures/native_cgate_remaining_applications.json`, `rust/testdata/vectors/identify.jsonl`, and `system_cgate_remaining_applications.rs` |
| `SHORTMESSAGE REFRESH/SEND` | The two maintained child paths accept application 173 on the configured network or a topology-resolved route through one to six bridges. REFRESH validates information type 0..63 and stays open under LOGIN. SEND validates total/index 0..7, information type 0..63, optional number 0..65535, optional symbol 0..255, and at most 14 UTF-8 bytes before I/O; it requires LOGIN when armed. C-Gate 3.4.0.2001's outbound SEND is malformed: it appends text as PCI ASCII-hex, overstates the extended length, swaps number/symbol flags, and can report 200 anyway. cmqttd deliberately sends a coherent repaired frame with real UTF-8 bytes, exact length, number flag `0x40`, and symbol flag `0x80`, matching the retained native inbound decoder rather than reproducing the defect. Both commands send once and require correlated PCI confirmation with no replay. Incoming messages retain source, native packed-total semantics and optional fields on event fanout; no MQTT state is defined. See `rust/testdata/fixtures/native_cgate_remaining_applications.json`, `rust/testdata/fixtures/native_cgate_shortmessage_flags.json`, `rust/testdata/vectors/shortmessage.jsonl`, and `system_cgate_remaining_applications.rs` |
| `EREPORT MESSAGE` | Accepts application 206 on the configured network or a topology-resolved route through one to six bridges and validates native message type or `RECENT`/`ERROR_REPORT`/`SEVERE`/`ACK`/`CLEAR` aliases, category 0..1023, three flags expressed as `y`/`n` or `1`/`0`, severity 0..7, unit 0..255, and optional data bytes 0..255 before I/O. The exact six-byte Error Reporting SAL is sent once and requires correlated PCI confirmation; LOGIN is required when armed. Incoming reports retain all fields and source unit on C-Gate event fanout. No MQTT Error Reporting state is invented. Routed delivery is exact-once and has no application-level readback. See `rust/testdata/fixtures/native_cgate_remaining_applications.json`, `rust/testdata/vectors/ereport.jsonl`, and `system_cgate_remaining_applications.rs` |
| `MEDIATRANSPORT` and all 21 subcommands | The bare and `?` forms return the captured native 101 help envelope. Playback, navigation, source-power, status/enumeration, total and category/selection/track name messages encode exact C-Gate 3.4 application-192 SAL and send exactly once and wait for correlated PCI confirmation. Native decimal, `0b`, `0x`, and `$` signed-integer grammar, range and reserved-operation checks, WNI values, enumeration size, quoted-name escapes, optional 11-byte text, and the captured non-ASCII-to-`FF` outbound quirk are checked before I/O. With LOGIN armed, `STATUS_REQUEST` and `ENUMERATE` stay open while controls and report injection require authentication. Incoming commands/reports preserve raw name bytes and fan out to event clients; no MQTT Media Transport state contract is claimed. Capabilities expose the `exactly-once-no-replay` policy. A 200 proves confirmed broadcast delivery on the active PCI generation, not player acceptance or state. Topology-resolved routes through one to six bridges use exact-once delivery with no application-level readback. See `rust/testdata/fixtures/native_cgate_mediatransport.json` and `rust/testdata/vectors/mediatransport.jsonl` |
| `TELEPHONY` and all 5 subcommands | The bare and `?` forms return the exact seven-line native help envelope. `CLEAR_DIVERSION`, `DIVERT`, `ISOLATE_SECONDARY_OUTLET`, `RECALL_LAST_NUMBER_REQUEST`, and `REJECT_INCOMING_CALL` encode exact C-Gate 3.4 application-224 SAL and wait for a correlated positive confirmation on the active PCI generation. Native arity, application, mode/direction and 1–16 Java-UTF-16-code-unit diversion bounds run before I/O; diversion is one literal whitespace token, with no quote or backslash decoding. The captured native malformed non-ASCII conversion is retained. With LOGIN armed, recall stays open and the four mutation forms require authentication. At Operate and Admin, all five probed forms return native 401 for absent objects before the retained Program physical-send gate; successful delivery below Program is unproven. Incoming commands and native line/call/ringing/number/Internet-request events fan out without completing a pending confirmation. There is no MQTT Telephony state contract or durable call/diversion model. A 200 proves interface delivery only, not telephone-unit acceptance. Topology-resolved routes through one to six bridges use exact-once delivery with no application-level readback. See `rust/testdata/fixtures/native_cgate_telephony.json`, `rust/testdata/fixtures/native_cgate_application_authorization_probe.json`, `rust/testdata/vectors/telephony.jsonl`, and `system_cgate_telephony.rs` |
| `DALI` | All 128 maintained paths dispatch: 103 physical leaves and 25 local/help paths. Physical coverage is 48 core, 14 emergency, and 41 specialized gateway, error-reporting, measurement, or session leaves; the six group roots and 19 catalogue/session/gateway-view leaves are local. Core commands retain exact extended-CAL EXEC/POLL/CANCEL and bounded AUTO behavior with source-correlated replies. Specialized memory uses the shared PCI programming lane, page-bounded stores, readback verification, active-generation commits, and no replay after uncertain writes. Catalogue data lives under `%PROJECT%/dali_catalogue/devices/*.json` in the durable virtual FILE repository. Sessions are volatile except explicit gateway-keyed SAVE/LOAD snapshots in cmqttd-json. `EXT_ONLY` extraction/deployment is physical. All four read-only typed extraction selectors are physical: `DALI_ONLY`, `FULL`, `REFRESH_STATUS_INFO`, and `RETRIEVE_RECONCILE`. They execute the exact retained plan, decode line masks, types, common/scene/status/emergency/LED/GTIN/serial fields and the `FULL` extended map, and atomically commit one snapshot on one PCI generation. `COND_QUICK`, `COND_EXTENDED`, and `RESCAN_FAULT` execute only their source-pinned non-remediating prefix, discard staged masks, and return 502 before `ADDRESS_UNKNOWN`; operation 2 has no allocation target/range bytes and its mask-only reply has no device-to-address receipt. Typed `DALI_ONLY`/`FULL` deployment validates its session, selection, range and gateway locally, then fails before I/O because the native ordered writes, model-field ownership, per-field readback receipts and `FULL` typed/extended atomic boundary are not retained. Mutations require LOGIN when armed. No MQTT DALI state is invented. See [the DALI guide](cgate-dali.md), `rust/testdata/fixtures/native_cgate_dali_help.json`, `rust/testdata/fixtures/native_cgate_dali_specialized.json`, `rust/testdata/vectors/dali.jsonl`, `system_cgate_dali.rs`, and `system_cgate_dali_specialized.rs` |
| LIGHTING/TRIGGER/ENABLE LABEL and UNICODELABEL | Actual checksummed dynamic-label SAL on the selected application. Supports raw/text payloads, built-in icon references, language selection, native segmented UTF-8, and start/header/chunk/commit dynamic bitmap uploads. Every fragment requires positive PCI delivery confirmation; Enable Unicode and invalid native bounds fail before transmission |
| Observed dynamic-label cache | Retains one network-wide ring of up to 4,096 exact incoming and confirmed outgoing label SAL payloads since the current connection, including source/direction and order. Outgoing append and direct-network standard/eDLT/FactoryDefault invalidation are committed only for the sending PCI generation, so an old completion cannot cross a reconnect boundary; routed operations leave this configured-network ring intact. `CMQTT LABELS` exposes the bounded observations with network scope and an unverified recipient; a unit-shaped request is a compatibility alias for the same ring. The Toolkit CLI assembles standard text/icons, Unicode, language selection and dynamic bitmaps while reporting incomplete transactions. This is explicitly not eDLT device-cache readback |
| LABEL CLEAR | Sends native standard point-to-point label-cache controls for all keys (`A3 FF 00 27`) or one key 1–8 (`A4 FF 00 66 KEY`) to unit 0–255 on the configured network or a topology-resolved one-to-six-bridge target. It uses one generation-safe exact-once send and waits only for the correlated PCI confirmation; there is no unit ACK or device readback. Native C-Gate treats either confirmation outcome as completion, so success reports command acceptance without claiming cache erasure or persistence |
| LABEL CLEAREDLT | Sends the native KEYGL5 programming control through the shared PCI exactly once on the configured network or a topology-resolved one-to-six-bridge target, requires both PCI confirmation and the direct source/tag or routed Reply Network unit/tag ACK, and reports acceptance separately from physical erasure or persistence |
| LABEL KFIGET / KFISET | Operates on configured or topology-resolved one-to-six-bridge application paths for native label-capable applications 48–95, 202 and 203. The application token is only the native `LabelSupportingApplication` class/scope gate; it is not encoded into KFIGET's fixed selector `0x1c`. KFIGET performs three route-correlated volatile parameter-`0xFF` writes before IDENTIFY attribute `0x3D`; exactly one direct-source or Reply Network route/unit-correlated `8D 3D 80` reply produces eight ordered `300` rows, while zero or multiple replies produce native 524 outcomes. KFISET accepts exactly eight values from 0 through 15, packs them low-nibble then high-nibble, and sends four correlated writes, stopping at the first failure. Every write and the GET IDENTIFY request is a generation-safe exact-once send with no transport replay. Both commands use the programming lane and optional LOGIN gate |
| `DO //PROJECT/NETWORK/p/UNIT FactoryDefault` | Sends native `A4 FF 43 B2 B2` exactly once for a database-classified KEYGL5 on the configured network or a topology-resolved one-to-six-bridge target and reports the 202 receipt separately from post-reset defaults, reboot, address retention and persistence |
| NET PINGU and GET network Units | Actual direct or one-to-six-bridge installation MMI using cmqttd's negotiated PCI checksum mode. Routed requests use native PPM source routing and exact-once transmission; only the matching Reply Network can contribute blocks. Both forms require positive confirmation and contiguous coverage of all addresses 0–255, replace only the addressed network's volatile cache, and report native sorted `302-Units=` output |
| NET PROJECT_IDENTIFY | Runs the native interface-rooted read-only discovery on cmqttd's configured shared PCI/CNI: one complete installation MMI, all nonzero states counted, address zero skipped, and level-zero IDENTIFY1/IDENTIFY2/parameter-33 discovery followed by a source-correlated six-byte parameter-35 recall from the first readable unit. It returns native `305 Project=NAME UnitCount=N` (or `Project=null`) without changing a project or physical cache. The interface type is case-insensitive and its address must exactly match the imported shared interface; another valid interface returns 502 instead of opening a second connection |
| NET SYNC and cached unit getters | Uses the configured direct-interface hint or BASIC discovery, then performs complete direct or one-to-six-bridge MMI and confirmed IDENTIFY1/2 plus bounded IDENTIFY4 for every present address. Routed replies must match the first bridge, remaining Reply Network and replying unit; other routes and direct replies are ignored. The addressed network cache is replaced atomically and its sync/duplicate events carry that network address. Eligible KEYGL5 metadata retains the configured/fresh type, non-error MMI and unique known-serial guards before the captured `0xFB`, applications and `0xFA` sequence. Direct targets use the OEM route; bridged targets require exact Reply Network/unit/selector-tag/parameter/count correlation. The first failed optional enrichment stops that sequence without replay and names its unit, field and cause. A definitive failure that leaves the connection healthy adds `300-MetadataWarning=unit <address> <field>: <cause>` to the successful identity-sync response. An incomplete exchange retires the entire PCI generation, returns a field-specific 408 and discards the staged snapshot. Cached `GET` issues no bus I/O and `Version` remains IDENTIFY2. Reconnect or transport loss clears every network's volatile presence/level cache, invalidates an in-flight snapshot before commit, returns 408, and emits no false sync-ok |
| NET SYNCNEW | Five complete MMI passes for direct and one-to-six-bridge networks. General routed discovery accepts only route-matched IDENTIFY1/2/4 replies. Direct and routed targeted modes reject an address already in the model, run the native three duplicate challenges, then read IDENTIFY1/2/4. A routed challenge accepts only the selected Reply Network, unit and parameter, requires positive PCI confirmation plus the bounded quiet window, and is never replayed; an incomplete exchange retires that PCI generation. Every result is staged, then only the addressed network's volatile cache and events are updated after a shared-PCI generation check. All forms retain native progress/result codes without creating database units. The routed target path is pinned by classfile, SIUG, exact scripted-wire and real-daemon evidence; no native routed-target completion capture or live physical-bridge acceptance is claimed |
| NET SET_PROJECT_IDENTIFY | Uppercases and packs the 1–8 character native six-bit value, obtains a fresh complete MMI on the resolved direct or one-to-six-bridge network, and selects the first unit in non-error present state one or two that supplies route-correlated IDENTIFY1 data plus exactly one valid known IDENTIFY4 serial in a complete quiet window. It sends parameter-35 STORE once with fixed tag `0x46`, accepts only the exact unit/parameter/tag acknowledgement from the selected Reply Network, and requires exact direct or routed RECALL readback before returning 200. A direct reply or neighbouring route cannot complete a bridged operation. MMI state three, multiple serial replies, unknown serials, and malformed identities are skipped; a failed or uncertain STORE/readback invalidates only that target network's older cached `ProjectName`. The verified result or same-generation invalidation is committed only while the captured shared PCI generation is still current. An uncertain exchange retires that generation without replay. The database is not changed; no live physical-bridge or power-cycle acceptance is claimed |
| NET CHECKUNIT | Active direct or one-to-six-bridge IDENTIFY4 collection through the native two-second quiet interval, with strict Reply Network correlation and native no-unit, single-unit, duplicate-unit and identity-error result forms; `*` expands from a fresh route-matched complete MMI |
| NET CLOCKS | Reads physical IDENTIFY16 summaries for the synchronized inventory. Target counts and gateway recovery use decoded `ClockGenEnable` layouts, read-modify-write CAL stores and mandatory readback; native-style per-unit failures remain visible in `120` lines even with final status 200 |
| `SET //PROJECT/NETWORK Retries 0` | Matches the owned native Toolkit-preparation exchange exactly: a ready network starts with `Retries=2`, the exact fully qualified zero form returns `200 OK: //PROJECT/NETWORK`, and subsequent `GET`/`SHOW` reads report zero. This setting is volatile and local: it sends no PCI command, emits no event, does not rewrite cmqttd's database, and resets to two after daemon restart or runtime clearing. Other non-`Address` scalar SET forms remain closed |
| `SET //PROJECT/NETWORK/p/UNIT Address DESTINATION` | Protected physical unit readdressing on the configured network or a topology-resolved one-to-six-bridge target. The service resolves the whole route before I/O, proves exactly one route-correlated source identity and an empty destination, obtains the route/source/parameter-bound one-use challenge, sends one special address STORE with no replay, and requires both PCI confirmation and the exact destination-address ACK. Only the addressed network's observed physical cache moves after the PCI-generation guard; the database address is unchanged |
| Unit identification | Source-correlated CAL replies from the physical unit |
| OEM physical memory reads | Volatile 0x41 pointer selection plus segmented RECALL; no EEPROM writes |
| KEYGL5 5.5.00 static strings and label references | Python reader checks physical identity, stable header and static-text CRC. Its network form runs one fresh serial refresh, selects supported records in numeric order, brackets each memory snapshot with physical IDENTIFY4, attaches the inventory identity only when both serials match, reads configurations sequentially and preserves mismatches as per-unit errors |

Retained CBusEdlt classfile bytecode fixes the KEYGL5 order as `0xFB` firmware,
applications, then `0xFA` WidgetGroups. Direct targets use the OEM route;
bridged targets use the database-resolved one-to-six-bridge point-to-point
route. The firmware request is one `RECALL 0xFB 9`; decoding stops at the first
NUL. The application read sends one volatile selector STORE for address 16
(`41 10 00`) and one parameter-1 RECALL of two bytes. WidgetGroups is one
`RECALL 0xFA 44`. Responses must match the direct source or exact Reply
Network/remote unit, selector tag or parameter, and total length. No phase is
replayed. A missing response faults the programming lane
until reconnect because a late untagged CAL response cannot be safely
attributed. These properties are optional for overall identity synchronization:
`NET SYNC` may still return 200, earlier values confirmed in the same sequence
remain fresh, and the failed value plus every later unrefreshed value is removed
instead of serving stale data. The database `FirmwareVersion` remains
persistent and separate from this volatile physical getter. `CMQTT
CAPABILITIES` reports `"edlt_extended_firmware": true`,
`"edlt_applications": true`, `"edlt_widget_groups": true`, and the routed
field/max-hop/delivery contract under `"edlt_sync_metadata_routed"`. The 44-byte
mapping is not a query of dynamic-label cache contents, rendering, labels or
persistence.

The optional sequence runs only for non-error present MMI state one or two and
exactly one raw IDENTIFY4 reply carrying a known serial. Live direct-network
evidence includes healthy, uniquely identified units in both states; routed
scripted evidence covers exact one/six-bridge frames and reply isolation. The complete
IDENTIFY4 reply window is the independent uniqueness guard. State three is a
native error flag and does not receive these metadata reads, nor do
addresses with zero or multiple raw replies. Multiple includes repeated identical
known replies and mixed known/unknown replies; neither shape is collapsed into
metadata eligibility. This
prevents one unit's response, or fragments from colliding units, from being
reported as another unit's metadata. The final cache commit is also bound to
the same connected PCI generation; reconnect invalidation wins over an older
in-flight synchronization.

The routed implementation is a bounded composition documented in
[`native_cgate_routed_edlt_metadata.json`](../rust/testdata/fixtures/native_cgate_routed_edlt_metadata.json).
It pins exact one/six-bridge requests and scripted route isolation without
claiming a native bridged capture or live remote-device acceptance.

Runtime levels and physical presence are not persisted. The persistent data is
cmqttd's own database format, not a Schneider SQLite database. Database PP
editing does not program the corresponding physical unit. Optional
`--cgate-unitspec DIR` supplies privately installed decoded vendor schemas for
PP INFO, defaults, local catalogue/spec/raw-memory administration and physical
PP LOAD; no vendor specifications are distributed
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

For a database-resolved route through one to six bridges, physical LOAD uses
the same standard CAL, page-aware, OEM-memory and GOC request bodies inside the
established source-route wrapper. Selector acknowledgements and responses must
carry the exact Reply Network, remote unit, parameter, tag and total byte count.
A successful load records the routed source in the owned session and changes no
direct- or target-network physical cache.

The maintained Python client wraps this surface with
`cbus-toolkit cgate physical-pp inspect|apply`. It requires the live cmqttd
capability document before locking, binds every selected parameter to one
declared programming method, stages and reads edits in one owned session, sends
one SAVE/SAVE_TO_SOURCE, and uses a distinct physical PP LOAD session for
schema-aware verification. It never retries a mutation. Apply to any loaded
schema containing an NCC parameter requires the separate routed NVM capability,
even when another method is selected for the edit. See
[`toolkit-cli/docs/physical-programming.md`](../toolkit-cli/docs/physical-programming.md)
for the JSON evidence and the live-bridge, hardware-matrix, original-Toolkit,
and power-cycle boundaries.

Physical SAVE uses captured tagged direct STORE for standard parameters, native
page selection plus tagged STORE for `paged`/`ncc`, and the OEM `0x41` address
selector plus tagged `0x42` STORE for eDLT/GIU/SGIU/DALI memory. GIU is halted
and resumed around its stores; DALI observes the native one-second settling
interval. GOC methods use parameter `0xFF` with a big-endian address prefix and
their native per-method limits. Factory and special parameters follow native
behavior and are skipped by ordinary SAVE.
Supported direct `lock` fields and physical unit readdressing use the native
unchecksummed, PCI-confirmed unlock and one-byte unit challenge reply after
selecting the relevant page and before STORE. A topology-resolved routed form
uses the same unlock CAL inside the checksummed one-to-six-bridge PTP envelope;
the challenge must carry the exact Reply Network, source unit and parameter.
Readdressing uses the vendor's fixed
`A3 20 4E <destination> <challenge>` form and recognizes its fixed destination
ACK and source NAK rather than treating them as ordinary variable-length CAL
messages. The protected STORE is never replayed after an uncertain outcome.
The retained direct request/ACK/NAK, routed challenge and Reply Network
composition, exact one/six-bridge vectors, scripted acceptance and physical
limits are recorded in
[`native_cgate_routed_unit_readdress.json`](../rust/testdata/fixtures/native_cgate_routed_unit_readdress.json).
There is no retained native routed readdress capture, live physical-bridge run
or power-cycle persistence proof. All dirty parameters are encoded
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
Routed SAVE supports standard `direct`, page-aware `paged`/`ncc`, OEM
`edlt`/`giu`/`sgiu`/`dali`, and `goc`/`gocbyt`/`goc2` transfers. Every selector,
pre-read, STORE acknowledgement and readback is route-correlated, and every ACK
also matches its STORE tag. A locked `direct`, `paged`, or `ncc` range sends the
evidenced Unlock CAL once and requires both its allocated PCI confirmation and
a one-byte challenge from the exact Reply Network, unit, and parameter. Each
stateful request is sent once; a missing or malformed challenge, confirmation,
ACK, or readback faults the programming lane until reconnect. A routed save of
changed ranges in a C-Bus 3 specification follows verified readback with the
native group-0 operation-4 Save-to-NVM EXECUTE/POLL sequence. Every status must
match the exact Reply Network, remote unit, group and operation; an incomplete
exchange faults the programming lane and is never replayed. `CMQTT CAPABILITIES`
publishes this exact scope.


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
late reply cannot be assigned to a later command. A target network can be the
configured network or a topology-resolved route through one to six bridges.
The routed form requires the exact PCI confirmation and Reply Network
route/unit/tag acknowledgement; direct and neighbouring-route replies are
ignored.

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
stale. A routed target uses the same exact-once confirmation contract but does
not discard that configured-network ring. No unit acknowledgement or
label-cache query follows, so `200 OK`
establishes native command completion only. Native C-Gate publishes no event
from the label-clear handler, so cmqttd does not invent a label-specific success
event. Native's optional high-verbosity command/response audit events are
generic to all commands and are outside this domain-event contract. A missing
confirmation makes the outcome uncertain and faults the programming lane until
reconnect.

`DO //PROJECT/NETWORK/p/UNIT FactoryDefault` accepts a database unit classified
as KEYGL5 and sends the native `A4 FF 43 B2 B2` programming control. It uses the
same strict confirmation and source/tag-correlated ACK policy as `CLEAREDLT` and
never retries automatically. A topology-resolved remote target uses the same
one-to-six-bridge Reply Network correlation and does not invalidate the local
observation ring. A `202 Done` response proves control acceptance,
not post-reboot defaults, address retention, rendering or power-cycle
persistence. The database record is not rewritten. The observed dynamic-label
ring is cleared because its entries may be stale after reset. Use the guarded
[`cbus-toolkit` workflow](../toolkit-cli/docs/edlt-factory-default.md) to bind the
request to a fresh complete inventory and expected serial.

`NET UNRAVEL //PROJECT/NETWORK [MATCHDB]` and `NET UNRAVELUNIT
//PROJECT/NETWORK UNITS [MATCHDB]` share one guarded direct or topology-routed planner.
It first completes installation MMI and known-serial identity inventory for
every present target-network address. Routed observations accept only the exact
one-to-six-bridge Reply Network. Healthy singletons stay put. All units at address 255
move, while each ordinary duplicate keeps a deterministic unit; when possible
the keeper is the serial already matching that database address, and the local
PCI is never selected for movement. `MATCHDB` prefers a unique serial-matched
database destination, then assigns the lowest free address.

Before any mutation, the planner proves local PCI parameter 66 equals `05`,
allocates a unique destination for every move, and independently identifies
every target as empty on that same route. It sends each direct or routed
selected-serial address broadcast exactly once, requires one exact route,
remote-unit and serial-correlated receipt, verifies the serial at that
destination, then repeats the complete MMI,
serial inventory, and PCI option check. Cache replacement and move/success
events commit only to the addressed network while the same PCI generation remains active. Timeout,
transport loss, unknown identities, a responding target, inadequate free
addresses, conflicting database destinations, or an incomplete final inventory
returns a bounded 408/409 without replay or rollback. Missing, ambiguous or
over-six-hop topology fails before physical I/O. `DO //PROJECT/NETWORK UNRAVEL` invokes the whole-network
form and returns native 202 framing after the same physical proof.
The route envelope and receipt rules are evidence-bound compositions recorded
in `rust/testdata/fixtures/native_cgate_routed_unravel.json`; there is no live
physical-bridge or power-cycle persistence acceptance.

`NET SET_PROJECT_IDENTIFY //PROJECT/NETWORK NAME` applies the native Java-style
one-to-eight UTF-16-unit check, uppercase fold, and six-bit range validation.
The Toolkit typed wrapper applies the same checks, including Unicode folds
whose uppercase result enters the six-bit repertoire, and emits mK quoting for
spaces, quotes, and backslashes. cmqttd pads the decoded value to eight
characters and stores the resulting six bytes in unit parameter 35 using
C-Gate's fixed transaction tag `0x46`. The resolved network may be direct or
one through six bridges. Native C-Gate accepts the matching unit ACK; cmqttd
then adds a direct or Reply-Network-correlated RECALL as a deliberate
verification step. A routed ACK or readback must match the first bridge, every
remaining hop, the selected unit, parameter 35, and fixed transaction tag; a
direct or neighbouring-route reply is ignored. Native C-Gate selects the first
present unit it can identify; cmqttd also
requires non-error present MMI state one or two and exactly one valid known
IDENTIFY4 reply over the complete bounded quiet window before STORE. Success updates only the
target network's volatile physical snapshot `ProjectName` field by decoding the verified bytes,
including the native `?`/space alias, with eight-character padding. A failed
or uncertain STORE/readback removes an older cached `ProjectName` so GET cannot
serve stale physical state. A verified cache update requires the captured PCI
generation, pointer, and connected state. Failed-write invalidation may run
after that same client retires itself, but only while its pointer and generation
are still current; it cannot clear a replacement generation's cache. A
reconnect during the operation returns 408, and the old operation cannot
repopulate the replacement generation's cache. It
does not rename, select, create, or persist a project. The separate
`NET PROJECT_IDENTIFY TYPE@ADDRESS` command is read-only
and interface-rooted, as in C-Gate 3.4: it runs one MMI, counts every nonzero
address, skips address zero while searching, identifies candidates in numeric
order, and recalls the six-byte parameter 35 from the first readable unit. It
returns a single native `305 Project=NAME UnitCount=N` response and does not
populate cmqttd's project cache. cmqttd accepts only the imported interface
already used by MQTT; a different valid interface fails closed with 502 rather
than creating a second transport. A valid SET target for another loaded
network without a resolved bridge path likewise fails closed instead of
reporting a local success. The selected native C-Gate class path, retained
routed matcher evidence, exact one/six-bridge vectors, and acceptance boundary
are recorded in
[`native_cgate_routed_project_identity.json`](../rust/testdata/fixtures/native_cgate_routed_project_identity.json).
The exact direct C-Gate 3.4 grammar, bytecode path and successful scripted wire exchange are
retained in the [native PROJECT_IDENTIFY acceptance](../toolkit-cli/research/experiments/2026-09-26/cgate-project-identify-native-acceptance.json).

## Live label reads

```sh
cbus-toolkit cgate --host 127.0.0.1 \
  edlt-labels --network //PROJECT/254
cbus-toolkit cgate --host 127.0.0.1 --timeout 30 \
  edlt-labels //PROJECT/254/p/5
```

The network inventory and `edlt-label-audit` use a 300-second per-command
timeout by default to allow a full `NET SYNC`; an explicit `cgate --timeout`
overrides this. Single-device label reads retain the 10-second default.
`serials refresh` and `serials populate --refresh` share the longer default.

The network form performs exactly one whole-network native serial refresh:
`NET SYNC` followed by `NET CHECKUNIT`. A separate read-only `NET PINGU`
checks full 0–255 MMI coverage and compares its addresses with every fresh
candidate and healthy identity. It classifies the fresh records and
selects exact supported KEYGL5 firmware 5.5.00 devices in numeric address order.
Known other families remain visible as `other_units`. Unsupported KEYGL5
firmware, unknown or ambiguous identities, successful device reads and
per-device failures are all retained in the report. Failed reads do not discard
earlier evidence. A selection, device-read or observation failure leaves
`complete=false`; the CLI still writes the JSON report and exits nonzero.
An address nominated by the fresh whole-network MMI but returning no IDENTIFY4
reply remains an unknown identity even though the native CHECKUNIT wording is
`No units detected`. The bounded inventory therefore stays incomplete instead
of excluding a possibly silent physical unit. Its `mmi_coverage` object reports
the independently observed addresses, disagreements and errors. A later PINGU
that omits an earlier unidentified candidate is recorded as discordance, not
proof of absence. PINGU failure or disagreement keeps `selection_complete=false`;
successful coverage and exact agreement are required before `complete=true`.
These are sequential observations, not an atomic network snapshot or a
guarantee that every physical device will respond to MMI.

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
Both label-read forms also make one read-only `DBGETXML` request for the saved
network and return `project_group_labels` at top level. These are the project
database's Group/TagsDLT rows, including language, flavour, type and value;
they are not attached to a physical unit or treated as displayed labels. A
The CLI probes `CMQTT CAPABILITIES` independently of the XML completion code,
because current cmqttd and native C-Gate both end successful `DBGETXML` with
344. A cmqttd reply is accepted only when that command reports
`saved_project_group_dlt_labels: true` for the requested project. Native
Schneider C-Gate is accepted when its service greeting is identified and it
rejects the cmqttd-only capability command with a 4xx response. An owned
original 3.4.0.2001 loopback capture returned `400 Syntax Error.` for
`CMQTT CAPABILITIES`, then `200 OK.` for a pipelined `NOOP` on the same
connection (`rust/testdata/fixtures/native_cgate_cmqtt_capability_vm.json`).
A malformed or unverified database response is a separate
`project_group_labels_error`, leaves physical read evidence in place, and sets
the CLI's top-level `complete=false`. The nested
`project_snapshot_complete=true` means only that the returned saved Group
snapshot was fully parsed. `device_label_inventory_complete=false` and
`device_dynamic_label_cache_readback=false` retain the physical boundary.
The network form defaults to a 300-second C-Gate command timeout because its
fresh `NET SYNC` and sequential physical reads can exceed the ordinary
10-second default. An explicit `cgate --timeout` value takes precedence.

On a fresh import, cmqttd preserves each configured Group's TagsDLT and the
Unit XML/PP element shape in its durable database. An existing database from
before this feature is upgraded once on startup; subsequent database state
remains authoritative. This also keeps PP names containing spaces as valid
`<PP Name="…" Value="…"/>` elements in `DBGETXML` network XML. Synthetic
state-file restart tests and an optional private project/state-copy acceptance
test cover the migration without a physical scan. The advertised capability is
persisted with the database:
an older durable Group with no saved TagsDLT is left untouched and reports
`saved_project_group_dlt_labels: false` because an intentional prior clear
cannot be distinguished from metadata lost by the old importer.

The [Toolkit 1.18 / C-Gate 3.4 source and loopback investigation](../toolkit-cli/docs/edlt-dynamic-cache-boundary.md)
records why this release-specific native readback operation is absent; it does
not establish a universal firmware limitation.

Physical string slots can retain old bytes after a shortened string's null
terminator. The reader reports whether the stored CRC matches the physical
bytes or Toolkit's zero-padded text projection; either must match before static
labels are accepted. The full physical-memory hash still includes those bytes.

The native physical KFI command shapes are:

```text
LABEL KFIGET //PROJECT/NETWORK/APPLICATION UNIT
LABEL KFISET //PROJECT/NETWORK/APPLICATION UNIT KFI1 KFI2 KFI3 KFI4 KFI5 KFI6 KFI7 KFI8
```

The application must be on the configured network or a topology-resolved route
through one to six bridges and must be in the native label-capable ranges
48–95, 202 or 203. The unit must fit in one byte;
each KFISET value must be 0–15. KFIGET returns `300-kfi1=...` through final
`300 kfi8=...`; KFISET returns `200 OK` only after all four writes are acknowledged.
Zero or multiple valid KFIGET replies return `524 No response.` or
`524 Too many responses.`; setup, write and transport failures use the native
application-scoped 408 envelope. `CMQTT CAPABILITIES` reports
`label_clear: true`, `label_kfi: true`, `label_management_routed: true`, the
admitted routed command list, and the six-bridge bound.

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
generation-safe exact-once sends and never enter the automatic retry table.
For a routed target, every ACK or IDENTIFY reply must match the Reply Network,
remote unit, parameter and expected payload before it can advance the
transaction. A lost confirmation makes the transaction uncertain and faults the programming
lane until reconnect. Late confirmations or identical untagged unit ACKs
therefore cannot advance a later selector, and replaying GET cannot manufacture
response multiplicity.

The retained direct commands and routed point-to-point contract are composed
and bounded in
[`native_cgate_routed_label_management.json`](../rust/testdata/fixtures/native_cgate_routed_label_management.json).
That evidence pins exact one- and six-bridge bytes and scripted correlation; it
does not claim a native remote-command capture or physical bridge acceptance.

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

The catalogue directory may also contain `cbusunits.xml`. `PP CATALOG_INFO`
reads its four metadata fields, `GET_UNIT_CATALOG` returns its XML envelope,
and `LIST_CATALOG_NUMBERS TYPE VERSION` filters its revision ranges. Unit-spec
arguments are bare filenames, symlinks are resolved with directory containment
rechecked, each file is capped at 8 MiB, and include traversal remains capped at
128 files. `PP LOAD_FROM_FILE` initializes staged parameters and raw memory from
declared defaults. `GET_RAW_DATA` renders unknown bytes as `??`; a new or
file-loaded session has a concrete default image. These commands do not read or
write a unit until a separate physical SAVE is issued.

### PP patch manifests

Create `%PROJECT%/patchsets` with `FILE MKDIR`, then upload
`%PROJECT%/patchsets/cmqttd-patches.json` with the standard base64
here-document form of `FILE UPLOAD`. If no project-specific file exists, the
service checks `patchsets/cmqttd-patches.json` in the global virtual root.
Neither spelling opens a host file.

```json
{
  "schema": "cmqttd.pp-patch/v1",
  "version": "site-reviewed-1",
  "patches": [
    {
      "unitType": "KEYGL5",
      "minFirmware": "5.5.0",
      "maxFirmware": "5.9.99",
      "catalogNumber": "5085EDLW",
      "patchVersion": "01",
      "currentPatchVersions": ["00"],
      "patchVersionParameter": 242,
      "blocks": [
        {"parameter": 114, "dataHex": "aabb", "unlock": false},
        {"parameter": 247, "dataHex": "cc", "unlock": true}
      ]
    }
  ]
}
```

The manifest is limited to 1 MiB, 1,024 patch selectors, 4,096 blocks and an
effective 136 bytes per selected patch. Each block contains 1–12 bytes, cannot
overlap, and must stay wholly inside the native patch ranges 114–241 or
247–254. Parameter 247 always takes the custom unlock path. Firmware versions
are bounded safe ASCII tokens and compare with native case-sensitive lexical
ordering, so `10.0` sorts below `9.9`. `patchVersionParameter` defaults to and,
in this schema version,
must equal decimal 242 (`0xF2`), matching `CBusUnit.N()` in C-Gate 3.4; the
0x70 control and patch-data ranges are reserved. Target patch version `FF` is
also reserved because the native pipeline uses it as its interrupted-write
sentinel; `currentPatchVersions` may explicitly admit `FF` for reviewed
recovery. A physical command is accepted
only when the current version is in
`currentPatchVersions`; a request whose target version is already installed
performs version and full-block readback, then recalls the native 0x70 enable
value. It is read-only when that value is already `9d40`; otherwise it repairs
and verifies enable. Ordinary blocks use fixed STORE tag `0x73`. Parameter
`0xF7` performs the native custom unlock and uses the returned challenge byte
as its STORE tag. A selector with `catalogNumber` requires equal saved catalogue
metadata, a deliberate stricter rule than native's missing-catalog behavior.

Run `PP WRITE_PATCH //PROJECT/NETWORK/p/UNIT VERSION SIMULATE` first. A 200
proves point-in-time manifest selection and validation only and prints its
SHA-256. Bind the physical command with
`PP WRITE_PATCH //PROJECT/NETWORK/p/UNIT VERSION EXPECT_SHA256=<64hex>`.
`SIMULATE` is recognized only as token 5; `EXPECT_SHA256` may follow it for a
review run, while a bound physical run puts it in token 5. The SHA option is a
cmqttd extension to native's otherwise ignored trailing tokens and a mismatch
fails before identity or PCI I/O. A physical 200 reports one of three exact
dispositions: the full pipeline proves every STORE acknowledgement, immediate
readback, complete second verification pass, final version and enable readback;
enable-only recovery proves matching version/blocks plus the repaired control;
and read-only recovery proves matching version, blocks and enabled control. It
does not make an
operator-supplied patch safe for a device; the manifest bytes and device
eligibility remain the operator's reviewed input. Success rechecks the manifest
digest and exact database unit record, then atomically persists decimal
`PatchVersion`, `PatchManifestSha256` and `PatchManifestVersion`.

Any failure after temporary version `FF` requires PCI reconnect and independent
inspection. An explicit recovery must use the same reviewed manifest with `FF`
deliberately admitted in `currentPatchVersions`, then reruns the full verified
pipeline. No retry or temporary-version bypass occurs automatically.

## Outstanding replacement work

The existing mock dispatches 431 command paths. The embedded service now has a
primary route for every one of the 429 non-obsolete paths, but that is **not**
evidence that every valid selector is physical or native-equivalent. `CMQTT
CAPABILITIES` returns `full_cgate_compatibility: false`; unsupported forms inside
an otherwise routed path fail explicitly before I/O. The enumerable primary
routing tracker is the executable capability matrix in
`cbus-cgate::capability_matrix` (pinned by `rust/cbus-cgate/tests/capability_matrix.rs`): 230
physical, 199 local/session, no blanket fail-closed 502 paths, and 2 obsolete
400 paths over the
431 inventoried paths, plus a separately asserted 11-row supplement for
non-inventoried service commands. Full replacement still requires:

- DALI has no whole-path gap: all 60 specialized leaves now dispatch as 41
  physical and 19 local/session operations, in addition to the 62 physical
  core/emergency leaves and six help roots. The remaining boundary is inside
  `SESSION EXTRACT` and `SESSION DEPLOY`: `EXT_ONLY` is implemented for both,
  and extraction implements every retained read-only typed plan:
  `DALI_ONLY`, `FULL`, `REFRESH_STATUS_INFO`, and `RETRIEVE_RECONCILE`.
  Extraction `COND_QUICK`, `COND_EXTENDED`, and `RESCAN_FAULT` run only their
  retained non-remediating prefix, discard staged masks and return 502 before
  `ADDRESS_UNKNOWN`; its no-payload request and mask-only response cannot prove
  a device-to-address allocation. Deployment `DALI_ONLY` and `FULL` validate
  the local session, target selection, range and gateway, then refuse before
  I/O until their ordered writes, model-field ownership, per-field readback
  receipts and combined typed/extended atomic boundary are retained. Physical
  success proves a
  correlated gateway/programming exchange, not downstream DALI-device state
  or persistence. See [the DALI guide](cgate-dali.md).

- Proprietary Schneider `patchset.zip` ingestion. The physical WRITE_PATCH
  protocol is implemented for the documented explicit manifest format, while
  the encrypted/signed vendor container, its private patch catalogue and its
  trust policy are not reproduced. PROGRAMMER and DEPLOY_QUEUE still stop at
  the first fault and retry only after an explicit RETRY.

- Physical PP multi-range failure recovery, power-loss behavior, and hardware write acceptance for
  every programming method and unit family. LOAD has full decoded-catalogue
  layout coverage plus live KEYGL5 acceptance; SAVE audits every well-formed
  writable catalogue default and has fake-PCI direct/page-aware/OEM/GOC
  write-readback acceptance. STORE failures report `after N confirmed write(s)`
  with the count of independently acknowledged ranges, and Save-to-NVM failures
  carry the same confirmed-count evidence. Factory/special parameters clear
  silently without a write while tag-filtered parameters stay dirty for a later
  matching-tags SAVE; a bare 200 covers the tag-selected subset only.
- Live routed-device and power-cycle acceptance for the `direct`,
  `paged`/`ncc`, OEM `edlt`/`giu`/`sgiu`/`dali`, and
  `goc`/`gocbyt`/`goc2` PP transfers and C-Bus 3 NVM commit; broader
  serial-address commissioning, arbitrary second-interface commissioning; and
  the remaining commissioning state transitions. The read-only interface-rooted
  `NET PROJECT_IDENTIFY` workflow
  is implemented for cmqttd's configured shared interface. The distinct physical
  `NET SET_PROJECT_IDENTIFY` parameter-35 write is implemented for direct and
  one-to-six-bridge networks with strict Reply Network correlation, one STORE,
  verified readback, target-cache generation guards, and no replay after an
  uncertain exchange.
  `NET SYNCNEW` is implemented for both direct forms and for general or targeted
  discovery across one to six bridges: five merged installation MMI passes,
  route-correlated IDENTIFY1/2/4, atomic target-network cache/event commit, and
  native `120`/`303`/`408` response envelopes. Both targeted forms run three
  exact CAL Unlock duplicate challenges. A routed challenge accepts only its
  selected Reply Network, unit and parameter, requires positive confirmation
  plus the bounded quiet window, and retires an incomplete generation without
  replay. No admitted form adds a discovered unit to the persistent project
  database.
  Direct and topology-resolved one-to-six-bridge `NET UNRAVEL`, arbitrary `NET UNRAVELUNIT` selections, and
  `DO ... UNRAVEL` use the complete-inventory safe planner described above.
  They split address 255 and larger duplicate sets into unique independently
  empty destinations, prefer unique MATCHDB addresses, and fail before writes
  when the inventory, route or target plan is uncertain. Reply Network receipts,
  per-move verification and the final inventory remain pinned to the target route;
  only the target cache/state commits after the PCI-generation guard. Acceptance
  is scripted and does not establish live bridge delivery or device persistence.
  Direct and one-to-six-bridge `NET PINGU`, `NET SYNC` identity population,
  general and targeted `NET SYNCNEW`, `DO ... SYNC`, and duplicate-aware
  `NET CHECKUNIT` are implemented with route-isolated caches. KEYGL5 firmware,
  applications and WidgetGroups enrichment, standard/eDLT label-cache clearing,
  KFI transactions and FactoryDefault now retain exact routed correlation and
  target-network cache scope. Protected unit readdressing also supports the
  configured network and topology-resolved one-to-six-bridge targets with
  route-correlated source/destination guards and exact-once STORE semantics.
  Routed PPM application commands
  cover standard Lighting (applications 48–95), Trigger (202), Enable SET
  (203), dynamic labels, Clock, Temperature, named-scene actions, and every
  maintained specialist family. Routed application commands
  use one PPM/SAL frame and exact PCI confirmation only; no Reply Network SAL,
  device acceptance, controller state, or status-readback contract is claimed.
  Guarded single-unit physical readdressing is implemented on the configured
  network and across topology-resolved one-to-six-bridge routes.
  `DO` lighting methods use the direct or routed physical lighting backend, and `DO ... UNRAVEL`
  uses the same generation-bound direct or topology-routed planner as NET.
  Direct-network clock inspection, target-count changes and gateway recovery are
  implemented for units whose decoded schema exposes a supported direct
  `ClockGenEnable` field; electrical arbitration remains outside software
  verification.
  Runtime NET catalogue lifecycle is implemented locally, and direct or
  one-to-six-bridge `NET LEARN`/`NETWORK LOCATE` use confirmed exact-once SAL.
  `NET OPEN`/`CLOSE`
  and `PROJECT START`/`STOP` change runtime state while preserving cmqttd's
  shared PCI and MQTT transport. `TOPOLOGY EXPLORE` reuses that active endpoint
  or opens supported additional descriptors transiently for physical MMI and
  project-identity discovery.
- Device-resident scene triggering beyond PP table programming, a physical
  eDLT operation that can query pre-existing dynamic-label cache contents. The maintained Audio,
  AIRCON/HVAC, Security, Measurement, Telephony and Media Transport families,
  plus the Identify control, Short Message and Error Reporting leaves, are
  implemented on the configured network and topology-resolved routes through one to six bridges; physical device acceptance and state readback remain unverified. Short Message SEND
  is a deliberate coherent repair of the retained native malformed encoder.
- Schneider repository/archive formats, full vendor CGL metadata/controller
  semantics, broader native DBSETXML Network/Unit forms, and exact native configuration,
  access, TLS, firmware, and deployment semantics. `REPOSITORY USE 1`,
  `PROJECT REPAIR`, all five portable TRANSFORM leaves, internal project
  snapshots, OID-preserving secondary-project copy/delete, the `cmqttd-json`
  repository descriptor, and all seven FILE commands are implemented. FILE and
  TRANSFORM use a durable controlled namespace and the versioned
  `cmqttd-portable-project-v14` SQLite container; they deliberately reject
  arbitrary host paths and private Schneider schemas. CGL 1.1 import/export is
  limited to the modeled label graph over known routes. DBSETXML provides
  scalar-field writes and complete Unit, Level, NetVar, Group, Application and
  Network/Interface replacement, including composed Network/Unit trees, with a
  submitted-root 301 OID receipt in the atomic local database. Retained typed
  state stays isolated across project copies and follows copy, rename, delete
  and internal archive/restore. A configured live Network admits the database
  replacement only at its existing address and interface binding, preserving
  its runtime observations without PCI I/O. Private vendor XML formats remain
  unsupported, and this bounded path is not general vendor-file interoperability.
  C-Gate TLS supports optional mandatory client-certificate verification with
  a private CA bundle. Physical `ACCESS_CONTROL CLOSE/LOCK` is implemented for
  direct application 213. The captured native TLS profile did not map a
  matching certificate subject into a user ACCESS row; broader certificate
  identity semantics and the remaining per-handler access-level matrix are
  incomplete.
- Command-by-command native interoperability and physical acceptance beyond
  the supported device profiles. Full Toolkit workflow parity remains tracked
  separately in `toolkit-cli/docs/implementation-status.md`.

## Tests

`native_cgate_pp_programmer.json` retains sanitized status/JSON/XML shapes,
owned class hashes, instruction types and the local-versus-physical boundary
from the pinned C-Gate 3.4.0.2001 jar. The oracle used a disposable loopback
daemon, loaded a temporary database network without opening it, and contacted
no C-Bus endpoint. `system_cgate_pp_programmer.rs` drives the real cmqttd
binary over TCP, exercises catalogue, raw-memory, lock/session and queue
lifecycle, verifies WRITE_PATCH manifest persistence and no-I/O SIMULATE, observes no
administrative PCI traffic, sends MQTT through the same fake PCI afterward,
and verifies that runtime locks, sessions and queues do not survive restart.
No vendor catalogue/spec XML is retained in the fixture.

`native_cgate_legacy_database.json` retains the selected-project DBTAGLIST
rows, case-insensitive filtering and exact errors; DBSET OID/path and blank
value behavior; both network-rename grammars; and the observed native
duplicate/non-numeric corruption defects. Unit and embedded-service tests pin
the repaired pre-mutation refusals, bridge/path remapping, atomic restart
persistence, configured-project boundary, incomplete and recursive OID objects,
complete typed Unit, Level, NetVar, Group, Application and Network/Interface
DBSETXML replacement, composed Network/Unit/Application trees, their 301 OID
receipts, opaque XML preservation where modeled, configured-Network binding
guards and runtime-state preservation, physical refresh/replace/update/verify
behavior, and the absence of PCI traffic for local database operations.
`toolkit-cli/tests/test_rust_cgate_interop.py` drives Unit and
Application/Group/Level forms through the production Python client.
`system_cgate_admin.rs` repeats both a typed application subtree and a complete
configured Network/Unit exchange through the running daemon while checking
zero administrative PCI traffic; `system_cgate_database_lifecycle.rs`
additionally pins restart behavior.

`native_cgate_deploy_queue.json` retains all five command help/grammar paths,
TaskGroupSummary field order, delete-type behavior, exact event JSON, owned
class hashes, and the native registry-orphan edge from the same pinned jar.
The oracle was a disposable loopback-only daemon with no project and no C-Bus
endpoint, so its retained cases used synthetic no-work and TEST-only
programmers. The cmqttd service and real-daemon regressions go further: they
verify asynchronous admitted PP/DALI execution through the PROGRAMMER worker,
per-session event filtering, first-fault termination, explicit RETRY as the
only re-execution path, volatile restart behavior, and MQTT continuity while
physical instructions share the existing PCI.

`native_cgate_config.json` retains the complete 148-entry catalogue and exact
help, grammar, scope, reset, LOAD/SAVE and no-current-project behavior from the
pinned C-Gate 3.4.0.2001 jar. A catalogue unit test compares every available
name, default, description, scope, effective mode and visibility flag with that
fixture. Service tests cover inheritance, obsolete registrations, ignored
tails, empty and multiword values, mixed response codes, the intentional
OBGET liveness repair, LOGIN classification for all five mutating verbs, atomic
rollback and restart durability without PCI traffic.
`system_cgate_config.rs` drives the real daemon over TCP with LOGIN enabled,
verifies the 122-row wildcard response, scoped values, internal snapshots,
restart readback, zero CONFIG PCI frames and MQTT continuity on the same fake
PCI. The catalogue oracle used a disposable loopback-only Java container with
no C-Bus endpoint. A separate owned loopback Java 11 capture in
`native_cgate_config_command_show_time.json` records eleven commands across
three fresh native starts: default `no`, `CONFIG SET yes` with no immediate
timing event, startup `yes` with `767` events, `CONFIG SET no` while those
events continue, and startup `no` with no timing event. The capture records a
failed unknown-key SET and validates the saved global boolean before replaying
it into the next child. The separate
`native_cgate_config_command_show_responses.json` captures 15 commands on
three fresh owned Java 11 starts plus one owned self-subscription: default yes, SET no without immediate
change, startup no with only 761 command events, SET yes without immediate
change, and startup yes with one 766 event for every line of a six-line INFO
reply. The self-subscription confirms its own 766 after the reply and shows
that native scheduling can place 761 on either side of that reply. It retains
the saved global value, error response and complete cleanup evidence.
`native_cgate_config_event_millis.json` records 13 commands across four
fresh owned Java 11 children. It pins the default `.mmm` timestamp on 761,
766 and 703 event lines, SET no with immediate GET readback but unchanged
runtime precision, saved no with whole-second timestamps after restart, and the
reverse transition to saved yes. A fourth start pins whole-second 767 timing
events when `command.show-time=yes`. The capture normalizes timestamps,
timing durations and owned session IDs, preserves event code/content/order and command replies,
and records listener ownership and complete process/work-directory cleanup.
The Rust service and daemon regressions repeat the restart and persistence
boundary on loopback. These captures prove only the three named restart
effects, not native filesystem/config-format compatibility or effects for
other catalogue keys.

`native_cgate_file.json` records the exact seven-command help, grammar,
status envelopes, path guard, binary transfer, multi-file SHA256, directory
semantics, replacement backup and failure behavior from the same pinned native
build. `system_cgate_file.rs` drives the real daemon over TCP with LOGIN
enabled, round-trips every byte value, checks 76-character download framing,
listings, digest rows, backup/delete behavior, invalid input recovery and
restart durability, and verifies zero FILE PCI frames plus MQTT continuity.
The oracle ran as a disposable loopback-only process with no C-Bus endpoint.
This evidence establishes the sandboxed cmqttd virtual-file contract, not
arbitrary host filesystem or Schneider project/archive interoperability.

`native_cgate_port.json` records the exact PORT help, syntax quirks, local
enumeration rows, native automatic-refresh 408, both UDP discovery protocols,
the synthetic CNI2 reply accepted by the pinned oracle, and PROBE response
families. `cni_discovery.jsonl` pins the legacy query/reply layout and CNI2
request CRC plus variable reply decoding. `system_cgate_port.rs` drives the
real daemon over TCP, sends both scans only to loopback, proves LOGIN policy,
host enumeration, active-endpoint refusal, refused transport handling, and a
successful isolated native echo-and-serial probe, then confirms MQTT still
uses the original shared PCI. This does not claim physical acceptance by every
serial adapter, CNI firmware, Wiser, or EtherLite model.

`native_cgate_access.json` records all five maintained registrations, exact
help and status envelopes, ordered roles, filtered line numbering, duplicate
login behavior, logout re-evaluation, SAVE/LOAD/restart behavior, and the
vendor daemon's plaintext-password, traversal, missing-load, empty-load and
unresolved-host defects. `system_cgate_access.rs` drives the real daemon with
the recovery-token gate armed, verifies native user login, redacted LIST rows,
sandboxed durable snapshots, non-mutating failures, restart authentication,
zero ACCESS PCI frames, a healthy second connection after a failed address
resolution, and the Docker-proxy transition from compatibility admission to
explicit 421/token-only recovery. The native oracle used owned C-Gate
3.4.0.2001 on six verified IPv4-loopback listeners with no C-Bus endpoint and
completed cleanup.

The sanitized `native_cgate_aircon.json` fixture records the owned C-Gate
3.4.0.2001 version/hash, exact success payloads for all eleven maintained
commands, parser boundary envelopes, and the eight report forms recognized by
the owned decoder. The `aircon.jsonl` protocol vectors pin exact unchecksummed
application payloads and canonical JSON for commands and reports.
`system_cgate_aircon.rs` drives the real daemon through its TCP C-Gate endpoint,
checks every checksummed PCI frame and correlated positive confirmation,
forces a negative confirmation to verify 502 recovery/correlation, verifies
mutation-only LOGIN gating, native parser boundaries, pre-I/O validation and
report event fanout, and sends MQTT traffic through the same PCI afterward. A
transport test proves a report received during `REFRESH` remains an event and
does not satisfy the command confirmation. This is isolated fake-PCI evidence;
it does not establish physical HVAC acceptance or readback.

The sanitized `native_cgate_audio.json` fixture records the same owned C-Gate
build and jar hash, the exact success SAL for all 19 maintained commands,
strict parser boundaries, native Z-address bit masking, sentinel parameters,
and the anomalous accepted mute range. It also records that native 3.4's
label/load-icon decoder cannot emit its advertised events. `audio.jsonl` pins
all command layouts and the intended label/load-icon repair. The
`system_cgate_audio.rs` real-daemon test checks every checksummed PCI frame,
correlated positive and negative confirmation behavior, mutation-only
LOGIN gating, pre-I/O rejection, command and repaired-label event fanout, and
MQTT continuity on the same fake PCI. This does not establish physical audio
controller acceptance, readback, or routed command support. A service
regression replaces the shared PCI after an Audio confirmation is allocated
and proves the retired generation cannot return success.

The sanitized `native_cgate_security.json` fixture records the same owned
C-Gate build and class hashes, exact success payloads for all seven commands,
parser boundaries, the native zone-index failure that cmqttd closes, and the
complete inbound opcode/report layout. `security.jsonl` pins 52 command and
event/report JSON/wire cases. `system_cgate_security.rs` drives the real daemon
against fake PCI and MQTT, checks authentication, exact frames, pre-I/O
rejection, positive/negative confirmation recovery, Security event fanout and
MQTT continuity. A transport regression injects a Security event while a
request confirmation is pending and proves the event cannot complete that
request. A service regression replaces the shared PCI while a confirmed
Security request is pending and verifies that the retired generation cannot
return success. This evidence does not establish physical alarm-panel
acceptance or readback.

The sanitized `native_cgate_measurement.json` fixture records the exact owned
C-Gate build and class hashes, DATA grammar and bounds, five native wire
examples, the incoming 702 event, and dynamic GET behavior. The four
`measurement.jsonl` vectors pin signed extremes and native field ordering.
`system_cgate_measurement.rs` drives the real daemon against fake PCI and MQTT,
checks LOGIN gating, exact confirmed frames, every captured error boundary,
NAK recovery, event fanout, dynamic object GETs, and MQTT continuity. The
oracle and tests use disposable projects and establish no physical
Measurement-device acceptance.

The sanitized `native_cgate_mediatransport.json` fixture records the owned
C-Gate build and all 21 command-class hashes, exact payloads, parser bounds,
inbound event layout, and the native non-ASCII name quirk.
`mediatransport.jsonl` pins typed JSON and wire cases for every command plus
empty, maximum and raw-byte names. `system_cgate_mediatransport.rs` drives the
real daemon against fake PCI and MQTT, checks every command family member,
authentication, no-I/O rejection, positive/negative confirmation recovery,
event fanout, explicit absence of invented MQTT state, and MQTT continuity. A
service regression replaces the shared PCI while a confirmed request is
pending and rejects the retired generation. This evidence does not establish
physical media-device acceptance or readback.

`cbus-transport` tests pin direct and one-to-six-bridge routing for standard
recall/tagged STORE, page-aware recall, page selection, cross-page tagged
STORE, OEM-memory and GOC selectors/writes/readback, plus the native
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
The routed-topology suite pins Schneider's one- and two-bridge PPM/PTP bytes,
native smart-mode Reply Network decoding, forward/reverse `DBNETWORKPATH`,
wrong-route rejection, per-network cache replacement, reconnect invalidation,
and remote sync event addresses. A real `cmqttd` process is driven through its
TCP C-Gate endpoint against the scripted PCI and in-process broker: remote
PINGU plus general and targeted SYNCNEW complete while direct-network lighting
reaches MQTT. Wrong-route MMI, duplicate and identity replies are ignored, and
the three routed duplicate challenges are emitted exactly once. Routed
`NET SET_PROJECT_IDENTIFY` then performs one route-correlated STORE plus
readback while another direct-network lighting observation reaches MQTT.
The same daemon then sends exact one-bridge Lighting, `DO` Lighting, Trigger
EVENT/INDICATORKILL, and Enable SET PPM/SAL frames once each; direct-network
MQTT observations continue through the shared reader, and Enable caches remain
separate by network. Unsupported application and unresolved-network forms emit
no PCI frame. Loss of the single plain-TCP CNI produces the expected clean
daemon shutdown. The
[routed project-identity evidence](../rust/testdata/fixtures/native_cgate_routed_project_identity.json)
records the selected native class path, retained route matrices, exact vectors,
and the remaining physical-bridge boundary. The
[routed application-control evidence](../rust/testdata/fixtures/native_cgate_routed_application_control.json)
records the retained direct SAL and routed-envelope composition, exact
one/six-bridge vectors, PCI-confirmation-only receipt, target-network state
scope, and unsupported readback boundary.
The retained [native topology acceptance](../toolkit-cli/research/experiments/2026-09-26/cgate-bridged-topology-native-acceptance.json)
pins C-Gate 3.4.0_2001's forward/reverse COMPACT and OID database paths on
disposable loopback endpoints, including the exact 408 result when the
conventional bridge unit is absent and continued success after the distinct
`/p/42` interface unit is deleted. The companion
[`DBNETWORKPATH` grammar acceptance](../toolkit-cli/research/experiments/2026-09-26/cgate-dbnetworkpath-grammar-native-acceptance.json)
pins zero-hop failure, default and unknown-mode OID output, ignored trailing
tokens and exact missing-address responses on the same selected runtime. The
companion [bridged SYNCNEW evidence](../toolkit-cli/research/experiments/2026-09-26/cgate-bridged-syncnew-readonly-evidence.json)
pins C-Gate 3.4's generic five-pass `CBusBridgeNetwork` classfile path, its
three optional-address duplicate commands and a selected-version one-hop MMI
request. Published SIUG routing plus scripted reply tests supply the strict
Reply Network success behavior. No physical bridge, retained native routed
target completion, persistent native unit creation, or routed-write acceptance
is claimed.
`cbus-cgate` service tests cover durable reload, corrupt-file preservation,
rollback, session ownership, unsupported hardware rejection, fragmented command
input during events, native-shaped command-session enumeration/tagging,
`EVENTS` alias state, reply-before-close `QUIT`/`EXIT`, disconnect cleanup,
first-token event parsing and the native session-local partial-mode effect after
selected 408 replies in
[`native_cgate_session_selectors.json`](../rust/testdata/fixtures/native_cgate_session_selectors.json),
specification-backed staged reset success/failure/ownership/persistence,
schema layout decoding and input bounds. The retained owned C-Gate 3.4.0.2001
[session capture](../toolkit-cli/research/experiments/2026-09-25/cgate-session-native-acceptance.json)
pins those statuses, envelopes, aliases and closure semantics on disposable
loopback listeners with no project or physical network configured.
The decoded vendor catalogue is optionally audited through `CBUS_UNITSPEC_DIR`.
The real cmqttd system tests perform physical PP LOAD and SAVE against a scripted
PCI, check standard and OEM values, dirty/tag selection, read-modify-write
encoding, acknowledgements, readback, and the exact C-Bus 3 NVM commit sequence,
and verifies that C-Gate and MQTT retain one PCI connection while lighting events
continue through the same transport. The routed regression additionally checks
one-bridge direct LOAD/SAVE, neighbour-route rejection, exact-once STORE,
readback, routed C-Bus 3 EXECUTE/POLL, target-session scope, and MQTT continuity;
transport and golden-vector tests pin the one- and six-bridge bounds. The same
test pins direct and routed
`DO` lighting methods to their physical SAL packets, the routed Lighting,
Trigger, and Enable exact-once slice, shared-reader MQTT continuity and
target-only cache behavior. It exercises `DO ... SYNC` and verifies the guarded
`DO ... UNRAVEL` physical planner. It also pins source-correlated
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

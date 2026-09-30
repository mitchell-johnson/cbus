# CLI reference

The Python `cbus-toolkit` application is installed separately; see [toolkit.md](toolkit.md). Run `cargo build --release --workspace` from `rust/` to create the Rust binaries under `rust/target/release/`. Use each program's `--help` output as the option-level authority.

## Program selection

| Need | Program | External effect |
| --- | --- | --- |
| Edit projects, commission networks, configure supported units, or use C-Gate | `cbus-toolkit` | Depends on subcommand: files, server state, or hardware |
| Decode one serial frame | `cbus-tools decode` | None |
| Read a Toolkit backup or project XML | `cbus-tools dump-labels` | Reads locally; optionally writes JSON |
| Query one unit or discover units | `cbus-tools interrogate` | Sends requests through a TCP CNI |
| Discover CNI2/Wiser endpoints | `cbus-toolkit interface discover-cni` / `scan-cni`, or `cbus-tools cni-discover` / `cni-scan` | One bounded IPv4 UDP query per selected route; does not open TCP or C-Bus |
| Verify a selected-serial plan | `cbus-tools serial-verify` | Sends bounded read-only MMI and IDENTIFY traffic |
| Apply a selected-serial plan | `cbus-tools serial-apply` | Writes a durable local journal, sends one address broadcast, then reads state |
| Bridge C-Bus and MQTT/Home Assistant | `cmqttd` | Long-running network and MQTT traffic; accepts control messages |
| Emulate a PCI/CNI endpoint | `cbus-simulator` | Opens a local TCP listener |
| Emulate the C-Gate 3.4 command surface | `cgate-mock` | Opens a TCP listener and mutates in-memory state |
| Recheck committed compatibility vectors | `cbus-vector-check` | Reads local JSONL vectors |

### Toolkit preference effects

`cbus-toolkit cgate --preferences STATE.json` uses 127.0.0.1 for an empty or
`LOCAL` Default Site when `--host` is omitted. A named site is rejected, so
pass `--host` for it. `thermostat-temperature convert --preferences STATE.json`
selects units from the low byte of `TemperatureUnit`. The Toolkit preferences
feature document lists what each of the other 38 preferences does.

### Native database XML file workflow

For a saved Group/eDLT project label or another supported database object, use
`cbus-toolkit cgate --host HOST database get-xml PATH --project NAME --output
new.xml`. It creates a new UTF-8 file and emits the exported document hash.
Review a separate edited copy, then use `database set-xml PATH edited.xml
--project NAME --expect-current-sha256 EXPORTED_HASH --readback`. The guard
performs a fresh read before one native `DBSETXML` here-document; it is not an
atomic compare-and-swap. Inspect the accepted receipt and the native-mapped
readback, then explicitly `cgate project save NAME` on original C-Gate. The
command does not program physical eDLT cache labels. See
`toolkit-cli/docs/native-database-xml-files.md` for bounds and acceptance.

### CNI interface discovery

Run `cbus-toolkit interface discover-cni` for the Python workflow or
`cbus-tools cni-discover` for the Rust equivalent. Defaults bind and broadcast
on UDP 20050; use `--bind` to select a local adapter. Both send the exact
captured query once, enforce a monotonic timeout and datagram cap, decode only
the fixed 30-byte reply shape, hide product id 2 unless `--include-hidden` is
set, and emit `cbus-cni-discovery-v1` JSON. Use a returned `endpoint` only after
review; discovery does not prove TCP reachability, exclusive ownership,
identity authenticity, physical C-Bus attachment or absence after zero replies.

For several explicit adapter/subnet pairs, use `cbus-toolkit interface scan-cni
--probe BIND_IPV4@DESTINATION_IPV4` or `cbus-tools cni-scan --probe
BIND_IPV4@DESTINATION_IPV4` with 1–16 unique `--probe` options. For
example, `--probe 192.0.2.10@192.0.2.255 --probe
198.51.100.10@198.51.100.255` sends one captured query per route, in order.
The sum of configured per-route reply windows is capped at 300 seconds. Read
each `cbus-cni-multi-discovery-v1` probe outcome: `devices_observed`,
`no_reply_by_deadline`, malformed/hidden filtered replies, `datagram_limit`, or
`transport_error`. A failed probe does not suppress later ones; a failed send
has unknown delivery and is never retried. `scan_complete` excludes caps and
transport errors. `absence_proven` and `ownership_checked` remain false even
after every reply window completes. Both CLIs also accept `--auto-adapters`
to derive directed broadcasts from active IPv4 adapters and `--plan-only` to
preview them without sending. Python needs the optional `network` extra;
Rust uses its host adapter library. Automatic scans constrain each socket to
its selected OS adapter before sending and confirm the socket option by
readback; a failed pin is a per-route `transport_error` and no unpinned
fallback is sent. Check `egress_interface_constraint_applied` and each
observation's `egress_interface_constraint` for the option and index.
`egress_interface_verified=false` still means the physical outbound packet
was not observed. These commands do not scan arbitrary IP
ranges or implement native C-Gate `PORT CNISCAN2` status and TCP ownership
behavior. See `toolkit-cli/docs/cni-discovery.md`.

### Guarded physical PP programming

Use `cgate physical-pp` against cmqttd when a task needs a physical PP LOAD,
edit, SAVE/SAVE_TO_SOURCE, and fresh physical verification. Supply exactly one
schema method and only fully qualified physical units:

```sh
cbus-toolkit cgate --host HOST physical-pp inspect \
  //PROJECT/NETWORK/p/UNIT --method edlt
cbus-toolkit cgate --host HOST physical-pp apply \
  //PROJECT/NETWORK/p/UNIT --method edlt --set NAME VALUE --journal JOURNAL.json
cbus-toolkit cgate --host HOST physical-pp recover --journal JOURNAL.json
```

The command derives the network lock, refuses method mismatches before PP SET,
does not retry a mutation, and creates a second PP session after a confirmed
save. Inspect `physical_programming_evidence` on failure. `saved=false` with
`save_outcome_uncertain=true` requires independent inspection before any new
write. A save requires `--journal`, created and fsynced before the save; an
unresolved journal for the unit refuses later saves until `physical-pp recover`
classifies every range `expected` or `unchanged` from a read-only fresh LOAD. Even a successful fresh readback leaves power-cycle persistence and the
hardware method matrix false. Use `--dry-run` only for a temporary physical
load/stage/readback; it is not offline. Full syntax and evidence are in
`toolkit-cli/docs/physical-programming.md`.

For low-level RECALL, IDENTIFY or WRITE through an authoritative legacy
XML/CBZ topology, use the typed PCI route form:

```sh
cbus-toolkit pci --host HOST --local-unit LOCAL routed-write \
  UNIT PARAMETER HEX --expected-ack-tag TAG --project-file PROJECT \
  --project-name NAME --source-network SOURCE --target-network TARGET
cbus-toolkit pci --host HOST --local-unit LOCAL routed-recall \
  UNIT PARAMETER COUNT --project-file PROJECT --project-name NAME \
  --source-network SOURCE --target-network TARGET
cbus-toolkit pci --host HOST --local-unit LOCAL routed-identify \
  UNIT ATTRIBUTE --project-file PROJECT --project-name NAME \
  --source-network SOURCE --target-network TARGET
```

Each derives the outbound route and independent return path from the project,
rejects ambiguous, cyclic, disconnected, unsupported, stale, or over-depth
topology before sending, and transmits once. Raw `--bridge` plus
`--expected-source/--expected-destination/--expected-route` remains available.
Neither successful form proves live bridge delivery or device origin. WRITE
does not prove parameter commit, readback, reboot behavior or nonvolatile
persistence. See `toolkit-cli/docs/pci-routed-recall.md`,
`toolkit-cli/docs/pci-routed-identify.md` and
`toolkit-cli/docs/pci-routed-write.md`.

### eDLT Measurement scaling

Use exact signed mantissa/exponent pairs when the stored value is already
known. Use `--gain-value` or `--offset-value` with
`--measurement-culture invariant|en-NZ|de-DE|fr-FR` when matching the original
Toolkit text editor. Omission selects the stricter `canonical` grammar. Toolkit
culture profiles can wrap an editor exponent into a signed byte, so inspect
`composite_conversions.*.editor_exponent`, `.exponent`, `.exponent_wrapped`,
and `.display_value` before applying a plan. The same options exist on offline
`edlt measurement-plan` and native database-unit `edlt-measurement` commands.
See `toolkit-cli/docs/edlt-measurement.md` for the pinned decimal/group
separators, blank/zero rules, and the non-finite safety boundary.

### eDLT Measurement/Percentage parent composition

Use a caller-supplied lifecycle cache to compose both controls through one
retained load/save plan:

```sh
cbus-toolkit edlt parent-form-plan snapshot.json \
  --metadata lifecycle-cache.json \
  --page 1 --position 1 --device-id 42 --channel 3 \
  --gain-value '1.5' --measurement-culture en-NZ \
  --wake-mode primary-event --group 42 --level-percent 50
```

The native equivalent is `cgate unit ... edlt-parent-form` and accepts database
destinations only. Add the unit-level `--dry-run` before the subcommand to
stage and verify without `SAVE`. `--level-percent` uses the original Decimal
conversion and is valid only when the resulting wake mode exposes the level
panel. `--action-selector` uses the same stored byte under trigger mode and is
mutually exclusive with the percentage.

Read `phases.controls`, `cross_control`, `preservation` and `write_order` in
the JSON. The plan pins the original construction, asynchronous worker,
selection-binding and save sequences, but reports
`native_parent_form_executed=false`. The complete original GUI and physical
behavior are outside this bounded workflow. See
`toolkit-cli/docs/edlt-parent-form.md`.

### eDLT ordered parent transaction

Use an ordered JSON array when one KEYGL5 5.5.00 edit contains distinct
supported widget or direct settings panels:

```sh
cbus-toolkit edlt parent-transaction-plan snapshot.json \
  --metadata lifecycle-cache.json --operations operations.json
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-parent-transaction \
  --metadata lifecycle-cache.json --operations operations.json
```

The array requires two through 22 operations and at least one widget,
SceneManager sequence or Reset. It
accepts Measurement, Lighting, Enable, Fan, HVAC, Multi Level, Room Courtesy,
Scene, Shutter, Time/Date, Timer, MRA Zone Control, Source Select and Source
Control and Blank widgets, plus activation, General, Display, Standby, Colours,
Navigation, Quick Status, Page Control and distributed MRA globals. Widget operations
use each standalone editor's exact option names; activation uses
`level_percent` or `action`. Percentages must be quoted canonical fixed-point
text. Overlapping complete records, a duplicate settings owner, conflicts with
the second Time/Date slice, page-mode conflicts, missing group or effective
dynamic-variant evidence, unknown fields and duplicate JSON keys fail before PP mutation.
Order enabling dependencies before their consumers: Display before an HVAC or
MRA icon edit, Standby before idle Colours controls, and a retained or newly
created MRA widget before `mra-globals`. Multiplexer and zone have independent
single owners. Omitted MRA globals come from the first existing record before
type conversion; stored standby records and raw multiplexer3 remain supported
inside this retained parent path.
One `scene-manager` operation accepts the standalone retained SceneManager's
ordered nested operations and requires a complete
`cbus-edlt-scene-manager-cache-v1`. Put Applications before SceneManager and
SceneManager before every Scene widget. Incomplete capacity outcomes and a
second scene-graph owner fail before PP mutation.

Inspect `operation_results`, `operation_metadata_dependencies`, `ownership`, `transaction_guards`,
`preservation`, `execution_counts` and `write_order`. Successful non-dry-run
native execution uses one parameter-write pass, complete readback and database
save. A save exception or interruption is never retried: inspect
`edlt_parent_transaction_evidence`, where `saved=false` means persistence was
not confirmed and `save_outcome_uncertain=true` keeps the database outcome
explicit. The plan has retained original evidence for each component, while
`native_multi_edit_parent_form_executed=false` and physical behavior remains
unverified. Applications/Corridor are admitted with a complete cache. Reset is
also admitted only as operation 1 with that complete cache and exact raw PP
strings; later operations bind to its fresh graph. The automatic resolver can
derive existing ordered lists and raw strings from DBGETXML, refuses missing
list objects, and can combine that state with automatic SceneManager metadata.
Reset after the first position and duplicate Reset fail before PP I/O. Blank
otherwise composes as a whole-slot retained selection; immediately after
Reset, a contiguous Blank prefix receives exact fresh-graph receipts and any
later or interleaved Blank fails closed. SceneManager can edit
the retained or Reset-fresh graph and shares the one terminal CRC/write/readback
path; the automatic parent metadata resolver can establish its cache and exact
Trigger application/group/action objects before the same parent PP save.
Complete original SceneManager/parent form binding
remains outside this bounded composition. See
`toolkit-cli/docs/edlt-parent-transaction.md`.

Use `lifecycle.crc_fields_calculated` to confirm the single five-field CRC
pass. `phases.crc` is a changed-only delta and may omit a field whose stored
value was already correct.

To derive the lifecycle facts from one exact native project snapshot instead
of a hand-authored cache:

```sh
cbus-toolkit edlt parent-transaction-plan snapshot.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations operations.json
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-parent-transaction \
  --auto-metadata --exclusive-project --operations operations.json
```

The first command requires the PP file to match the selected XML unit exactly.
The second requires an exact selected-network lock address, a closed project
and exclusive caller ownership. Review
`planned_creations`, `metadata_cache`, `static_labels` and the nested parent
plan. Applying creates a backup, adds missing applications/groups for all
admitted operations and exact SceneManager actions in dependency order, stages
PP once, performs one PP SAVE and one target PROJECT SAVE, then
reloads and verifies. These native operations have no shared atomic commit.
Only a failure before PP SAVE is rolled back automatically. After either save
starts, inspect `edlt_parent_metadata_evidence`; never retry an uncertain
operation. Consumed DYNAMIC/FONT/ICON image facts fail closed because
DBGETXML does not include project images or Toolkit's DLTP image index. See
`toolkit-cli/docs/edlt-parent-metadata.md`.
For Applications/Corridor/Reset, also inspect
`automatic_ordered_application_cache`: XML child order and TagName are a
database view; Toolkit registry display/sort preferences are unobserved and no
missing list object is created.

### Native dynamic-label cache clear

Use the typed native command to request all cached labels or one key be cleared
for one unit:

```sh
cbus-toolkit cgate label cache-clear //PROJECT/254/56 5
cbus-toolkit cgate label cache-clear //PROJECT/254/56 5 --key 3
```

The application path must resolve to native label-capable ID 48–95, 202 or
203; the unit is 0–255 and the optional key is 1–8. Successful native
acceptance reports that a PCI confirmation was received, while delivery
outcome, cache erasure, persistence and device readback remain unverified.
This is native `LABEL CLEAR`, separate from the empty-SAL `cgate label clear`
action and the guarded KEYGL5 `cgate edlt-label-clear` workflow.

### Live eDLT label inventory

Against cmqttd's embedded C-Gate service, inventory the supported physical
KEYGL5 5.5.00 devices on one network with:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-labels --network //PROJECT/254
```

The command runs one network serial refresh (`NET SYNC` and `NET CHECKUNIT`),
selects supported devices in numeric address order, reads their static
configurations sequentially, then queries `CMQTT LABELS` once for the network.
Physical IDENTIFY4 reads bracket each selected memory snapshot; the fresh
inventory identity is attached only if both physical serials match it. A
mismatch remains a per-unit error without stale identity attachment. Its JSON
preserves unsupported, unknown and ambiguous records plus successful reads and
failures. `complete: false` produces a nonzero exit status without discarding
the partial report. Dynamic-label observations are a transient,
network-wide and recipient-unverified traffic ring, never a per-device result.
Unit-shaped `CMQTT LABELS` requests are compatibility aliases for the same
ring. Physical dynamic-label cache readback remains unavailable and false.

Create or compare a deterministic static-label acceptance baseline with:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-label-audit //PROJECT/254 --write-baseline labels.json
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-label-audit //PROJECT/254 --baseline labels.json --mode configuration
```

The audit joins stable, serial-bound memory images with each unit's 44-byte
`WidgetGroups` mapping from the same initial synchronization. `exact` compares
the complete physical-image digest, `configuration` the decoded label-bearing
records, and `labels` the text/reference/placement view; identity and mapping
changes fail all modes. Incomplete reads return nonzero and cannot create a
baseline. Dynamic-label observations are retained only as diagnostics and do
not enter fingerprints. See `toolkit-cli/docs/edlt-label-audit.md`.

### Retained eDLT scene names

For a KEYGL5 / 5055EDL 5.5.00 database unit, put ordered SceneManager
operations in a JSON array. Use `set-name-text` to allocate and bind a name,
or `set-name-index` with index 255 to clear only the scene's reference:

```json
[
  {"op": "set-name-text", "scene": 1, "text": "Evening"},
  {"op": "set-name-text", "scene": 2, "text": "Evening"},
  {"op": "set-name-index", "scene": 3, "index": 255}
]
```

Preview the retained state or final PP plan before using the native database
workflow:

```sh
cbus-toolkit edlt scene-manager-state snapshot.json \
  --metadata scene-cache.json --operations scene-operations.json
cbus-toolkit edlt scene-manager-plan snapshot.json \
  --metadata scene-cache.json --operations scene-operations.json
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-scene-manager \
  --metadata scene-cache.json --operations scene-operations.json
```

To derive existing metadata from one exact native project snapshot:

```sh
cbus-toolkit edlt scene-manager-plan snapshot.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations scene-operations.json
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-scene-manager \
  --auto-metadata --exclusive-project --operations scene-operations.json
```

The automatic parent and SceneManager paths also accept
`--display-preferences prefs.json` (`cbus-edlt-display-preferences-v1` registry
DWORDs for the source-pinned FormattedDisplay/SortMode list model) and the
pair `--toolkit-dltp-dir APP_DIR --toolkit-dltp-sha256 HEX`, which resolves
`ICON` dynamic labels from a SHA-256-bound Toolkit DLTP index. `DYNAMIC` and
`FONT` still fail closed. `cbus-toolkit edlt display-lists --project-xml
project.xml --network 254` shows the lists read-only. See
`toolkit-cli/docs/edlt-display-preferences.md`.

The automatic path requires all project networks closed and idle. Retained
getter accesses can add application202 as `Trigger Control`, an exact non-255
trigger group as `Group N`, and exact missing actions as `Action Selector N`
with Address=Value=N and four blank variants. Apply with a reviewed backup:

```sh
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 edlt-scene-manager \
  --auto-metadata --exclusive-project --backup-project SCBACKUP \
  --operations scene-operations.json
```

Apply rechecks the exact source before backup and its semantics afterward,
creates and reads back all planned objects, stages PP with connected rollback, then records
separate PP SAVE and PROJECT SAVE results and verifies after reload. Automatic
rollback ends before the first applicable PP or target-project save. Never
retry a lost or interrupted save reply.
Consumed image-dependent existing labels fail closed; use the manual cache
path only for independently established project-image or DLTP facts.
The separate interactive blank Add dialogs are not implemented; the action
dialog's source-backed allocator is first-free 0..254 with editable `Level N`.

Allocation is case-sensitive and ordered. It reuses the first exact text slot,
otherwise chooses the highest whole-unit unreferenced slot. The selected
scene's old reference is released before its new allocation; earlier
operations and unrelated scene, page and widget references remain reserved.
Text is nonblank, contains no NUL and is at most 63 UTF-8 bytes. Inspect
`static_text.overlay_changes`, `static_text.allocations`,
`static_text.fingerprint`, and `scene_pointers` in the result. Exhaustion
fails before any PP write or SAVE. This workflow edits database PP only; it
does not verify a physical display or complete SceneManager form behavior.

### Invoke a retained eDLT scene binding

Use the exact identity-bearing `cbus-cli-parameters-v1` export and SceneManager
cache to resolve a stored Trigger Control group/action pair and submit one
event. A bare parameter mapping is rejected before client construction:

```sh
cbus-toolkit cgate --host 127.0.0.1 edlt-scene-trigger snapshot.json \
  --metadata scene-cache.json --network //PROJECT/254 --scene 1 --force
```

Preflight rejects missing or disabled bindings and bindings absent from the
supplied cache before connecting. The command sends exactly one
`TRIGGER EVENT //PROJECT/NETWORK/202/GROUP ACTION` request, optionally with
`FORCE`, and never retries or changes PP data. A terminal `200` is native
acceptance only. A complete non-408 4xx is a protocol rejection; `408`, all
5xx, transport loss and unsupported replies remain outcome-uncertain. Every
submitted result says that a device side effect is possible. The event is
group-scoped rather than point-to-point. The caller-supplied source/cache are
not compared with a physical unit; binding freshness, physical scene execution
and persistence remain unverified. See `toolkit-cli/docs/edlt-scene-trigger.md`.

### Live eDLT WidgetGroups mapping

Consume cmqttd's physical synchronized KEYGL5 mapping with:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-widget-groups //PROJECT/254/p/5
```

The command validates the exact unit path, requires a successful network-wide
`NET SYNC`, then accepts one exact final status-300
`GET //PROJECT/NETWORK/p/UNIT WidgetGroups` response. The payload is exactly 44
canonical unsigned decimal bytes joined by commas. It is an opaque static
mapping from the physical synchronized cache, not dynamic-label cache readback.
The native request is one OEM `09 00` parameter-`0xFA` recall of 44 bytes.
The JSON keeps rendering, persistence, and network atomicity false. It records
that persistent device configuration stays unchanged while the metadata read
writes a volatile OEM selector. It uses cmqttd's shared CNI connection and
never opens a direct one. Query `CMQTT
CAPABILITIES`; this extension is advertised as `edlt_widget_groups: true`.

## cbus-tools

### Decode

```sh
rust/target/release/cbus-tools decode 05013800790148
rust/target/release/cbus-tools decode --client '\053800790149g'
rust/target/release/cbus-tools decode --no-checksum --not-strict FRAME
```

The default direction is PCI-to-client. `--client` selects client-to-PCI. `--no-checksum` relaxes checksum validation, and `--not-strict` enables lenient decoding. Output contains consumed byte count, a debug packet representation, and stable packet JSON. A syntactically accepted invocation can print `packet: None`; inspect the decoded result instead of using exit status alone to decide whether the frame was valid.

### Dump project labels

```sh
rust/target/release/cbus-tools dump-labels project.cbz
rust/target/release/cbus-tools dump-labels --pretty 2 --output labels.json project.xml
```

Input may be a one-file Toolkit `.cbz` archive or bare project XML. Output is keyed by network address and includes network metadata, applications, groups, units, catalogue and serial fields, plus parsed group-address channel mappings. The command exits nonzero for unreadable archives, malformed XML, or required project fields that cannot be parsed.

### Interrogate units

```sh
rust/target/release/cbus-tools interrogate --tcp 192.168.1.10:10001 --unit 5
rust/target/release/cbus-tools interrogate --tcp 192.168.1.10:10001 --discover --max-address 37 --timeout 5
```

Choose either a single `--unit` or `--discover`. Discovery scans addresses from zero through `--max-address`, inclusive. This command opens the given TCP CNI, initializes it, and sends CAL identify and recall requests. It is active bus traffic even though it is intended to read attributes.

### Selected-serial verify and apply

```sh
rust/target/release/cbus-tools serial-verify \
  --pci 192.0.2.10:10001 --plan selected-plan.json --timeout 300
rust/target/release/cbus-tools serial-apply \
  --pci 192.0.2.10:10001 --plan selected-plan.json \
  --journal /operator/recovery/selected-plan-attempt.json \
  --attempt-store /operator/commissioning-attempts --timeout 300
rust/target/release/cbus-tools serial-verify \
  --pci 192.0.2.10:10001 \
  --journal /operator/recovery/selected-plan-attempt.json --timeout 300
```

Both commands require the numeric IP and port to match the validated plan before connecting. Each `--pci` invocation opens a direct TCP socket. They take the same nonblocking host-local endpoint lease as the Python selected-serial coordinator, from before connection through the final observation; a competing cooperating CLI process exits before PCI I/O or journal creation. The lock is automatically released if the process exits or crashes. It does not exclude `cmqttd`, a controller on another host, or software that ignores the lease, so the operator must still establish exclusive ownership of the CNI. Verify is read-only and exits zero only when a fresh, bookended observation equals `expected_after`. Apply first requires that exact fresh-before inventory, then immediately recalls local option 66 and requires `05`. It exclusively creates and fsyncs a hidden SHA-256 canonical-plan attempt marker, then the main journal with conservative send intent, before invoking the one-shot write on the same PCI connection. With `--attempt-store`, the marker goes in the existing shared directory and cooperating processes refuse the same canonical plan across different journal directories. Without it, the marker is beside the journal as before. Preserve both files. A preexisting marker is refused before connecting; concurrent claim races are stopped by exclusive marker creation before send. The marker path appears in successful apply JSON as `attempt_identity` and may be passed to `serial-verify --journal` if a crash left no main journal. All operators must use the same protected store for this cross-directory guarantee. Deleted markers, different stores, changed plans and independent controllers remain outside it; it does not establish exclusive bus ownership. A journal without a complete post-send observation is uncertain regardless of receipt status, so use read-only verification and never infer that a send did not occur.

For routed plans, both commands require `--project FILE`, `--source-network N`
and `--target-network N`. They validate the exact raw project digest and
re-derived one-to-six-bridge route before I/O, and recheck route freshness at
handoff. Local PCI identity/options stay direct; target inventories and the
one-shot exchange require the exact Reply Network. Routed apply produces
`cbus-selected-serial-apply-v2` with bounded versioned original/parser frame
evidence. Preserve the original journal path and canonical attempt marker.
`cbus-toolkit serial-address reconcile --journal J --project FILE` independently
validates the complete proof before planning or applying an offline XML/CBZ
move; partial/uncertain evidence, direct Rust v1 and routed live C-Gate
reconciliation refuse. Read [the full contract](../../../../docs/rust-selected-serial-routed.md)
and [reconciliation](../../../../toolkit-cli/docs/physical-addressing.md).

The committed tests use scripted loopback peers. They prove ordering, wire count, evidence, and failure behavior, not physical-unit compatibility, movement cause, or persistence.

## cmqttd

Exactly one C-Bus endpoint mode is required:

```sh
rust/target/release/cmqttd \
  --broker-address mqtt.example.net \
  --broker-port 8883 \
  --tcp 192.168.1.10:10001 \
  --project-file house.cbz \
  --cbus-network Main Network
```

Endpoint choices are `--tcp HOST:PORT`, `--esp32-wifi HOST[:PORT]`, `--esp32-serial DEVICE` (alias `--serial`), and `--esp32-discover`. Do not combine them.

Important options:

- Broker: `--broker-address`, `--broker-port`, `--broker-keepalive`.
- Security: `--broker-disable-tls`, `--broker-auth`, `--broker-ca`, `--broker-client-cert`, `--broker-client-key`.
- Runtime: `--timesync`, `--no-clock`, `--status-resync`, `--verbosity`, `--debug`, `--log-file`.
- Labels: `--project-file` and `--cbus-network`.
- ESP32 serial/reconnect: `--esp32-baudrate`, `--esp32-reconnect-interval`, `--esp32-max-reconnect`.

TLS is enabled by default. Broker port `0` selects 8883 with TLS or 1883 with `--broker-disable-tls`. The authentication file contains the username on line one and password on line two. Client-certificate authentication requires both the certificate and key options.

## cbus-simulator

```sh
rust/target/release/cbus-simulator 127.0.0.1 10001
```

Both positional arguments are optional; defaults are `127.0.0.1` and `10001`. The simulator provides the PCI/CNI behavior used for development and tests. It does not model every physical unit.

## cgate-mock

```sh
rust/target/release/cgate-mock --bind 127.0.0.1:20033
rust/target/release/cgate-mock --bind 127.0.0.1:0 --deny-programming
rust/target/release/cgate-mock --unitspec /path/to/unit/specifications
```

The default bind is `127.0.0.1:20033`. Port `0` chooses an ephemeral port and the first output line reports the actual listener. Programming rights are enabled by default; `--deny-programming` exercises restricted behavior. Vendor unit specifications are optional and are not included in the repository.

## cbus-vector-check

```sh
rust/target/release/cbus-vector-check rust/testdata/vectors
rust/target/release/cbus-vector-check rust/testdata/vectors --file checksum.jsonl
rust/target/release/cbus-vector-check rust/testdata/vectors --file cgate_dbsetxml.jsonl
```

The final line has the form `protocol-vectors: PASSED/TOTAL PASS|FAIL`. Exit code zero requires at least one processed vector and no failures.
The DBSETXML suite runs six real in-memory C-Gate replacements and exact
readbacks; five use a synthetic typed-tree pre-state and one uses an owned
native combined Network/Unit readback. It does not contact a C-Gate listener.

## Docker

Copy `.env.example` to `.env`, set the broker plus either a CNI or serial endpoint, then run `docker compose up --build`. Docker uses host networking. Project backups, authentication files, and certificates in `cmqttd_config/` are site-specific ignored files; do not commit or expose them.

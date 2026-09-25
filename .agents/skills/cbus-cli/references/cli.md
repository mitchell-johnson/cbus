# CLI reference

The Python `cbus-toolkit` application is installed separately; see [toolkit.md](toolkit.md). Run `cargo build --release --workspace` from `rust/` to create the Rust binaries under `rust/target/release/`. Use each program's `--help` output as the option-level authority.

## Program selection

| Need | Program | External effect |
| --- | --- | --- |
| Edit projects, commission networks, configure supported units, or use C-Gate | `cbus-toolkit` | Depends on subcommand: files, server state, or hardware |
| Decode one serial frame | `cbus-tools decode` | None |
| Read a Toolkit backup or project XML | `cbus-tools dump-labels` | Reads locally; optionally writes JSON |
| Query one unit or discover units | `cbus-tools interrogate` | Sends requests through a TCP CNI |
| Verify a selected-serial plan | `cbus-tools serial-verify` | Sends bounded read-only MMI and IDENTIFY traffic |
| Apply a selected-serial plan | `cbus-tools serial-apply` | Writes a durable local journal, sends one address broadcast, then reads state |
| Bridge C-Bus and MQTT/Home Assistant | `cmqttd` | Long-running network and MQTT traffic; accepts control messages |
| Emulate a PCI/CNI endpoint | `cbus-simulator` | Opens a local TCP listener |
| Emulate the C-Gate 3.4 command surface | `cgate-mock` | Opens a TCP listener and mutates in-memory state |
| Recheck committed compatibility vectors | `cbus-vector-check` | Reads local JSONL vectors |

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

Use the same exact-profile parameter export and SceneManager cache to resolve a
stored Trigger Control group/action pair and submit one event:

```sh
cbus-toolkit cgate --host 127.0.0.1 edlt-scene-trigger snapshot.json \
  --metadata scene-cache.json --network //PROJECT/254 --scene 1 --force
```

Preflight rejects missing, disabled or stale bindings before connecting. The
command sends exactly one `TRIGGER EVENT //PROJECT/NETWORK/202/GROUP ACTION`
request, optionally with `FORCE`, and never retries or changes PP data. A
terminal `200` is native acceptance only. The event is group-scoped rather
than point-to-point. The caller-supplied source/cache are not compared with a
physical unit; binding freshness, physical scene execution and persistence
remain unverified. See `toolkit-cli/docs/edlt-scene-trigger.md`.

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
  --journal /operator/recovery/selected-plan-attempt.json --timeout 300
rust/target/release/cbus-tools serial-verify \
  --pci 192.0.2.10:10001 \
  --journal /operator/recovery/selected-plan-attempt.json --timeout 300
```

Both commands require the numeric IP and port to match the validated plan before connecting. Each `--pci` invocation opens a direct TCP socket and requires exclusive ownership of that CNI; stop `cmqttd` or any other current owner before running it. Verify is read-only and exits zero only when a fresh, bookended observation equals `expected_after`. Apply first requires that exact fresh-before inventory, then immediately recalls local option 66 and requires `05`. It exclusively creates and fsyncs the journal with conservative send intent before invoking the one-shot write on the same PCI connection. It sends no automatic retry or rollback and independently observes the result. Preserve the journal at one stable path: same-process canonical plan fingerprints are only an additional guard; a new process using a different path is not globally deduplicated. A journal without a complete post-send observation is uncertain regardless of receipt status, so use `serial-verify --journal` and never infer that a send did not occur.

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
```

The final line has the form `protocol-vectors: PASSED/TOTAL PASS|FAIL`. Exit code zero requires at least one processed vector and no failures.

## Docker

Copy `.env.example` to `.env`, set the broker plus either a CNI or serial endpoint, then run `docker compose up --build`. Docker uses host networking. Project backups, authentication files, and certificates in `cmqttd_config/` are site-specific ignored files; do not commit or expose them.

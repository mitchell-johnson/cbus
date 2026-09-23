# CLI reference

The Python `cbus-toolkit` application is installed separately; see [toolkit.md](toolkit.md). Run `cargo build --release --workspace` from `rust/` to create the Rust binaries under `rust/target/release/`. Use each program's `--help` output as the option-level authority.

## Program selection

| Need | Program | External effect |
| --- | --- | --- |
| Edit projects, commission networks, configure supported units, or use C-Gate | `cbus-toolkit` | Depends on subcommand: files, server state, or hardware |
| Decode one serial frame | `cbus-tools decode` | None |
| Read a Toolkit backup or project XML | `cbus-tools dump-labels` | Reads locally; optionally writes JSON |
| Query one unit or discover units | `cbus-tools interrogate` | Sends requests through a TCP CNI |
| Bridge C-Bus and MQTT/Home Assistant | `cmqttd` | Long-running network and MQTT traffic; accepts control messages |
| Emulate a PCI/CNI endpoint | `cbus-simulator` | Opens a local TCP listener |
| Emulate the C-Gate 3.4 command surface | `cgate-mock` | Opens a TCP listener and mutates in-memory state |
| Recheck committed compatibility vectors | `cbus-vector-check` | Reads local JSONL vectors |

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

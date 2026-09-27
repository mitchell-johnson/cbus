# Command-line programs

The Python Toolkit CLI and Rust programs are installed independently. Use a program's `--help` output for its option list.

## cbus-toolkit

Requires Python 3.13 or newer. From the repository root:

```sh
python3.13 -m venv toolkit-cli/.venv
toolkit-cli/.venv/bin/python -m pip install -e ./toolkit-cli
source toolkit-cli/.venv/bin/activate
cbus-toolkit --help
cbus-toolkit project inspect project.cbz
cbus-toolkit cgate --host 127.0.0.1 --port 20023 project list
```

`project` edits XML/CBZ files offline. `cgate` provides native project, network, database, unit, addressing, and application workflows; `pci` talks directly to a CNI. Other families provide device configuration planning, scenes, templates, firmware diagnostics, preferences, and compatibility reporting. Results are JSON; use `--compact` before the command for one-line output. See the [Toolkit CLI guide](../toolkit-cli/README.md) and [feature status](../toolkit-cli/docs/implementation-status.md) for supported device profiles and exact workflows.

Use `cbus-toolkit interface discover-cni` or `cbus-tools cni-discover` to send
one bounded IPv4 UDP interface-discovery query. Both return the same endpoint
and raw-field schema without opening the advertised TCP service. Pass
`--bind LOCAL_IPV4` on a multi-adapter host; no-reply output is not proof that
an interface is absent. See [CNI discovery](../toolkit-cli/docs/cni-discovery.md).

`cbus-toolkit coverage --require-complete` reports the outstanding work and deliberately returns nonzero while full Toolkit parity remains incomplete.

## Build the Rust programs

Run `cargo build --release --workspace` from `rust/`. Binaries are written to `rust/target/release/`.

## cmqttd

`cmqttd` connects one C-Bus endpoint to an MQTT broker. Exactly one endpoint is required: `--tcp`, `--esp32-wifi`, `--esp32-serial` (also accepted as `--serial`), or `--esp32-discover`.

```sh
cmqttd \
  --broker-address mqtt.example.net \
  --broker-port 8883 \
  --tcp 192.168.1.10:10001 \
  --project-file house.cbz \
  --cbus-network Main Network
```

Key option groups:

- MQTT: `--broker-address`, `--broker-port`, `--broker-keepalive`, `--broker-disable-tls`, `--broker-auth`, `--broker-ca`, `--broker-client-cert`, and `--broker-client-key`.
- Endpoint: `--tcp`, `--esp32-wifi`, `--esp32-serial`, `--esp32-discover`, baud rate, and reconnect controls.
- Runtime: `--timesync`, `--no-clock`, `--status-resync`, logging, project file, and network selection.

## cbus-tools

Decode a PCI-to-client frame:

```sh
cbus-tools decode 05013800790148
```

Add `--client` for client-to-PCI direction, `--no-checksum` to accept unchecksummed data, or `--not-strict` for lenient decoding.

Export a project backup as JSON:

```sh
cbus-tools dump-labels --pretty 2 --output labels.json project.cbz
```

Interrogate one unit or scan a range:

```sh
cbus-tools interrogate --tcp 192.168.1.10:10001 --unit 5
cbus-tools interrogate --tcp 192.168.1.10:10001 --discover --max-address 80
```

Verify a strict selected-serial plan, apply it once with a durable recovery journal, or resume read-only verification from that journal:

```sh
cbus-tools serial-verify --pci 192.0.2.10:10001 --plan selected-plan.json
cbus-tools serial-apply --pci 192.0.2.10:10001 \
  --plan selected-plan.json \
  --journal /operator/recovery/selected-plan-attempt.json
cbus-tools serial-verify --pci 192.0.2.10:10001 \
  --journal /operator/recovery/selected-plan-attempt.json
```

Both commands open a direct TCP socket for `--pci` and require exclusive ownership of that CNI; stop `cmqttd` or any other current owner before running them. Apply requires a bookended fresh inventory equal to the plan's `before`, immediately recalls local option 66 and requires `05`, then durably reserves a hidden canonical-plan attempt marker and the main journal before sending the exact address command once on the same PCI connection. Preserve both files after every outcome. The marker's path is reported as `attempt_identity` on success. If interruption left a marker without the main journal, find the hidden `.cbus-selected-serial-attempt-sha256-*.json` file in the journal directory and use `serial-verify --journal MARKER` for read-only recovery. A preexisting marker refuses another process before connection; a concurrent claim race is refused at exclusive creation before send. This is a same-directory guard; other directories, removed markers, newly generated plans with different contents and competing controllers remain outside it. Recovery is read-only and never authorizes replay. Scripted acceptance does not prove device compatibility or persistence.

## cbus-simulator

The simulator accepts an optional bind address and port as positional arguments:

```sh
cbus-simulator 127.0.0.1 10001
```

It is intended for protocol development and automated tests. It is not a complete model of physical units.

## cgate-mock

```sh
cgate-mock --bind 127.0.0.1:20033
cgate-mock --bind 127.0.0.1:0 --deny-programming
cgate-mock --unitspec /path/to/unit/specifications
```

The server prints the actual listener address, which is useful with port `0` in tests. Programming-lock rights are enabled by default; `--deny-programming` reproduces the restricted posture. See [C-Gate compatibility](cgate.md).

## cbus-vector-check

Run a supported committed compatibility suite outside the Rust test harness:

```sh
cbus-vector-check rust/testdata/vectors --file encode.jsonl
cbus-vector-check rust/testdata/vectors --file cgate_event_fanout.jsonl
cbus-vector-check rust/testdata/vectors --file cgate_dbsetxml.jsonl
```

The event-fanout suite checks four native-observed status filters and four
config filters inferred from the pinned C-Gate bytecode. It does not claim a
captured native config-change trigger. The command succeeds only when it
processes at least one vector and all selected vectors pass. Directory-wide
mode also reads suites without standalone handlers and reports them as failures;
use `--file` for a supported suite.

The DBSETXML suite creates an explicit in-memory pre-state, performs each
replacement through `cbus-cgate`, and checks the `301` receipt, exact
`DBGETXML` readback, and old-OID retirement. Five typed-object expectations
are modeled fixtures; the composed Network/Unit expectation is from an owned
C-Gate 3.4.0.2001 loopback capture. This offline check does not exercise a
running C-Gate or physical network.

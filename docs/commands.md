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

Run the committed compatibility vectors outside the Rust test harness:

```sh
cbus-vector-check rust/testdata/vectors
cbus-vector-check rust/testdata/vectors --file encode.jsonl
```

The command exits successfully only when it processes at least one vector and all processed vectors pass.

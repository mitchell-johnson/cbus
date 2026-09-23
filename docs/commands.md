# Command-line programs

Build every program with `cargo build --release --workspace` from `rust/`. Use `--help` on a Clap-based program for the authoritative option list.

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
cbus-tools decode 0538007901490D
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

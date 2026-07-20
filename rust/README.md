# cbus (Rust)

Rust port of the `cbus` Python library and the `cmqttd` MQTT bridge daemon.
Wire/MQTT behaviour is bit-for-bit compatible with the Python working tree —
including its documented quirks — as proven by the golden-vector and
behavioral harness in `../rust-migration-harness/` (`./run.sh` must exit 0).

## Building

```sh
cd rust
cargo build --workspace            # debug
cargo build --workspace --release  # release
cargo test --workspace
```

Requires Rust 1.92+ (edition 2021).

## Crates

| crate            | kind | contents |
|------------------|------|----------|
| `cbus-protocol`  | lib  | pure wire codec: checksums, ramp rates, CAL/SAL/packet model, the `decode_packet` state machine, canonical JSON codec |
| `cbus-mqtt`      | lib  | cmqttd's pure logic: MQTT topic conventions, Home Assistant discovery payload builders, CBZ (Toolkit backup) label extraction |
| `cbus-transport` | lib  | buffered framing (256-byte cap), the async PCI client state machine (confirmation allocator, 1 s retransmit, 0.1 s pre-write delay, init sequence), TCP/serial connections |
| `cmqttd`         | bin  | the daemon: C-Bus ↔ MQTT bridge with HA discovery (CLI-compatible with the Python `cmqttd`) |
| `cbus-vector-check` | bin | golden-vector runner for `../rust-migration-harness/vectors` |
| `cbus-simulator` | bin  | fake PCI TCP server (port of `pciserverprotocol.py`); `cbus-simulator [address] [port]`, default `127.0.0.1:10001` |
| `cbus-tools`     | bin  | `decode` (frame decoder), `dump-labels` (CBZ → JSON), `interrogate` (unit interrogation over TCP) |

## Running cmqttd

```sh
cmqttd -b broker.example.com --broker-disable-tls \
    -t 192.0.2.1:10001 -P project.cbz -T 300 -v INFO
```

Flags mirror the Python daemon: `-b/-p/--broker-keepalive/--broker-disable-tls/
-A/-c/-k/-K` (MQTT), exactly one of `-t/--esp32-wifi/--esp32-serial/
--esp32-discover` (C-Bus), `-T/-C/-S` (time), `-P/-N` (Toolkit labels),
`-l/-v` (logging).

TLS uses the system trust store when `-c/--broker-ca` is not given; the
flag accepts a PEM file or a directory of PEM files. `--serial` is an
alias for `--esp32-serial` (Docker entrypoint compatibility), and
`--esp32-discover` finds a bridge via mDNS (`_cbus._tcp.local.`).
SIGINT/SIGTERM disconnect cleanly from the broker.

Differences from the Python daemon:

* TLS requires an explicit `--broker-ca` file (no system trust store yet).
* `--esp32-discover` (mDNS) is not ported; use `--esp32-wifi HOST[:PORT]`.
* The web UI and the debug proxy remain Python-only.

## Validation

```sh
./rust-migration-harness/run.sh   # from the repository root
```

runs the Python self-checks, `cargo build`, the 3201 protocol vectors,
`cargo test`, and the 17-assertion behavioral suite against a scripted fake
PCI and a minimal MQTT 3.1.1 broker.

# Rust workspace

This directory contains the complete maintained implementation.

| Crate | Kind | Purpose |
| --- | --- | --- |
| `cbus-protocol` | library | C-Bus packet, CAL, SAL, checksum, report, and JSON codecs |
| `cbus-transport` | library | TCP/serial connections, framing, PCI state machine, retries, and flow control |
| `cbus-mqtt` | library | MQTT topics, command parsing, Home Assistant discovery, and CBZ label extraction |
| `cmqttd` | binary | C-Bus to MQTT/Home Assistant bridge |
| `cbus-tools` | binary | `decode`, `dump-labels`, and `interrogate` commands |
| `cbus-simulator` | binary | fake PCI/CNI TCP server |
| `cbus-cgate` | library + binary | stateful C-Gate model and `cgate-mock` TCP server |
| `cbus-vector-check` | binary | standalone compatibility-vector runner |
| `cbus-golden-tests` | test crate | generated vector and exhaustive-domain tests |
| `cbus-test-support` | test library | in-process MQTT broker, fake PCI, process, and polling helpers |

Build and validate the workspace from this directory:

```sh
cargo build --release --workspace
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Repository documentation starts at the [root README](../README.md). The most useful implementation references are [architecture](../docs/architecture.md), [commands](../docs/commands.md), [C-Gate compatibility](../docs/cgate.md), and [testing](../docs/testing.md).

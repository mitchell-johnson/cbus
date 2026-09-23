# C-Bus Rust tools

This repository contains a Rust workspace for communicating with Clipsal/Schneider C-Bus networks. Rust is the only maintained implementation in this repository.

The workspace provides:

- `cmqttd`, a C-Bus to MQTT and Home Assistant bridge.
- `cgate-mock`, an in-memory C-Gate 3.4 compatible test server.
- `cbus-simulator`, a fake PCI/CNI TCP endpoint for development.
- `cbus-tools`, command-line utilities for frame decoding, project-label export, and unit interrogation.
- Reusable protocol, transport, MQTT, and test-support crates.

The C-Gate model recognizes every command path in the maintained command inventory: 224 public manual headings and 268 registered bytecode command paths, representing 431 unique paths. Core project, database, network, unit, event, and programming operations have stateful models. Hardware-facing and specialist application families use deterministic in-memory behavior; see [C-Gate compatibility](docs/cgate.md) for the exact boundary.

## Build

Install a current stable Rust toolchain, then run:

```sh
cd rust
cargo build --release
```

The binaries are written to `rust/target/release/`.

## Quick start

Decode a C-Bus frame:

```sh
rust/target/release/cbus-tools decode 0538007901490D
```

Run the fake PCI on the standard CNI port:

```sh
rust/target/release/cbus-simulator 127.0.0.1 10001
```

Run the C-Gate test server:

```sh
rust/target/release/cgate-mock --bind 127.0.0.1:20033
```

Run the MQTT bridge against a TCP CNI without TLS:

```sh
rust/target/release/cmqttd \
  --broker-address 127.0.0.1 \
  --broker-disable-tls \
  --tcp 192.168.1.10:10001
```

For Docker, copy `.env.example` to `.env`, set the broker and C-Bus endpoint, and run:

```sh
docker compose up --build
```

## Documentation

- [Current implementation status](docs/status.md)
- [Architecture and crate map](docs/architecture.md)
- [Command-line programs](docs/commands.md)
- [C-Gate compatibility](docs/cgate.md)
- [Protocol and transport behavior](docs/protocol.md)
- [cmqttd configuration](docs/configuration.md)
- [Testing and development](docs/testing.md)

## Repository layout

```text
rust/                    Rust workspace and all maintained source code
rust/testdata/           committed protocol vectors and system-test fixtures
docs/                    maintained documentation
cmqttd_config/           optional local Docker configuration
.github/workflows/ci.yml Rust formatting, lint, test, and release-build checks
```

## Validation

```sh
cd rust
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo build --release --workspace
```

The test suite includes generated tests for every committed compatibility vector, property tests, command-inventory checks, protocol tests, and full-system `cmqttd` tests using an in-process MQTT broker and scripted PCI.

## License

This project is licensed under the GNU Lesser General Public License v3.0 or later. See [COPYING](COPYING) and [COPYING.LESSER](COPYING.LESSER).

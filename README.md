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

## C-Bus Toolkit and C-Gate CLI compatibility

The Rust CLI stack provides full command-surface compatibility with the C-Gate 3.4 interface used by C-Bus Toolkit 1.18. Every command in the maintained native inventory is recognized and dispatched: 224 public manual headings and 268 registered command paths, representing 431 unique paths.

`cgate-mock` supports tagged commands, multiline replies, here-documents, event subscriptions, cross-client event delivery, per-session project selection, access levels, and programming locks. Its stateful command model covers project and database management, networks, units, groups, labels, levels, scenes, schedules, CGL data, repository operations, and PP programming sessions. Unit-specification directories can be supplied with `--unitspec` for catalogue-backed programming parameters.

The companion `cbus-tools` CLI reads Toolkit `.cbz` backups and project XML, exports network/application/group/unit metadata, decodes C-Bus frames, and interrogates units through a CNI. `cmqttd` can use the same project files for Home Assistant entity names and network selection.

Full compatibility here means that every registered C-Gate command path has tested parsing, dispatch, and protocol-shaped behavior. Core project, database, network, lighting, event, and programming workflows are stateful. Commands that normally require Schneider services or physical equipment use deterministic in-memory behavior in `cgate-mock`; the CLI does not reproduce the Toolkit graphical interface or create physical device side effects. See [C-Gate compatibility](docs/cgate.md) for the detailed boundary.

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

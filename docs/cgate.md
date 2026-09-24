# C-Gate compatibility

For the physical C-Gate service embedded in `cmqttd`, see [supported operations
and replacement status](cmqttd-cgate.md). It shares the real CNI with MQTT and
supports live eDLT reads. The rest of this document describes the separate mock.

`cbus-cgate` provides a bounded, stateful C-Gate 3.4 command model. `cgate-mock` exposes that model over TCP for integration tests and local tooling.

The user-facing client is [`cbus-toolkit cgate`](../toolkit-cli/README.md#c-gate-and-pci), implemented in Python. It connects to a native C-Gate server for online workflows, or to `cgate-mock` for local tests. Set `--port 20033` explicitly when using the mock; the client's default plain TCP port is 20023. This document describes the Rust server's compatibility, while the [Toolkit feature ledger](../toolkit-cli/docs/implementation-status.md) tracks end-to-end workflow parity.

## Command coverage

The registry contains:

- 224 command headings from C-Gate manual section 4.5.
- 268 command paths recovered from the registered command inventory.
- 431 unique paths after overlaps are removed.

Tests assert the inventory sizes, uniqueness, help exposure, parser reachability, and dispatch reachability. Unknown commands return an error response instead of silently succeeding.

## Stateful behavior

The model tracks projects, databases, networks, units, group levels, labels, locks, sessions, event modes, and programming sessions. Core `PROJECT`, `DB`, `NET`, `GET`, `SET`, `LIGHTING`, `EVENT`, and `PP` flows mutate and read this state. Application families and private registered commands have deterministic handlers so clients can exercise every command path without physical hardware.

The TCP server shares model state across connections. Project selection remains connection-local. Subscribed clients receive event fanout according to their `EVENT` mode, while command replies retain their client tag and C-Gate continuation/final-line framing.

## Wire behavior and bounds

- Default listener: `127.0.0.1:20033`.
- Tagged commands use `[tag] COMMAND ...` syntax.
- Reply continuations use a hyphen after the status/tag prefix; the final line uses a space.
- Input lines are limited to 1 MiB.
- Here-document bodies are limited to 16 MiB.
- The library event queue defaults to 4,096 entries and emits an overflow marker when it fills.
- TCP fanout channels are unbounded; a subscribed client that never reads can grow memory while other clients continue writing.

## Programming and unit specifications

Programming rights are enabled by default in `cgate-mock`. Use `--deny-programming` to deny programming sessions. Pass `--unitspec DIR` to load catalogue-backed parameter metadata. The loader supports includes, ordered fields, last-definition overrides, containment checks, structural numeric validation, an eight MiB file limit, and a 128-file include limit.

Vendor unit-specification files are not included. Without them, programming sessions still operate with spec-free behavior where the model permits it.

## Compatibility boundary

The server provides complete command dispatch and stable protocol-shaped behavior for automated clients. It does not connect to a physical C-Bus network, persist its in-memory projects across restarts, or reproduce every timing characteristic and device-specific side effect of Schneider C-Gate. Hardware discovery, firmware transfer, port probing, and specialist application commands are deterministic simulations.

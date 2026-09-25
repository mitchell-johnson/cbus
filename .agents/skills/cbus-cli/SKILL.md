---
name: cbus-cli
description: Operate, troubleshoot, and change the Python cbus-toolkit CLI and Rust C-Bus tools, including cmqttd, cbus-tools, cbus-simulator, cgate-mock, and cbus-vector-check. Use for Toolkit project editing, commissioning, unit configuration, scenes, C-Gate clients, frame decoding, MQTT bridging, simulations, integration tests, and questions about system architecture or compatibility.
---

# C-Bus CLI

Use the Python Toolkit CLI for project and commissioning workflows, and the Rust tools for MQTT bridging, protocol inspection, and test servers. Both are maintained products.

## Start with the task type

- For Toolkit project editing, commissioning, device configuration, and Python installation, read [references/toolkit.md](references/toolkit.md).
- For exact commands, arguments, outputs, and exit behavior, read [references/cli.md](references/cli.md).
- For crate responsibilities, data flow, project files, and MQTT behavior, read [references/system.md](references/system.md).
- For C-Gate commands, sessions, wire framing, and the Toolkit compatibility boundary, read [references/cgate.md](references/cgate.md).
- For common operating, test, and diagnostic sequences, read [references/workflows.md](references/workflows.md).

## Operating rules

1. Work from the repository root and run Cargo commands with `--manifest-path rust/Cargo.toml`, or change to `rust/` first.
2. Treat `--help`, the current Python and Rust source, `toolkit-cli/docs/`, and `docs/` as authoritative. Do not confuse the active Python Toolkit CLI with the retired Python bridge implementation.
3. Select the program for the job. Use `cbus-toolkit` for project editing, commissioning, supported device configuration, and C-Gate client workflows; `cbus-tools` for small Rust inspection utilities; `cmqttd` for the bridge; and the appropriate simulator for tests.
4. Install `cbus-toolkit` with Python 3.13 or newer into `toolkit-cli/.venv`. Rust binaries live under `rust/target/release/` after a release build. During Rust development, use `cargo run --manifest-path rust/Cargo.toml -p <package> -- <args>`.
5. Start with committed fixtures, a simulator, or an ephemeral loopback port. Use a physical endpoint only when the user supplied or selected it.
6. Distinguish observation from mutation. Toolkit project edits write files; online C-Gate and PCI commands may change a server or physical devices. `decode`, `dump-labels`, and vector checks are local reads. `interrogate` sends C-Bus requests. `cmqttd` accepts commands that can control a connected network. State-changing commands against `cgate-mock` affect only its in-memory model.
7. Never invent endpoint addresses, project names, credentials, certificate paths, unit addresses, or network names. Read them from the user's command, existing configuration, or project data.
8. Preserve ignored site files and secrets. Do not print authentication files, private keys, or project contents unless the task requires that exact output.
9. Report the command used, its exit result, and the relevant output. When the command can affect hardware, state which endpoint was targeted.
10. For eDLT Measurement decimal Gain/Offset values, never infer a locale from the host. Keep the default `canonical` grammar or choose one of the source-pinned Toolkit profiles explicitly, then inspect exponent-wrap metadata before applying the plan.

## Compatibility language

Describe `cgate-mock` as providing full C-Gate 3.4 **command-surface compatibility**: all 431 unique maintained command paths parse and dispatch, core workflows are stateful, and specialist or hardware-facing families have deterministic protocol-shaped behavior. Do not claim that it is the Toolkit GUI, Schneider C-Gate, persistent storage, a physical bus interface, or an exact simulation of every device side effect and timing characteristic.

`cbus-toolkit` is the user-facing Python CLI, with offline project editors and online workflow implementations. It targets Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001. Full Toolkit parity remains unfinished: consult its feature ledger and `coverage --require-complete`. The Rust mock's command coverage does not establish the Python CLI's complete workflow or hardware compatibility.

`cmqttd --cgate-bind` is the real embedded C-Gate service alongside MQTT. Read
`docs/cmqttd-cgate.md` and query `CMQTT CAPABILITIES` for its supported backend.
It is not yet a full C-Gate replacement. For live KEYGL5 labels, use
`cbus-toolkit cgate edlt-labels` against this service; Windows is unnecessary.
Keep saved database labels distinct from CRC-verified physical reads and
the bounded current-connection dynamic-label observations. The observation
view is incomplete and does not read labels that were already cached by a
device.

## Changing the repository

Keep behavior in the owning Python module or Rust crate and add tests at the narrowest useful layer. Use a golden vector when exact bytes or JSON define compatibility, and a system test when correctness depends on multiple components. Run the applicable Python or Rust validation from `AGENTS.md`. Preserve Toolkit source, tests, feature documentation, and acceptance evidence during cleanup.

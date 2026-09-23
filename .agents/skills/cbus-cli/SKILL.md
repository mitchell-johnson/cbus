---
name: cbus-cli
description: Operate, troubleshoot, and change this repository's Rust C-Bus command-line suite, including cmqttd, cbus-tools, cbus-simulator, cgate-mock, and cbus-vector-check. Use for C-Bus frame decoding, Toolkit project-file inspection, unit interrogation, MQTT bridging, C-Gate compatibility, simulations, integration tests, and questions about the system architecture or supported behavior.
---

# C-Bus CLI

Use the maintained Rust workspace and its test doubles to complete C-Bus tasks reproducibly.

## Start with the task type

- For exact commands, arguments, outputs, and exit behavior, read [references/cli.md](references/cli.md).
- For crate responsibilities, data flow, project files, and MQTT behavior, read [references/system.md](references/system.md).
- For C-Gate commands, sessions, wire framing, and the Toolkit compatibility boundary, read [references/cgate.md](references/cgate.md).
- For common operating, test, and diagnostic sequences, read [references/workflows.md](references/workflows.md).

## Operating rules

1. Work from the repository root and run Cargo commands with `--manifest-path rust/Cargo.toml`, or change to `rust/` first.
2. Treat `--help`, the current Rust source, and `docs/` as authoritative. Do not infer behavior from historical branches or removed implementations.
3. Select exactly one program for the immediate job. Use `cbus-tools` for one-shot inspection, `cmqttd` for the long-running bridge, `cbus-simulator` for a PCI/CNI test endpoint, `cgate-mock` for C-Gate client compatibility, and `cbus-vector-check` for committed vectors.
4. Prefer `rust/target/release/<program>` after a release build. During development, use `cargo run --manifest-path rust/Cargo.toml -p <package> -- <args>`.
5. Start with committed fixtures, a simulator, or an ephemeral loopback port. Use a physical endpoint only when the user supplied or selected it.
6. Distinguish observation from mutation. `decode`, `dump-labels`, and vector checks are local reads. `interrogate` sends C-Bus requests. `cmqttd` accepts MQTT commands that can control a connected network. C-Gate state-changing commands mutate the mock's shared in-memory model.
7. Never invent endpoint addresses, project names, credentials, certificate paths, unit addresses, or network names. Read them from the user's command, existing configuration, or project data.
8. Preserve ignored site files and secrets. Do not print authentication files, private keys, or project contents unless the task requires that exact output.
9. Report the command used, its exit result, and the relevant output. When the command can affect hardware, state which endpoint was targeted.

## Compatibility language

Describe `cgate-mock` as providing full C-Gate 3.4 **command-surface compatibility**: all 431 unique maintained command paths parse and dispatch, core workflows are stateful, and specialist or hardware-facing families have deterministic protocol-shaped behavior. Do not claim that it is the Toolkit GUI, Schneider C-Gate, persistent storage, a physical bus interface, or an exact simulation of every device side effect and timing characteristic.

The CLI can consume Toolkit `.cbz` backups and project XML, expose their labels and metadata, interrogate units through a CNI, and provide the C-Gate command surface used by Toolkit clients. Use the compatibility boundary above whenever explaining “full Toolkit compatibility.”

## Changing the repository

Keep behavior in the owning crate and add tests at the narrowest useful layer. Use a golden vector when exact bytes or JSON define compatibility, and a system test when correctness depends on multiple components. Run the applicable tests while iterating, then run the complete validation gate from `AGENTS.md` before committing a code change.

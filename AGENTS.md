# AI agent guidance

This repository maintains two applications: the Python `cbus-toolkit` CLI in `toolkit-cli/` and the Rust MQTT bridge and supporting tools in `rust/`. The Toolkit CLI is an active product, separate from the removed pre-Rust bridge implementation. Preserve both applications when cleaning up legacy code. Treat their current source and feature documentation as authoritative.

For tasks that operate, troubleshoot, or change the command-line tools, read [`.agents/skills/cbus-cli/SKILL.md`](.agents/skills/cbus-cli/SKILL.md) and the relevant files in its `references/` directory first.

Run Cargo commands from `rust/`. Keep protocol rules in `cbus-protocol`, endpoint behavior in `cbus-transport`, pure MQTT transformations in `cbus-mqtt`, C-Gate behavior in `cbus-cgate`, and orchestration in the binary crates. Add exact wire or JSON compatibility cases to `rust/testdata/vectors/` and interaction behavior to an integration or system test.

The Toolkit CLI requires Python 3.13 or newer. Its source is under `toolkit-cli/src/cbus_toolkit/`, with tests under `toolkit-cli/tests/`. Preserve its compatibility ledger and supporting acceptance evidence. Full C-Gate command coverage in the Rust mock does not mean full Toolkit workflow parity; consult `toolkit-cli/docs/implementation-status.md` and `cbus-toolkit coverage --require-complete` before making completeness claims.

Never commit site project files, `.env`, broker credentials, certificates, private keys, vendor unit specifications, or files in `cmqttd_config/` that are ignored by Git. Prefer the simulator, `cgate-mock`, committed fixtures, and ephemeral ports for development. Use a real broker, CNI, PCI, or C-Bus network only when the task explicitly requires it and the endpoint is known.

Before committing a Rust code change, run these checks from `rust/`:

```sh
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo build --release --workspace
```

For Toolkit changes, install the `test,research,serial,usb` extras in `toolkit-cli/.venv`, then run `make check` and `make check-interop` from `toolkit-cli/`. The offline suite skips tests requiring explicitly configured vendor software or hardware. Report those skips; an offline pass does not replace native or hardware acceptance. See `docs/testing.md` for setup.

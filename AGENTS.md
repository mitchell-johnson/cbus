# AI agent guidance

This is a Rust-only C-Bus repository. Treat the current `main` branch, the Rust source, and the maintained files under `docs/` as authoritative. Do not restore or rely on the removed pre-Rust Toolkit replacement.

For tasks that operate, troubleshoot, or change the command-line tools, read [`.agents/skills/cbus-cli/SKILL.md`](.agents/skills/cbus-cli/SKILL.md) and the relevant files in its `references/` directory first.

Run Cargo commands from `rust/`. Keep protocol rules in `cbus-protocol`, endpoint behavior in `cbus-transport`, pure MQTT transformations in `cbus-mqtt`, C-Gate behavior in `cbus-cgate`, and orchestration in the binary crates. Add exact wire or JSON compatibility cases to `rust/testdata/vectors/` and interaction behavior to an integration or system test.

Never commit site project files, `.env`, broker credentials, certificates, private keys, vendor unit specifications, or files in `cmqttd_config/` that are ignored by Git. Prefer the simulator, `cgate-mock`, committed fixtures, and ephemeral ports for development. Use a real broker, CNI, PCI, or C-Bus network only when the task explicitly requires it and the endpoint is known.

Before committing a code change, run the applicable checks from `rust/`. The complete gate is:

```sh
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo build --release --workspace
```

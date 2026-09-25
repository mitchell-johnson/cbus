# Testing and development

## Rust checks

Run the Rust gates from `rust/`:

```sh
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo build --release --workspace
```

CI runs the same four checks for pull requests and pushes to `main`.

## Toolkit CLI checks

Install Python 3.13 or newer and the development extras from the repository root:

```sh
python3.13 -m venv toolkit-cli/.venv
toolkit-cli/.venv/bin/python -m pip install -e './toolkit-cli[test,research,serial,usb]'
cd toolkit-cli
make check
make check-interop
```

`make check` runs the offline Python suite. Tests requiring vendor binaries, unit specifications, native C-Gate, Windows workers, or physical devices skip unless their explicit environment gates are configured. `make check-interop` builds the Rust mock and exercises the production Python client and wrappers against it. CI runs the offline suite with the mock built; vendor and hardware acceptance remain separate.

Do not equate offline test success with complete Toolkit parity. Run `cbus-toolkit coverage --require-complete` to inspect that separate gate, and consult the [Toolkit status and acceptance evidence](../toolkit-cli/docs/implementation-status.md) for full validation requirements.

## Test data

`rust/testdata/vectors/` contains JSONL compatibility vectors for checksums, frame encoding and decoding, ramp rates, MQTT topics, and Home Assistant discovery. The `cbus-golden-tests` build script generates a separately named Rust test for every vector so a failure identifies the exact case.

`rust/testdata/fixtures/` contains a small project XML and behavioral expectations used by CLI and full-system tests. These are test fixtures rather than production configuration.

## Full-system tests

`cmqttd` tests launch the compiled daemon against an in-process MQTT 3.1.1 broker and a scripted fake PCI. They verify startup, subscriptions, discovery, state publication, command delivery, status sweeps, clock behavior, and reconnect-related flows without external services.

`cgate-mock` tests exercise tagged framing, multiline replies, shared state, per-session project selection, event filtering and fanout, here-documents, command inventory reachability, and programming access. The hardware-service tests separately pin bounded `DBSETXML` document framing, durable project archive/restore/rename rollback, read-only repository listing, and MQTT continuity through those local administrative commands.

## Adding behavior

Keep byte-level rules in `cbus-protocol`, endpoint behavior in `cbus-transport`, pure MQTT data transformations in `cbus-mqtt`, and orchestration in the binary crate. Add a golden vector when compatibility depends on exact bytes or JSON. Add a system test when correctness depends on interactions among the daemon, broker, and PCI.

Do not add site project files, credentials, certificates, or vendor catalogue data to the repository.

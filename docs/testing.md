# Testing and development

Run the repository gates from `rust/`:

```sh
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo build --release --workspace
```

CI runs the same four checks for pull requests and pushes to `main`.

## Test data

`rust/testdata/vectors/` contains JSONL compatibility vectors for checksums, frame encoding and decoding, ramp rates, MQTT topics, and Home Assistant discovery. The `cbus-golden-tests` build script generates a separately named Rust test for every vector so a failure identifies the exact case.

`rust/testdata/fixtures/` contains a small project XML and behavioral expectations used by CLI and full-system tests. These are test fixtures rather than production configuration.

## Full-system tests

`cmqttd` tests launch the compiled daemon against an in-process MQTT 3.1.1 broker and a scripted fake PCI. They verify startup, subscriptions, discovery, state publication, command delivery, status sweeps, clock behavior, and reconnect-related flows without external services.

`cgate-mock` tests exercise tagged framing, multiline replies, shared state, per-session project selection, event filtering and fanout, here-documents, command inventory reachability, and programming access.

## Adding behavior

Keep byte-level rules in `cbus-protocol`, endpoint behavior in `cbus-transport`, pure MQTT data transformations in `cbus-mqtt`, and orchestration in the binary crate. Add a golden vector when compatibility depends on exact bytes or JSON. Add a system test when correctness depends on interactions among the daemon, broker, and PCI.

Do not add site project files, credentials, certificates, or vendor catalogue data to the repository.

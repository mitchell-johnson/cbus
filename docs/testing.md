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
make check-wheel
```

`make check` runs the offline Python suite. Tests requiring vendor binaries, unit specifications, native C-Gate, Windows workers, or physical devices skip unless their explicit environment gates are configured. `make check-interop` builds the Rust mock and exercises the production Python client and wrappers against it. CI runs the offline suite with the mock built; vendor and hardware acceptance remain separate.

`make check-wheel` builds a fresh wheel, creates a temporary Python 3.13
environment, installs the wheel with all supported extras, and runs the same
offline suite with `PYTHONPATH=tests` so imports resolve from the installed
artifact instead of `src/`. The temporary wheel and environment are removed
after either success or failure. Provisioning-gated skips retain the same
meaning as the source-tree run.

Do not equate offline test success with complete Toolkit parity. Run `cbus-toolkit coverage --require-complete` to inspect that separate gate, and consult the [Toolkit status and acceptance evidence](../toolkit-cli/docs/implementation-status.md) for full validation requirements.

## Test data

`rust/testdata/vectors/` contains JSONL compatibility vectors for checksums, frame encoding and decoding, ramp rates, MQTT topics, and Home Assistant discovery. The `cbus-golden-tests` build script generates a separately named Rust test for every vector so a failure identifies the exact case.

`rust/testdata/fixtures/` contains a small project XML and behavioral expectations used by CLI and full-system tests. These are test fixtures rather than production configuration.

## Full-system tests

`cmqttd` tests launch the compiled daemon against an in-process MQTT 3.1.1 broker and a scripted fake PCI. They verify startup, subscriptions, discovery, state publication, command delivery, status sweeps, clock behavior, and reconnect-related flows without external services. The MQTT consistency regressions cover immediate opposite QoS 1 commands, PUBACKs, delayed and lost PCI confirmations, FIFO blocking, outcome-uncertain failure, per-command physical level requests, C-Gate cache population only from bus reports, transport-state publication, and a forced post-reconnect sweep.

Routed PP tests cover one- and six-bridge standard CAL encoding plus exact
Reply Network, unit, parameter, tag and length correlation. Lock-protected
SAVE additionally exercises the routed Unlock challenge and its PCI
confirmation before the tagged STORE; direct and neighbouring-route replies
cannot advance it, and a lost confirmation is never replayed. The retained
composition evidence and physical-acceptance boundary are recorded in
`rust/testdata/fixtures/native_cgate_routed_pp_protection.json`.

`cgate-mock` tests exercise tagged framing, multiline replies, shared state, per-session project selection, event filtering and fanout, here-documents, command inventory reachability, and programming access. Focused `DBSETXML` tests cover scalar fields and complete typed Unit, Level, NetVar, Group, Application, and Network/Interface replacement, including mixed Network documents with Unit and Application children; submitted-root `301 OID` receipts; Unit scalar/PP ambiguity checks; project-wide OID and sibling-address conflicts before mutation; subtree retirement; inherited namespace/comment/PI retention; and copy/rename/delete/archive/restart lifecycle. The production Python C-Gate client and real cmqttd daemon repeat typed subtree exchanges. Hardware-service tests pin configured-Network replacement at the same address/interface binding, preservation of physical inventory/live levels/state/retries, durable restart readback, rollback for a move or rebind, and no PCI I/O. The mixed tree composes separately retained native complete-Network and complete-Unit contracts; no exact native combined replacement capture is claimed. `rust/testdata/fixtures/native_cgate_legacy_database.json` and `rust/testdata/vectors/cgate_dbsetxml.jsonl` retain the oracle summary and exact documents/readbacks.

`cmqttd/tests/system_cgate_dali.rs` launches the real daemon with the scripted
PCI and broker. It pins DALI help and capability reporting, LOGIN boundaries,
exact core and emergency extended-CAL bytes, source-correlated replies,
pre-I/O validation, and MQTT continuity while a gateway operation is pending.
`cmqttd/tests/system_cgate_dali_specialized.rs` pins specialized memory recall,
page selection, tagged store acknowledgement and readback, group-zero gateway
control, session state, LOGIN, typed-plan pre-I/O refusal, and MQTT continuity
through the same real-daemon harness. The 60-path fixture/dispatch test, local
catalogue and durable session tests, and exact wire unit cases live in
`cbus-cgate/src/service/dali_specialized.rs`.
Transport tests separately prove bounded AUTO polling and that a lost reply is
never replayed after reconnect. These loopback tests do not establish behavior
of a particular physical DALI gateway or downstream DALI bus.

`system_cgate_net_lifecycle.rs` starts the real daemon with the fake PCI and
mini broker. It pins exact NET/NETWORK/TOPOLOGY help, LOGIN boundaries, local
catalogue operations with zero PCI writes, bound OPEN/CLOSE and project
START/STOP while the one MQTT PCI remains connected, exact `NET LEARN` and
all-selector `NETWORK LOCATE` wire behavior, definitive-NAK no-replay,
capabilities, topology parser failures, and MQTT lighting continuity. Focused
service tests additionally pin the exact one-bridge NET LEARN and every LOCATE
selector frame, unrelated-reply isolation, one-to-six-route vector boundary,
pre-I/O route refusal and reconnect invalidation. They also drive physical
TOPOLOGY EXPLORE and the direct
UNRAVEL planner through complete scripted before/after inventories. The five independent
packet vectors live in `rust/testdata/vectors/network_management.jsonl`; the
sanitized build-2001 help/runtime/class evidence lives in
`rust/testdata/fixtures/native_cgate_net_lifecycle.json`.

`cmqttd/tests/system_cgate_remaining_applications.rs` runs the real daemon
against the same scripted PCI and broker for direct-network Identify, Short
Message and Error Reporting. It pins exact confirmed command bytes, LOGIN
boundaries, invalid-input no-I/O behavior, source-preserving inbound fanout,
negative-confirmation no-replay behavior, capability reporting, and concurrent
MQTT lighting continuity. Protocol unit and golden-vector tests separately pin
the native wire layouts and the repaired Short Message SEND contract.

## Adding behavior

Keep byte-level rules in `cbus-protocol`, endpoint behavior in `cbus-transport`, pure MQTT data transformations in `cbus-mqtt`, and orchestration in the binary crate. Add a golden vector when compatibility depends on exact bytes or JSON. Add a system test when correctness depends on interactions among the daemon, broker, and PCI.

Do not add site project files, credentials, certificates, or vendor catalogue data to the repository.

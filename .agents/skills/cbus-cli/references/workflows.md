# Operational workflows

For Python Toolkit project editing, commissioning, and C-Gate client commands, start with [toolkit.md](toolkit.md). The recipes below cover the Rust tools and shared diagnostics.

## Build and identify the current interface

```sh
cd rust
cargo build --release --workspace
target/release/cbus-tools --help
target/release/cmqttd --help
```

Use the current `--help` output before composing a command for a deployed checkout. If observed behavior disagrees with documentation, inspect the checked-out source and record the discrepancy.

## Decode an observed frame

1. Determine whether the text traveled from PCI to client or client to PCI.
2. Run `cbus-tools decode FRAME`; add `--client` for client-to-PCI data.
3. Keep checksum and strict validation enabled initially.
4. Retry with `--no-checksum` or `--not-strict` only to diagnose malformed or partial captures, and state that validation was relaxed.
5. Use the JSON line for machine processing and the debug packet for human diagnosis.

## Inspect a Toolkit project without hardware

```sh
rust/target/release/cbus-tools dump-labels --pretty 2 project.cbz > labels.json
```

Confirm the selected network name before passing the project to `cmqttd`. Avoid committing the source project or derived site metadata.

## Baseline live eDLT labels

1. Confirm cmqttd owns the intended CNI and its embedded C-Gate listener.
2. Run `edlt-labels --network` first if you only need a partial diagnostic inventory.
3. Run `edlt-label-audit //PROJECT/NETWORK --write-baseline PATH` only when every supported unit can be freshly identified and read. The path must not exist.
4. Preserve the baseline outside the repository when it contains site labels.
5. After commissioning or a controlled programming operation, use `--baseline PATH --mode configuration`. Use `exact` only when every physical byte must remain identical, or `labels` when human-facing text/reference drift is the acceptance boundary.
6. Inspect added, removed and changed units before replacing any operator-held baseline.

The audit reuses one initial network synchronization and reads units
sequentially. Dynamic-label SAL observations remain diagnostic traffic and do
not enter the baseline. A passing result does not establish an atomic network
snapshot, display rendering, power-cycle persistence or dynamic-cache readback.

## Test a PCI/CNI client locally

Start the simulator in one process:

```sh
rust/target/release/cbus-simulator 127.0.0.1 10001
```

Then point the client at `127.0.0.1:10001`. Use an ephemeral or otherwise unused port when a test owns process management. The simulator is useful for framing, initialization, confirmation, selected SAL, and status-response workflows; it is not evidence of every physical-unit behavior.

## Discover a CNI without opening it

```sh
cbus-toolkit interface discover-cni --bind LOCAL_IPV4 --timeout 3
# Equivalent Rust command:
cbus-tools cni-discover --bind LOCAL_IPV4 --timeout 3
```

Review `devices[].endpoint`, product and raw fields. A zero-result collection
does not prove absence. To create a native network, pass the chosen endpoint
explicitly to `cbus-toolkit cgate database network-new`; discovery itself
performs no project mutation or TCP connection.

## Interrogate a real CNI

1. Obtain the actual `HOST:PORT` and the intended unit address or scan ceiling.
2. Start with one known unit and an explicit timeout.
3. Use discovery only when a bounded network scan is intended.
4. Record the endpoint and whether the result was a response, timeout, connection failure, or decode failure.

```sh
rust/target/release/cbus-tools interrogate \
  --tcp CNI_HOST:10001 --unit UNIT --timeout 5
```

## Verify or apply a selected-serial plan

1. Generate and inspect a strict version-one plan with the Toolkit CLI. Confirm the numeric endpoint, local unit and serial, selected serial, empty destination, and embedded fresh-before evidence.
2. Give `--journal` one stable, protected path that does not exist. Preserve it after every outcome.
3. Run read-only `serial-verify --plan` first when you only need classification.
4. Run `serial-apply` only while the process owns the endpoint and commissioning activity exclusively. It completes the exact bookended fresh-before inventory, then immediately rechecks option 66=`05` before journaling or sending on that same connection.
5. Treat every existing apply journal as a possible send, even when it has no receipt. Continue only with `serial-verify --journal`; never rerun apply from recovery evidence.

```sh
rust/target/release/cbus-tools serial-apply \
  --pci CNI_IP:10001 --plan selected-plan.json \
  --journal /operator/recovery/selected-plan-attempt.json --timeout 300

rust/target/release/cbus-tools serial-verify \
  --pci CNI_IP:10001 \
  --journal /operator/recovery/selected-plan-attempt.json --timeout 300
```

The process-local canonical fingerprint only blocks equivalent plan encodings during that process. After restart, even an equivalent reserialization at a different journal path is not globally deduplicated; semantically different validated plans are distinct as well. Simulator and scripted-peer tests do not establish physical movement or persistence.

## Exercise a C-Gate client

1. Start `cgate-mock --bind 127.0.0.1:0` and capture its printed port.
2. Open a TCP connection and send a basic `APIVER` or tagged `PROJECT LIST` command.
3. Enable events only when the client drains asynchronous lines.
4. Build the project model required by the client, then exercise state changes.
5. Use a second subscribed connection when testing cross-client fanout.
6. Close clients and terminate the mock after the test.

Use response status, tags, continuation/final framing, events, and subsequent reads to verify a command. A `200` alone may show dispatch but not the state transition the client needs.

## Validate compatibility data

```sh
rust/target/release/cbus-vector-check rust/testdata/vectors
```

For a focused failure, add `--file NAME.jsonl`. A new exact byte or JSON compatibility case belongs in the appropriate JSONL file and must be exercised by `cbus-golden-tests`.

## Diagnose cmqttd

1. Validate arguments with `cmqttd --help`; exactly one C-Bus endpoint is required.
2. Check whether TLS is intended and whether the selected broker port matches it.
3. Confirm that authentication, CA, client certificate, and key paths exist without printing their contents.
4. Verify the CNI or serial endpoint independently.
5. Run with `--verbosity DEBUG` or `--debug` and, when useful, an explicit `--log-file`.
6. Check broker connection, subscriptions, Home Assistant discovery, C-Bus initialization, confirmations, and reconnect behavior in that order.
7. If labels are wrong, dump the project, verify the network name, and pass `--cbus-network` explicitly.

## Validate repository changes

Run the narrow owning-crate test while iterating, for example:

```sh
cd rust
cargo test -p cbus-protocol
cargo test -p cbus-cgate
cargo test -p cmqttd
```

Before committing a code change, run:

```sh
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo build --release --workspace
```

For documentation or skill-only changes, validate links, examples, frontmatter, and the skill package. Run binary smoke checks when command syntax was changed.

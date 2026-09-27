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

`make check` runs the complete source-tree suite. Tests requiring vendor
binaries, unit specifications, native C-Gate, Windows workers, or physical
devices skip unless their explicit environment gates are configured. The
pytest summary reports those skips. `make check-offline` omits the C-Gate
interop module and both cmqttd interop modules so CI can execute and report
the two server selections separately.

`make check-interop` builds both `cgate-mock` and `cmqttd`, verifies that both
executables exist, runs the nine-case original C-Gate `SESSION_ID` payload
differential and the separate eleven-case numeric-tag full-wire differential
against each fresh server, then runs `test_rust_cgate_interop.py` in one
invocation and `test_cmqtt_interop.py` plus
`test_cmqtt_programming_methods_interop.py` in a second invocation. The focused
`check-cgate-interop` and `check-cmqtt-interop` targets deliberately do not
build a missing binary: they fail before collection. CI builds the two servers
and requires all four differential executions before the offline and two interop
selections; it retains their JSON receipts as well as a JUnit report and a
checked execution receipt for each pytest selection. The CI pytest
plugin records the collected and started node IDs plus every call outcome. The
audit compares that trace to JUnit, requires at least one passing test in the
`cgate-mock` module and in each cmqttd interop module, and fails if a selection
is missing, truncated, or entirely skipped. A green source job therefore cannot
conceal a cmqttd suite that skipped because its binary was absent.

The `toolkit-*-results.json` artifacts record the exact source revision,
JUnit/trace hashes, case IDs and outcomes, call events, and reported pass/skip/
failure counts. Pytest's JUnit counter includes `unittest` subtest events that
it does not emit as individual `<testcase>` elements. Receipts give those
events occurrence numbers under the parent test and report the unitemized
subtest count separately; they do not invent semantic IDs for them. The job
summary shows actual counters, including provisioning skips, rather than
inferring a zero-skip run from a green job.

`make check-wheel` builds a fresh wheel, creates a temporary Python 3.13
environment, installs the wheel with all supported extras, and runs the same
suite from outside the checkout with only the repository root and tests on
`PYTHONPATH`. Before collection it resolves `cbus_toolkit.__file__` and fails
unless it is under the temporary environment's `site-packages`; importing
`src/cbus_toolkit` cannot satisfy this gate. The temporary wheel and
environment are removed after either success or failure. The independent CI
wheel job retains its JUnit report, including every provisioning-gated skip.
It also retains and audits the same execution trace and result receipt as the
source job. The wheel gate still checks the imported package location before
pytest collection begins.

## Provisioned release gates

Native and physical acceptance are manual, separately provisioned jobs in
`.github/workflows/ci.yml`; neither is implied by ordinary pull-request CI.
Dispatch the workflow with `release_gate=native` or
`release_gate=hardware`. The native job requires a self-hosted macOS runner
labelled `cbus-native` and the `cbus-native` environment. Its environment must
supply executable `CBUS_CGATE_JAVA` and `CBUS_CGATE_JAVAC` paths, the original
C-Gate application directory in `CBUS_LOCAL_CGATE_VENDOR`, including
`cgate.jar`, and `CBUS_UNITSPEC_DIR`. `make check-native` reads the committed
`research/release-gates/native.json` selection. Both manual jobs build and
install a non-editable wheel, then set `CBUS_TOOLKIT_WHEEL` to that exact
archive. A missing or substituted wheel, missing provision, unsupported host,
zero-test selection, failed test, or skipped test fails the gate.

The hardware job requires a self-hosted runner labelled `cbus-hardware`, the
`cbus-hardware` environment, `CBUS_HARDWARE_ACCEPTANCE=1`, and a private
manifest path in `CBUS_HARDWARE_GATE_MANIFEST`. The manifest uses this shape:

```json
{
  "format": "cbus-provisioned-release-gate-v1",
  "gate": "hardware",
  "systems": ["Darwin"],
  "required_environment": {
    "CBUS_HARDWARE_ACCEPTANCE": {"kind": "flag"},
    "CBUS_CNI_ENDPOINT": {"kind": "value"}
  },
  "tests": ["tests/test_physical_fixture.py::PhysicalFixtureTests::test_effect_and_readback"]
}
```

Allowed provision kinds are `value`, `flag` (exactly `1`), `file`,
`directory`, and `executable`; a file or directory rule may add a relative
`contains` list. Test selectors must name committed `tests/test_*.py` modules
in the checkout, optionally followed by pytest node IDs. Keep device identities,
endpoints and vendor paths in the protected runner environment, not the
manifest. `research/release_gate.py` rejects a dirty tracked checkout,
untracked executable inputs under Toolkit source/tests/research (including
`conftest.py`), and inherited pytest options or plugins. It hashes the
selected modules and checked-in Toolkit
source/test/research inputs, hashes provision files and whole directory trees,
and verifies every installed package member against the wheel's `RECORD`,
archive bytes and exact checkout source bytes. Its pytest plugin records
collected, deselected and executed node IDs. The gate requires each selected
module or node to collect tests,
every collected test to execute once, no deselection, matching JUnit identities
and counters, and unchanged source, wheel, installed package, manifest and
provision artifacts after execution. It removes a prior JUnit report before
running pytest. The receipt contains the source revision, aggregate hashes,
counts, provision variable names and kinds, and a sanitized failure reason;
it omits private paths, values, test IDs and pytest output. Keep the separate
JUnit artifact protected because test-produced XML may contain site details.
The hardware selection stays private until P1.04 defines the required fixtures;
an absent manifest fails instead of turning hardware acceptance into a skip.

Both provisioned jobs upload the JSON receipt and JUnit report, then run
`.venv/bin/cbus-toolkit coverage --require-complete` directly. That final
command remains nonzero while the census or any implementation/acceptance
requirement is incomplete. `make coverage` is only an informational local
summary that prints the same status without enforcing it; use
`make require-complete` or the direct command for a release decision.

Do not equate offline test success with complete Toolkit parity. Run `cbus-toolkit coverage --require-complete` to inspect that separate gate, and consult the [Toolkit status and acceptance evidence](../toolkit-cli/docs/implementation-status.md) for full validation requirements.

## Test data

`rust/testdata/vectors/` contains JSONL compatibility vectors for checksums,
frame encoding and decoding, ramp rates, MQTT topics, Home Assistant discovery,
and selected C-Gate behavior. The `cbus-golden-tests` build script generates a
separately named Rust test for each vector in its supported protocol/MQTT suites.

`cbus-vector-check rust/testdata/vectors --file cgate_dbsetxml.jsonl` separately
executes six stateful DBSETXML transactions against `cbus-cgate`. The five
typed-object rows use the committed synthetic pre-state in
`cgate_dbsetxml_typed_tree_seed.xml`. The combined Network/Unit row requires
the submitted XML, `301` receipt, and exact readback from the owned native
C-Gate 3.4.0.2001 loopback fixture. The runner checks a nonempty pre-state,
exact replacement receipt and XML readback, and old-OID retirement for typed
rows.

`rust/testdata/fixtures/` contains a small project XML and behavioral expectations used by CLI and full-system tests. These are test fixtures rather than production configuration.

## Full-system tests

`cmqttd` tests launch the compiled daemon against an in-process MQTT 3.1.1 broker and a scripted fake PCI. They verify startup, subscriptions, discovery, state publication, command delivery, status sweeps, clock behavior, and reconnect-related flows without external services. The MQTT consistency regressions cover immediate opposite QoS 1 commands, PUBACKs, delayed and lost PCI confirmations, FIFO blocking, outcome-uncertain failure, per-command physical level requests, C-Gate cache population only from bus reports, transport-state publication, and a forced post-reconnect sweep.

Routed PP tests cover one- and six-bridge standard CAL, page-aware, OEM memory,
and GOC encoding plus exact Reply Network, unit, parameter, tag and length
correlation. Lock-protected SAVE additionally exercises the routed Unlock
challenge and its PCI confirmation before the tagged STORE; direct and
neighbouring-route replies cannot advance it, and a lost confirmation is never
replayed. The retained composition evidence and physical-acceptance boundary
are recorded in `rust/testdata/fixtures/native_cgate_routed_pp_protection.json`
and `rust/testdata/fixtures/native_cgate_routed_pp_methods.json`. For C-Bus 3
specifications, the routed suite also pins exact one- and six-bridge Save-to-NVM
EXECUTE/POLL bytes, rejects direct, neighbouring-route, wrong-unit and
wrong-operation statuses, and faults without replay after a lost result. Its
evidence boundary is recorded in
`rust/testdata/fixtures/native_cgate_routed_nvm_commit.json`.

Focused transport tests also cover selected-serial addressing, protected unit
readdressing, direct eDLT label clear, and physical PP one-shot sends. A timed-out
send keeps its allocated confirmation code quarantined until PCI reconnect, so
a late receipt cannot satisfy a later operation; the uncertain send is never
replayed.

`cgate-mock` tests exercise tagged framing, multiline replies, shared state, per-session project selection, event filtering and fanout, here-documents, command inventory reachability, and programming access. Focused `DBSETXML` tests cover scalar fields and complete typed Unit, Level, NetVar, Group, Application, and Network/Interface replacement, including mixed Network documents with Unit and Application children; submitted-root `301 OID` receipts; Unit scalar/PP ambiguity checks; project-wide OID and sibling-address conflicts before mutation; subtree retirement; inherited namespace/comment/PI retention; and copy/rename/delete/archive/restart lifecycle. The production Python C-Gate client and real cmqttd daemon repeat typed subtree exchanges. Hardware-service tests pin configured-Network replacement at the same address/interface binding, preservation of physical inventory/live levels/state/retries, durable restart readback, rollback for a move or rebind, and no PCI I/O. One owned native C-Gate 3.4.0.2001 combined Network/Application/Unit case pins the `301` root-OID receipt, schema-ordered plain Unit readback and a missing-`UnitName` `446` without mutation. A second [disposable-VM oracle](../toolkit-cli/docs/native-cgate-dbsetxml-combined-vm.md) pins exact tagged wire for combined acceptance, unknown namespaced Unit attribute/child omission on readback, and retirement of an omitted Application. It is original-service evidence, not a Rust comparison or broad vendor XML acceptance. `rust/testdata/fixtures/native_cgate_dbsetxml_combined.json`, `rust/testdata/fixtures/native_cgate_dbsetxml_combined_vm.json`, `rust/testdata/fixtures/native_cgate_legacy_database.json` and `rust/testdata/vectors/cgate_dbsetxml.jsonl` retain the corresponding oracles and vectors.

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
TOPOLOGY EXPLORE and the direct and topology-resolved UNRAVEL planners through
complete route-correlated scripted before/after inventories. The five independent
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

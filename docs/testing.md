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

Retained native receipts may describe an earlier implementation. Their archive
checks verify immutable recorded bytes and source pins; they do not establish
current native applicability. The separately provisioned matrix records its
actual implementation, and evidence validation still rejects changed current
invalidation inputs. See the [receipt correction report](../toolkit-cli/docs/feature-batch-2026-10-03-ci-receipt-regressions.md).


On this Mac, the native trust-store test has failed when its executable runs
from the external build volume and passed from a byte-identical internal copy.
The precise OS cause is not established. The opt-in
[`local_test_runner.py`](../rust/scripts/local_test_runner.py) retains each
executable's hashes, arguments and exit status while executing an internal
temporary copy. It changes neither assertions nor trust policy. Use this
profile only when reproducing that location difference, and retain the failed
ordinary run separately. From `rust/`:

```sh
cbus_test_runtime=$(mktemp -d /private/tmp/cbus-rust-tests.XXXXXX)
export CBUS_RUST_TEST_RUNNER_DIR="$cbus_test_runtime"
export CBUS_RUST_TEST_RUNNER_RECORDS="$cbus_test_runtime/executions.jsonl"
export CARGO_TARGET_AARCH64_APPLE_DARWIN_RUNNER="python3 -B $PWD/scripts/local_test_runner.py"
unset SSL_CERT_FILE SSL_CERT_DIR
cargo test --workspace
```

Unsetting those CA overrides selects the actual native store; supplying a PEM
file would test a different profile. Temporary executable copies are removed
after each owned process exits. The private execution record remains available.

For a Python-only feature chunk, the current user-directed local workflow uses
focused owning and affected historical modules rather than rerunning every
suite. The SceneManager inventory release selection is declared in
[`toolkit-cli/docs/edlt-scene-inventory-release-test-modules.txt`](../toolkit-cli/docs/edlt-scene-inventory-release-test-modules.txt).
Run that selection in both source and a fresh installed wheel, require every
module in the trace/JUnit auditor, and retain the exact public roster on both
owned backends. Record separate parent/subtest counts and each provisioning
skip. Pin source inputs before/after; retain Rust gates only when their entire
input set and owned binary hashes are unchanged. CI still runs the full gates.

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
against each fresh server, and replays twelve original Unit XML mapper cases
plus two earlier full Network readbacks against each server. The mapper gate
requires exact native/Rust `343/347/344` XML wires, including the LF-only
declaration row. It also runs the production Python client and pipelined XML
read smoke on both servers, then `test_rust_cgate_interop.py` in one
invocation and `test_cmqtt_interop.py` plus
`test_cmqtt_programming_methods_interop.py` and
`test_cmqtt_dali_commissioning_interop.py` in a second invocation. The focused
`check-cgate-interop` and `check-cmqtt-interop` targets deliberately do not
build a missing binary: they fail before collection. CI builds the two servers
and requires all six differential executions before the offline and two interop
selections; it retains their JSON receipts as well as a JUnit report and a
checked execution receipt for each pytest selection. The CI pytest
plugin records the collected and started node IDs plus every call outcome. The
audit compares that trace to JUnit, requires at least one passing test in the
`cgate-mock` module and in each cmqttd interop module, and fails if a selection
is missing, truncated, or entirely skipped. A green source job therefore cannot
conceal a cmqttd suite that skipped because its binary was absent.

The committed differential receipts under `toolkit-cli/research/fixtures/`, the
C-Gate contract inventory and the parity register are bound to source
fingerprints, so editing a fingerprinted Rust or Python source makes
`tests/test_parity_register.py` report them stale.
`make refresh-parity-receipts` rebuilds both debug servers, regenerates the contract
inventory, re-runs the `SESSION_ID`, numeric-tag and Unit XML mapper
differentials against each server into the committed fixture paths, then
rebuilds the `SESSION_ID` physical applicability receipt and the parity
register and runs `check-parity-register`. It stops on the first failed
differential. It never rewrites the retained pre-fix `SESSION_ID` receipt, and
receipts must never be edited by hand.

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
supply executable `CBUS_CGATE_JAVA` and `CBUS_CGATE_JAVAC` paths from the
owned Temurin 11.0.32.1+1 JDK, whose launcher digests and whole JDK-home tree
digest are pinned in `native.json` (see
[original artifact provenance](../toolkit-cli/docs/original-artifact-provenance.md#native-gate-runtime-pin));
any other Java, including `/usr/bin/java`, fails the gate before pytest runs. It also needs the original
C-Gate application directory in `CBUS_LOCAL_CGATE_VENDOR`, including
`cgate.jar`, `CBUS_UNITSPEC_DIR`, `CBUS_NATIVE_SERVICE_BACKEND=local`, and the
`CBUS_NATIVE_TLS_TEST=1` and `CBUS_SCENE_NATIVE=1` opt-ins. The job builds
`cmqttd` itself and exports it as the executable `CBUS_CMQTTD_BIN`, which the
native/cmqttd `PROJECT ARCHIVE`/`RESTORE` interchange test needs; `sqlite3`
must be on the runner's `PATH`. With the local
backend selected, `tests/conftest.py` starts one owned loopback `LocalCGate`
before the first module that reads `CBUS_CGATE_TEST_HOST`, publishes its
ephemeral port and loopback simulator routing, and refuses an externally set
`CBUS_CGATE_TEST_HOST`/`PORT`. `make check-native` first runs
`research/skip_census.py --check`, which statically classifies every test
module's skip gates by provisioning into the committed
`research/release-gates/skip-census.json` and fails if a test runnable under
that profile is missing from the committed
`research/release-gates/native.json` selection, or if the selection covers a
test the profile would skip. Modules that need the original Toolkit, Windows,
hardware, vendor firmware, other Rust binaries, private evidence inputs or a
pre-provisioned project stay out, with the reason in the census. Both manual jobs build and
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
An absent manifest fails instead of turning hardware acceptance into a skip.

### Hardware fixture matrix

[`toolkit-cli/research/hardware-fixture-matrix.json`](../toolkit-cli/research/hardware-fixture-matrix.json)
lists the physical fixtures that required acceptance cases need. It has one row
per device type derived from the 280 decoded unit specifications and the
C-Gate catalogue, one row per programming method, and explicit CNI/PCI
interface, one- to six-bridge topology, wireless gateway, DALI gateway and
ballast, eDLT USB DFU bootloader, eDLT/DLT display, power-cycle, electrical
and reference-network rows. Each row has a stable `fixture:` ID, family,
required observables, owning work items and issues, a status, and input
SHA-256 digests. It never contains specification content. Every fixture is
`unavailable` today; `provisioned` requires a private manifest reference, and
neither status is acceptance evidence.

`build_hardware_fixture_matrix.py --check` regenerates the matrix from
`CBUS_UNITSPEC_DIR` and `CBUS_LOCAL_CGATE_VENDOR` and fails when they are
absent. `--verify` checks the committed matrix without private inputs. The
parity register marks a physical dimension `blocked`, not not-applicable or
`unassessed`, when it requires unavailable fixtures, and names them in
`blocker_ids`. `coverage` reports blocked counts separately, and a blocked
dimension never counts as accepted. A private hardware gate manifest should
select tests for provisioned fixture IDs only.

Both provisioned jobs upload the JSON receipt and JUnit report, then run
`.venv/bin/cbus-toolkit coverage --evidence-root . --require-complete` directly
from `toolkit-cli/`. The explicit root verifies the recorded input and report
bytes against the checked-out acceptance snapshot. That final
command remains nonzero while the census or any implementation/acceptance
requirement is incomplete. `make coverage` is only an informational local
summary that prints the same status without enforcing it; use
`make require-complete` or the direct command for a release decision.

Do not equate offline test success with complete Toolkit parity. Run `cbus-toolkit coverage --require-complete` to inspect that separate gate, and consult the [Toolkit status and acceptance evidence](../toolkit-cli/docs/implementation-status.md) for full validation requirements.

## Test data

The loaded-project barcode CLI module runs four public parents against
`cgate-mock` and five against `cmqttd`, including authenticated apply, separate
save/reload and daemon restart. Synthetic catalogue/project fixtures cover
duplicate selection, first-free and explicit addresses, unrelated raw labels,
incomplete Units, stale inputs, lost replies and initializer refusals. The
tests retain exact tagged wire bytes and verify that no PP, implicit save,
delete, rollback or retry occurs. These owned software peers establish the
documented workflow only; the retained original scanner vectors and native
Unit receipts are separate component evidence, and physical scanner/Toolkit
GUI/controller acceptance remains open.

The named database CLI journey runs in both interoperability selections through
explicit `[mock]` and `[daemon]` test nodes. Every CLI subprocess selects its
project on the same connection before using OIDs; the journey checks fresh copy
identities, Level values, refusals, explicit save/reload and neighbouring graphs.
The mock uses `--native-project-archives` and public FILE upload/PROJECT RESTORE
to import complete named XML. The daemon uses real NET CREATE/NET SAVE DB
materialization. This does not claim mock runtime-definition materialization.
Tests own their child processes, loopback listeners, inert broker, PCI simulator
and no-contact CNI trap, and verify cleanup. With no configured binary they skip
explicitly; these provisioning skips are separate from configured passes. The
original C-Gate component test is independently provisioned and does not replace
the complete native or hardware release gates. See the
[named workflow report](../toolkit-cli/docs/feature-batch-2026-10-01-named-database-workflows.md).
The latest corrected candidate uses focused source and noneditable installed-wheel
checks against owned Rust peers. Original Toolkit/C-Gate acceptance is deferred
to [issue #72](https://github.com/mitchell-johnson/cbus/issues/72); historical
native captures support bounded contracts and receive no current execution credit.
The selected-serial live fixture copies the immutable golden plan before giving
its OS-backed receipt the existing 200 ms fixture window. A separate partial
receipt test requires durable uncertainty, one send and no automatic replay.

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

The resilience tests also cover three fault paths. In a broker crash and restart, the daemon resubscribes and republishes discovery without fabricating state. After a plain-TCP CNI drop, the daemon exits and a supervisor restart recovers it. Two MQTT clients each receive every state publish from a burst of bus events. The [staging rehearsal](deployment-rehearsal.md) repeats the broker, CNI and rollback checks with Docker against Mosquitto and `cbus-simulator`. It is offline evidence only.

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

`cgate-mock` tests exercise tagged framing, multiline replies, shared state, per-session project selection, event filtering and fanout, here-documents, command inventory reachability, and programming access. Focused `DBSETXML` tests cover scalar fields and complete typed Unit, Level, NetVar, Group, Application, and Network/Interface replacement, including mixed Network documents with Unit and Application children; submitted-root `301 OID` receipts; Unit scalar/PP ambiguity checks; the captured Application/Unit, two-Unit and two-leaf-Application duplicate-OID shapes, other OID and sibling-address conflicts before mutation; subtree retirement; selective nested namespace/comment/PI retention; and copy/rename/delete/archive/restart lifecycle. The production Python C-Gate client and real cmqttd daemon repeat typed subtree exchanges. Hardware-service tests pin configured-Network replacement at the same address/interface binding, preservation of physical inventory/live levels/state/retries, durable restart readback, rollback for a move or rebind, and no PCI I/O. One owned native C-Gate 3.4.0.2001 combined Network/Application/Unit case pins the `301` root-OID receipt, schema-ordered plain Unit readback and a missing-`UnitName` `446` without mutation. The [combined](../toolkit-cli/docs/native-cgate-dbsetxml-combined-vm.md) and [direct-Unit](../toolkit-cli/docs/native-cgate-dbsetxml-unit-mapper-vm.md) disposable-VM oracles pin exact original tagged wire for acceptance and unknown namespaced Unit attribute/child omission. A source-bound owned-loopback duplicate-OID capture pins separate Unit scalar/PP values through native save/reload and direct replacement; two Rust vectors compare ten immediate readbacks, and a service test checks JSON restart and no PCI I/O. The [289-request owned five-/six-Unit capture](../toolkit-cli/docs/native-cgate-five-plus-unit-oid-mutations.md) pins all five OID verbs, scrambled submission order, direct sibling preservation and delete/reload selection against the original service; focused source-bound Python and Rust replay tests cover it. The [1,551-request owned large/cross-Network capture](../toolkit-cli/docs/native-cgate-large-cross-network-oid.md) pins seven/eight Unit collisions and both insertion orders for four two-Network Unit/Application arrangements across all five OID verbs, direct readback and save/close/load; focused source-bound Python and Rust replay tests cover all 50 cases. The [184-request owned cross-kind capture](../toolkit-cli/docs/native-cgate-cross-kind-oid-mutations.md) pins both Application/Unit XML orders, all five OID-targeted mutation verbs, direct and OID readback, and save/close/load fallback; a Rust replay and focused real cmqttd TCP test verify the same bounded behavior. A second [owned-loopback Application-pair capture](../toolkit-cli/docs/native-cgate-dbsetxml-duplicate-applications.md) pins both Applications through native save/reload and direct/OID TagName mutation; a Rust vector replays all captured post-setup transactions and a service test checks JSON restart and no PCI I/O. A source-bound owned-loopback differential passes 12/12 Unit mapper cases plus 2/2 full combined Network readbacks on each Rust server with exact `343/347/344` XML wire framing, including the LF-only declaration row. The [fresh framing oracle](../toolkit-cli/docs/native-cgate-dbgetxml-framing-vm.md) also pins address/OID reads, an absent Unit, and a pipelined `DBGETXML`/`NOOP`. This is not broad vendor XML or physical acceptance. `rust/testdata/fixtures/native_cgate_dbsetxml_combined.json`, `rust/testdata/fixtures/native_cgate_dbsetxml_combined_vm.json`, `rust/testdata/fixtures/native_cgate_legacy_database.json` and `rust/testdata/vectors/cgate_dbsetxml.jsonl` retain the corresponding oracles and vectors.

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

`cmqttd/tests/system_cgate_pp_liveness.rs` runs a 16-chunk direct `PP SAVE`
against a scripted unit on the shared fake PCI. While a STORE is unacknowledged,
MQTT commands still reach the wire once each, in publish order, within a bound
derived from `FlowConfig` (`rto_max + silent_hold + error_pause + 2 x min_gap`
plus 1 s slack). Their state echoes follow PCI confirmation, and bus observations
reach MQTT and C-Gate `EVENT` rows in bus order. A PCI loss mid-save
(ESP32-WiFi reconnect mode) returns 502 with the confirmed-write count, replays
no STORE, ignores a late ACK and only writes the remaining chunks on an explicit
new save. A broker outage mid-save leaves the save and 80 C-Gate events
unaffected; on reconnect cmqttd resubscribes, republishes discovery and bridge
state, delivers the queued observations and republishes the last observed or
confirmed light state (`broker_restart_republishes_observed_light_state`). The mini broker's
`disconnect_clients`/`set_refusing` emulate that outage. These are scripted
loopback tests, not physical programming or broker acceptance.

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

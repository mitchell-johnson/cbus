# Current Rust Unit and combined Network XML mapper receipts

The routed transport changes left two retained mapper receipts bound to older
Rust source. CI for `4f1b604b81a4e63af343c39e583d13399aa6f2e3` failed the two
current-receipt tests and their mutation-rejection test. The strict validator
rejected the source closure before it reached the intended wire checks. The
subsequent Clippy correction did not change this closure.

The completed historical CI logs report these results:

| Job on `4f1b604b` | Reported offline result |
| --- | --- |
| [Source](https://github.com/mitchell-johnson/cbus/actions/runs/36728608029/job/109931899760) | 6,362 passed, three failed, 452 skipped and 30,193 subtests passed. |
| [Installed wheel](https://github.com/mitchell-johnson/cbus/actions/runs/36728608029/job/109931899732) | 6,360 passed, three failed, 612 skipped and 30,193 subtests passed. |

Both jobs report the same three mapper guard failures. Their full log hashes
are retained in the follow-up audit. These are historical failures, not current
full-suite acceptance. The original-runtime and physical jobs were skipped.

The closure deliberately includes transitive Rust dependencies rather than
only the XML mapper. Nine existing entries changed: `rust/Cargo.lock`, the
transport manifest, and transport `apply.rs`, `framing.rs`, `lib.rs`, `pci.rs`,
`pci/programming.rs`, `plan.rs` and `verify.rs`. The new
`commissioning_route.rs` and `pci/selected_serial_observation.rs` are also
included. There are no removed entries. The mock closure grows from 165 to
167 files, and cmqttd from 184 to 186.

## Genuine current-server replay

The existing producer ran against the exact current `cgate-mock` and `cmqttd`
release binaries in owned IPv4 loopback services. Each product passed twelve
ordered direct/combined Unit cases and two combined Network readbacks. All
XML payloads, `301` write receipts and `343/347/344` framing matched the
retained original wire. Generated Network/Interface OIDs and the declared
combined-response tags are the only comparison substitutions.

The [mock receipt](../research/fixtures/cgate-dbsetxml-unit-differential-mock.json)
and [cmqttd receipt](../research/fixtures/cgate-dbsetxml-unit-differential-cmqttd.json)
were produced by that execution, not by replacing hashes in old evidence.
Their source maps and binary hashes remained unchanged throughout replay.
Independent review reversed each public derivative to its raw result exactly:
only `/binary/path` and `/command` contain normalized path roles, with an added
provenance declaration retaining the raw and prior receipt hashes.

The immutable original Unit and combined Network fixtures retain SHA-256
`6ae63e7a36de13cdd5af034ba132dcda9b452dc5bc3a5e403a3213423e9ce70d`
and `7d850980d52a05103796bfcb01ca49a4fda5db23177387c0ad1d72978953abae`.
The previous public receipts remain available at the parent revision and were
also retained byte for byte privately. Historical acceptance is not relabeled.

cmqttd used only its owned PCI simulator and dummy broker. The replay performs
closed-database provisioning without opening the synthetic Network. Its stored
loopback CNI coordinate is not a connection measurement; CNI connection counts
remain unmeasured. No original C-Gate/Toolkit process, VM, physical device or
site endpoint was used. This adds current Rust compatibility evidence for the
captured forms, not complete XML-schema, GUI or physical parity.

The first replay attempt stopped before any cases when the mock did not
announce an owned loopback listener. Its log remains preserved. A subsequent
invocation completed both products; its raw receipts and logs are separately
fingerprinted. The strict validator, source and tests were not weakened.

## Validation boundary

The [focused acceptance receipt](acceptance/2026-10-01-unit-mapper/acceptance.json)
and [independent root audit](acceptance/2026-10-01-unit-mapper/root-validation.json)
record these results:

| Check | Result |
| --- | --- |
| Source selection | 57 distinct normal tests and 24 subtests passed; zero failures, errors, skips or exclusions. |
| Isolated installed wheel | The same 57 nodes and 24 subtests passed; all 321 product files match source, wheel and installation. |
| Executed product imports | 19 main-process origins per context; 20 installed finder resolutions and two 150-module subprocess import audits agree with installed bytes. |
| References and resources | The explicit prior 2,753-reference roster was hashed in place before/after; each context recorded 171 resource samples, with minimum internal free space above 3 GB. |

The selection contains seven complete modules and three exact package/register
guards. It includes all three formerly failing mapper tests, immutable
Unit/combined/framing fixture checks, retained `SESSION_ID` guards and two
genuine Rust client/pipelined-XML interoperability cases per context. The
`SESSION_ID` server replay and original producers were not repeated. JUnit
contains 57 testcase elements; its suite counter of 81 includes the 24 subtests.
The 195 phase reports are setup/call/teardown events, not distinct tests.

Counts from these layers overlap and must not be added. The reused raw wheel
runner retains inherited deselection prose and a boolean from an earlier
selection. Neither provides evidence of exclusions here: no original-runtime
producer was selected, and actual collection/call records show zero exclusions.
The public qualifications and root audit explicitly preserve this distinction.

Two path-parser setup failures and an intentional replacement of that scanner
occurred before build, collection or test execution. Their partial task-owned
artifacts remain preserved. The final setup used the explicit prior reference
roster instead of inferring paths from prose. A finalizer field-name correction
did not rerun or modify the executed tests or their raw results.

The earlier routed batch's receipts retain their own original bindings. No full
local suite ran for these two fixture changes. Final publication adds only
documentation after execution; its declared reference delta is recorded in the
root audit.

The broad ledger remains 18/42 (42.86%). The functional denominator is
incomplete and full Toolkit/C-Gate parity remains unfinished. Subsequent CI
must be checked against the published revision; a passing replay alone does
not establish a green workflow.

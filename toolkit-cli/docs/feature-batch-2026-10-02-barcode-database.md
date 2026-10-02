# Barcode commissioning of a loaded project

`cbus-toolkit cgate database barcode-add` now carries the retained Units-view
barcode policy into a loaded C-Gate database. It previews a scan, selects an
existing project-wide serial match, or creates and verifies one new Unit through
`cgate-mock` or the C-Gate service in `cmqttd`. MQTT remains available alongside
that database service. This completes a major software workflow within
[issue #58](https://github.com/mitchell-johnson/cbus/issues/58); the issue's
remaining scanner, GUI and controller scope stays open.

## Using the workflow

```sh
cbus-toolkit cgate --host HOST --port PORT database barcode-add //PROJECT/NETWORK \
  --project PROJECT --catalog PRIVATE_CATALOG.xml \
  --barcode '5031NL          123456789012'
```

Use an existing project and its exact Network Address. A named Address is
independent of the physical NetworkNumber. The command previews by default.
Inspect the proposed address, tag, catalogue match, warnings and input hashes;
add `--apply --exclusive-project` to create the Unit. Optional
`--expect-project-sha256` and `--expect-catalog-sha256` bind reviewed inputs.
`--barcode -` reads one wedge line from stdin, and `CBUS_UNIT_CATALOG` can supply
the catalogue path. `--auth-token-file` supports a private cmqttd recovery LOGIN
token with redacted operator evidence.

The policy preserves the original component's catalogue lookup, first revision
type, default firmware, serial normalization, project-order duplicate selection,
first-free address, dialog address choices, family checks and warning order.
The independent zero-prefixed serial branch sees the conceptual new Unit.
`--tag-name` changes TagName while UnitName remains `NEWUNIT`. The offline XML/CBZ
editor retains its existing State=New marker; native Unit XML omits that Toolkit
staging metadata. The offline API and outputs remain compatible.

## Database and failure behavior

Local inputs are checked before connection. The CLI authenticates optionally,
selects the project once and reads its complete XML. Preview, duplicates and
serial-only misses do not mutate the database. Apply rechecks the exact catalogue
bytes and project snapshot before issuing one SAFE Unit ADD. A fresh-read check
is not a server-side compare-and-swap; exclusive editing ownership remains the
caller's responsibility.

The server-issued OID is checked against the original project, including its
Project OID, and bound to the Unit's exact addressed XML before one complete
Unit initializer. Final verification checks the Unit XML, all eight scalar
fields and the whole-project new Unit again, then compares every unrelated
project node. Comments, processing instructions, namespace attributes,
programming parameters and significant text remain part of preservation checks.

The Rust backend admits named Unit construction and validates direct replacement
of only the selected independent Unit, preserving unrelated raw labels,
incomplete Units and decorated Networks. Complete external Network admission
remains strict. Existing direct Unit OID/address replacement and Unit/Application
shared-OID compatibility remain available. Exact stored-address conflicts,
foreign OIDs and unsupported duplicate identity kinds refuse atomically.
The barcode adapter separately requires a newly issued OID absent from its
baseline. Numeric SAFE Unit ADD now
returns the native `301 OID=...` receipt pinned by sixteen retained original
setup cases. Unsafe numeric creation retains its existing receipt. Named
Unit COPY remains outside this new scope.

The command does not load PP defaults, program hardware, save/reload a project,
delete, roll back or retry. Save separately when the loaded edit should become
the saved baseline. A refused initializer leaves the confirmed scaffold visible.
A lost ADD or initializer receipt retains uncertainty. Invalid or reused ADD
identity also remains unresolved and never triggers initialization. Preserve
`barcode_database_evidence` after a failure and inspect the database independently
before further writes. Output or connection cleanup failure retains a confirmed
edit separately from delivery of the result.

## Validation and evidence boundary

All four required Rust 1.99 checks passed: formatting, workspace Clippy with
warnings denied, release build and workspace tests. The workspace log contains
8,655 passes, zero failures and one ignored private-project test. Two earlier
workspace attempts retained exact failures from old SAFE Unit `200` setup
assertions; those assertions were corrected to the retained native `301` receipt.

Focused source and a fresh, noneditable installed wheel each passed 92 parent
tests and 67 separate, unitemized subtests, with no failures, errors or skips.
All 327 package files match source, wheel and installation, and all 417 frozen
source/resource pins remained unchanged during those runs. Each public nine-parent
subset records 64 CLI calls, 48 connections, 198 tagged commands, 11 document
bodies and four deliberately lost native receipts. All 18 owned processes were
cleaned up; fake PCI traffic consists only of 80 startup frames, with no later
frames or CNI trap contacts. Authentication, separate save/reload, daemon restart,
stale inputs, exact-once failures and complete project preservation are covered.

`make check-interop` passed 192 parent/framing tests with two vendor-specification
skips and 227 separate subtests. Its actual execution precedes the final
owner-description and equivalent vector-key correction; both input versions
and an independent semantic comparison are retained. The final source/wheel
runs execute the corrected version. Initial public attempts retain nine invalid
Level-fixture failures and then two overly broad numeric-envelope assumptions;
the final assertions require the exact measured reply, without accepting either
status indiscriminately.

Six actual modeled comparisons were published directly from their literal
outputs. Their 1,123 bindings over 210 distinct declared source inputs remain
current. All 261 resource-consumer parents passed with one original-input skip
and 934 separate subtests; subsequent wording checks preserve their original
execution contexts. Independent review verified the required Rust totals,
public journeys, interop records, wording delta and final installed-wheel proof.
The full Python suite was not repeated. See the
[bounded release receipt](../research/fixtures/barcode-database-owned-release-20261002.json)
for artifact/source hashes, separate counts, historical failures and the final
documentation delta.

The restored numeric test Network has Address and NetworkNumber `11`, and the
retained daemon state confirms its assigned numeric owner. Unit ADD uses that
typed owner; qualified scalar reads use the retained tag route and terminate
with `342`. This does not establish the separate bare/runtime-only scalar route
or renamed/alternate numeric Network paths.

The retained 73 original-instruction barcode vectors and sixteen native SAFE
Unit creation receipts support components. They do not execute the new complete
Toolkit workflow. Current original/vendor/VM/hardware execution is zero. The
independent named Unit XML route keeps its historical opaque metadata retention;
the numeric mapper keeps its existing schema normalization. Plain new barcode
Units use the retained native schema order in both.

## Outstanding work

KEYGL5/Hydra sibling scanner routines, original Tag Name dialog validation,
original parent-form timing and physical USB scanner behavior remain unaccepted.
Physical inventory selection is outside the database-only scan policy. Broader
Schneider native-server creation, defaults, save/reload and GUI comparisons need
their own acceptance. PICED/controller handoff remains an evidence question;
the prior negative static search is not a fabricated integration contract.

The broad ledger stays at 18 implemented of 42 categories, with zero fully
accepted functional obligations. The functional denominator is incomplete,
so this workflow does not establish a percentage of full Toolkit functionality.
Associated COPY/LOAD corrections deferred in
[issue #74](https://github.com/mitchell-johnson/cbus/issues/74) are unchanged.

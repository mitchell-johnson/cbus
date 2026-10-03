# Thermostat Unicode default-name lookup — 4 October 2026

The Toolkit CLI now loads missing ordinary output and programmable-damper
defaults when the application also contains Unicode group names. It reuses a
unique ASCII-equivalent generated name or creates the actual ASCII default at
the requested missing address. Existing-address access retains its previous
rename behavior. See the [operator guide](thermostat-default-names.md) and
[owned receipt](../research/fixtures/thermostat-unicode-defaults-owned-release-20261004.json).

The recovered comparison changes ASCII letters only. `é`/`É`, `Ω`/`ω` and
`straße`/`STRASSE` remain distinct. Duplicate generated-name matches still
refuse until original manager ordering is established. This does not expose
caller-defined Unicode generated defaults or implement application migration.
Shared references, OIDs and exact optional existing Level Value metadata remain
preserved; new Level creation remains strict. Uncertain writes stop without replay.

## Current focused acceptance

Source and a separately built installed wheel each passed **251 parent tests
and 976 separately counted subtests**, with **six optional source-input skips**.
All 19 required module bodies and all **108 backend identities** passed in each
phase: 54 per server, with 92 retained cases and 16 new Unicode-inventory cases.
These overlapping cohorts are not added to earlier thermostat totals.

Independent artifact review reconstructed 178 public CLI executions/connections,
14,292 tagged commands, 140 successful exits and 38 expected refusal/uncertain
exits per phase. All 108 owned service PIDs were cleaned up. The software PCI
peers saw 432 startup frames and zero later/trap traffic. Controlled losses
covered 14 successful 200 and two successful 301 replies; the new Unicode cases
drop a quoted TagName DBSET 200, not a SAVE. Six controlled stale-graph changes
were verified. Complete synthetic 98/109-field PP, graph/OID/opaque-Value
preservation, exact quoted names and successful fresh close/reload were checked.
Raw writer family labels and exact passing pytest IDs are checked separately;
they are not claimed to map one-to-one.

The fresh wheel SHA256 is `8b85f053d77f0efa6d15c1136ca3887090b2e7dacc47b5b1bbffa16b988a3fb6`.
All 389 package files match source, ZIP and installed bytes. The internal
reference copy contains 4,121 distinct source files and two declared extras.
Actual source pytest PID 65305 and installed pytest PID
64764 have hash-bound startup/terminal module origins;
these are snapshots, not continuous import tracing. Source, package, clone,
freeze, all 473 Rust inputs and the accepted immutable server pair stayed exact.

The first source epoch failed all 108 backend setups at sandbox EPERM before
service startup, while its 143 offline parents and 976 subtests passed. That
failure remains recorded. The separate successful source epoch used identical
frozen inputs with owned localhost access. No failed epoch was relabelled.

## Source and metadata evidence

A fresh read-only EXE/MAP data check passed for five dependency spans and
15 semantic checks. It confirms ASCII-only case conversion followed by exact
UTF-16 equality and the source table's 174 rows, 48 nonempty ASCII labels and
four ASCII damper labels. No original instructions or original software ran.
The six ordinary source-input skips remain disclosed; this separate data check
does not earn original GUI, native-server or physical acceptance.

Seven owned compatibility capture/check commands and five census/register/check
commands passed. The six captures cover 64 primary cases and four combined Unit
checks, with 1,183 source bindings across 220 distinct files. Saved native and
pre-fix references remain unchanged. The Make roster has 829 unique backend
selectors, preserving all 813 predecessors and the inherited 745 identities.
Rust source did not change; its retained four-gate build passed 8,730 tests with
one ignored. No full Python suite, Rust suite or release rebuild was repeated.

## Remaining scope

Fresh installed `coverage --require-complete` exited 1 with completion, census
and denominator readiness false: 487 obligations, none fully accepted, three
defined and 484 provisional. The category ledger remains 18 implemented,
22 in progress and two pending out of 42. Its 42.9% measures categories, not
functional parity. The copied-root diagnostic also exited 1, refusing a missing
ignored historical native receipt before emitting a coverage payload; no trusted
reference verification pass is claimed.

Application migration, exposed Delete behavior, wider manager/locale histories,
implicit GUI notifications and complete original/native/hardware acceptance
remain under issues #42/#72. The preceding [Edit integration](feature-batch-2026-10-04-thermostat-output-edit-integration.md)
and repository-wide CI/default-branch integration are separate checkpoints.
Full parity, current CI green and a main merge are not claimed here.

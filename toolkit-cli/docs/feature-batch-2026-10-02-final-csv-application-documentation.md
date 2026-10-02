# Final CSV type admission, Application Add and database documentation

This batch adds the last 48 statically registered CSV types, ordered eDLT
Application Add and Reset/Add histories, and live database documentation with
additional device tables. Work used three parallel implementation lanes,
public integration and separate read-only reviews. Full Toolkit parity remains
unfinished: the broad ledger is 18/42 implemented areas, and the functional
denominator is unresolved. The category ratio is not a functionality estimate.

Work began on 2 October 2026; the final publication is dated 3 October 2026
(Pacific/Auckland). Artifact names retain the batch start date.

## Completed software scope

[CSV profiles](database-csv-last-profiles.md) now admit **262/262 static unit
types** and **424/425 registration rows** at explicit firmware/class/state
profiles. The duplicate KEYGL5/TKEYGL5 row has no exact-class agent and remains
refused; the separate 5.5.00/5055EDL profile is supported. The new scope includes
temperature scalar groups, SENTEMPB application-dependent associations, IOPE
output initialization, infrastructure Application255 and wireless fan/output
channels. 62 complete invented fixture Units have independent literal CSV rows;
112 firmware endpoint cases supplement the historical vectors. Cached v4 still
requires authoritative Application and Group identities. Type admission does
not establish all firmware/state combinations or native GUI/provider parity.

[Application Add](edlt-application-reset-add.md) uses the corrected original
owner/eDLT overload, explicit creation preferences, allowed address catalogue,
locked standard names, first-free allocation, ordered local/cross-network
validation and reserved-address confirmation. Nonempty Description is a
separate database assignment after issued creation. Operation-1 Reset/Add
consumes the fresh model, preserving the earlier scene/proximity getter
allocations. Old generic Add, Corridor, Activation and retained SceneManager
can compose before one parent PP save. Metadata, PP SAVE and PROJECT SAVE
remain separate operations, and an uncertain save is never replayed.

[`cgate database-document`](native-project-documentation.md) now generates
HTML from one fresh complete DBGETXML snapshot through cmqttd or an admitted
C-Gate service. It binds Project.Address independently of TagName, requires
exact 343/347/344 framing, preserves existing files and creates no output after
an interrupted read. It sends no network OPEN, scan, physical PP LOAD or SAVE.
The saved-project renderer adds eight source-pinned factory profiles across
seven light-level, WHAA and DALI types, with ten literal body/usage/action
cases. [Exact profile limits](project-documentation-remaining.md) preserve
unresolved multisensor loaders, scenes, omitted state and whole-page parity.

## Review corrections and retained failures

Independent review found the database document reader initially accepted an
unrelated continuation or a missing XML opener. It now requires exact native
framing, with five malformed-wire atomic/no-replay cases. The parent review
strengthened Reset preservation checks against every supplied default outside
explicit terminal owners, and added an initial48 → Reset56 → cancelled
Application Add counterexample. Source inspection verified the 23 Application
method spans and corrected overload premise. Final review found that issued-OID
collision checks covered only selected objects; the manager now checks all
observed unnamespaced OIDs in the original and fresh Project snapshots before
initialization. A colliding receipt stops without Description writes, PP saves
or inverse deletion of an existing object; literal foreign-object cases cover
that failure boundary.

Actual parent interoperability exposed two distinct Description gaps: Rust
acknowledged an issued-OID assignment but its getter could not read the value,
and the XML export omitted the field. The scalar setter now stores Application
and Group descriptions under the canonical project object and in its durable
field map. The parent verifies the nonempty scalar at its issued UUID before
PP save and after reload, separately from XML graph preservation. Empty
descriptions make no assignment or null-readback claim. Original inherited descriptor mapping is static
evidence, not proof of runtime XML behavior. The broader native XML round-trip
gap is tracked in [issue 75](https://github.com/mitchell-johnson/cbus/issues/75).

Author failures remain private and are not execution credit: invalid synthetic
fixture fields, sandbox loopback restrictions, oracle transcriptions, an old
generic Add routing regression and stale static bindings were corrected.
The initial documentation sandbox attempts were reported by tools; later
retained harness attempts have raw logs/JUnit/trace. Static reads of original
EXE/MAP are source proof, not original-instruction execution.

Previous publication CI run 36988443730 passed Rust checks and both maintained
backend interoperability targets, but exposed 20 Python
failures: stale refusal assertions for newly admitted conversions/CSV, and
six partially sanitized evidence receipts whose commands had lost private
roles while artifact coordinates remained. The new tests preserve pre-I/O
specification guards. The maintained sanitizer now publishes full derivatives
from retained actual raw receipts; wire cases, artifact digests and claims are
unchanged. Shared Make/CI updates and the Rust scalar fix trigger fresh modeled
compatibility captures against newly built owned Rust binaries. Their raw logs/receipts stay
private; published derivatives retain explicit mappings and raw hashes.

## Validation and remaining acceptance

The [bounded release receipt](../research/fixtures/final-csv-application-documentation-owned-release-20261002.json)
records exact commands, input and artifact hashes, reviews and retained failures.
Required Rust formatting, workspace Clippy, workspace tests and release build
passed: **8,697 tests passed, zero failed and one private-input case ignored**.
Both owned binaries were freshly built. Actual issued-OID Description reads
pass before and after save/reload in both services, and after a distinct cmqttd
process restart; whole XML remains unchanged and does not acquire Description.

The selected **48 Python modules** ran in source and an isolated installed
wheel, with all **3,748 inputs and both binaries unchanged** during each run.
Both selections retained exit 1 from three stale refusal subcases in one
registry test; every other selected test passed or had an explicit provisioned
input skip. The corrected whole registry module then passed separately in
both environments: **11 parent tests, 1,282 subtests and one original-input
skip**. All eight malformed/refusal inputs and atomic no-output assertions
remain. Runtime code is unchanged by that correction. The earlier selections
are not relabeled green, and overlapping checks are not summed.

The retained pytest headlines report 1,278 passing parents, 12,907 passing
subtests, three failed subtests and 13 skips per environment. Their JUnit
auditor instead classifies the failing outer testcase as failed: 1,277 passing
parents, 12,908 passing subtests, one failed parent and two failed subtests.
The aggregate counts agree. The receipt preserves both classifications and
all 13 skipped IDs; these original/source/native provisioning skips provide
no acceptance credit. All 338 runtime files match source, wheel and installed
bytes, with no outside-runtime imports in the actual process guard. The
publication wheel SHA-256 is
`c5258385e275e3519452b8d47f705279fab8ef16f7599931d08ff19d5b9f1b2a`.

Initial source/wheel attempts ran out of local disk space before complete
JUnit/trace/summary artifacts could be written and receive no test credit.
Recovery verified every file in an older completed validation archive before
moving it to external storage and preserving its original path. Fresh selected
runs wrote artifacts there. The full Python suite was not repeated locally.
The 20 new public journeys per backend are required by both maintained targets
and their CI auditors. Publication-head CI is a separate automatic check;
this local receipt makes no claim about its outcome.

The main outstanding boundaries remain original GUI/parent initialization and
page byte/visual capture, print/progress/cancel, complete firmware/model states,
private repository/provider behavior and applicable hardware persistence,
rendering, recovery and deployment. The four remaining conversion directions
are unchanged. Issue 72 retains manual/original acceptance, issue 73 retains
selector work, and issue 74 retains cyber-deferred corrections. No original
instructions were executed, and no Windows VM, house service or physical
network was used for this batch. MQTT behavior is unchanged; the narrow Rust Description fix
and Python workflows are tested through both maintained Rust services.

# Functional parity register

`cbus-toolkit coverage` now derives its completion result from packaged
functional-obligation and evidence records. The 39-row feature ledger remains
visible as historical planning information, but changing its labels cannot
make the completion gate pass.

The register remains provisional. It accounts for every committed source
surface currently available without treating unlike records as equal functions.
The first three defined functional obligations are narrow C-Gate session
identity outcomes; they do not complete the broader command paths:

| Source record | Count |
| --- | ---: |
| Indexed help topics | 3,767 |
| Page headings | 3,680 |
| Page anchors | 1,349 |
| Device-dialog candidates | 118 |
| Macro-reference leaves | 179 |
| Unindexed HTML files | 6 |
| Public C-Gate command blocks | 209 |
| Maintained C-Gate primary paths | 431 |
| cmqttd supplement paths | 11 |
| Executable Delphi form resources | 412 |
| Executable component/control instances | 10,102 |
| Executable event bindings | 1,892 |
| **Total provisional scope records** | **22,156** |

The same help topic can contribute a navigation record, headings, anchors,
dialog membership and a macro leaf. These records are source accounting, not
a denominator to sum. P0 must review and deduplicate them into stable user
outcomes, reconcile conditions and undocumented branches, expand C-Gate paths
into valid selector/state/effect contracts, and partition the device and
firmware domains. Until that finishes, `denominator_ready` and
`functional_percent_available` are false and functional percentages are
`null`.

The [original Toolkit Dynamic Label Editor observation](edlt-dynamic-cache-boundary.md)
adds a hash-bound offline GUI and project-XML cross-check to the existing
provisional eDLT scope. It distinguishes application/group `TagDLT` data from
unit `StaticTextString` parameters. It adds no accepted obligation receipt,
changes no provisional source count, and supplies no physical cache readback.

## Files and regeneration

- `src/cbus_toolkit/parity-obligations.json` contains the source inventory,
  provisional scope mappings and obligation records. It contains one
  source-bound provisional obligation for each of the 442 C-Gate paths, the
  42 historical umbrella obligations, and three scoped `SESSION_ID` functions.
- `src/cbus_toolkit/parity-evidence.json` contains a scoped, source-bound
  `SESSION_ID` original-differential receipt and a separate physical
  applicability decision. Historical paths and test filenames remain outside
  acceptance evidence.
- `src/cbus_toolkit/parity.py` validates both documents and derives progress.
- `research/workflow-completion-criteria.json` holds the reviewed completion
  criteria for each workflow and allocates every ledger row to one workflow.
- `research/parity-denominator-history.json` versions the denominator. The
  register's `denominator_version` is its last entry.
- `research/closure-receipts.json` holds machine-readable roadmap closure
  receipts. The builder copies all three into the packaged register.
- `src/cbus_toolkit/cgate-contract-inventory.json` contains one versioned,
  digest-bound contract record for each of the 431 primary and 11 supplement
  C-Gate paths.
- `research/build_cgate_contract_inventory.py` derives that inventory from the
  Rust routing matrix, declarative application arities, endpoint authorization
  policy, public-help syntax hashes and ten sanitized native handler-role
  probes. It records unknown selector/state fields explicitly instead
  of deriving them from a command name.
- `research/build_parity_register.py` regenerates the provisional register
  deterministically from the committed documentation/executable surface
  censuses, feature ledger, Rust capability matrix, parity roadmap and
  `research/functional-obligation-pilot.json`. The pilot manifest pins exact
  public-help syntax, path-contract and owned native-session capture hashes.
- [The `SESSION_ID` differential](cgate-session-differential.md) retains a red
  pre-fix mock receipt and separate green mock and production cmqttd receipts.
  Each evidence record carries the report's recorded source closure as its
  `invalidates_on` rule; the builder refuses to credit a receipt whose inputs
  changed.
- `research/cgate_session_physical_applicability.py` verifies the retained
  native loopback capture, the three pinned path contracts and their resolved
  no-bus-I/O boundary. Its report records a separate physical
  `not_applicable` decision for each narrow session function.
- `docs/toolkit-executable-surface.json` is the sanitized Toolkit 1.18.0
  executable inventory. It records names and hashes for 412 parsed Delphi form
  resources, 10,102 component/control instances and 1,892 event bindings.
- `research/extract_toolkit_executable_surface.py` reproduces that inventory
  from an explicitly supplied Toolkit executable and MAP. The inputs are
  identified by SHA-256 and remain outside Git.
- `docs/toolkit-dialog-map.json` (`research/map_dialog_candidates.py`) supplies
  the ledger rows for the 118 dialog scope items. The 101 dialogs that resolve
  unit types, a director or unit-dialog form and a specific row use that row,
  and their form resources, controls and events leave `toolkit-surface-census`.
  The other 17 keep their triage routing and carry `dialog_map_unresolved`
  reason codes. This is scope routing, not acceptance; the map's control
  coverage table is identification, not control acceptance.

Run:

```sh
PYTHONPATH=src python3 research/build_cgate_contract_inventory.py --check
PYTHONPATH=src python3 research/build_parity_register.py --check
cbus-toolkit coverage --evidence-root . --require-complete
```

Maintainers with the retained vendor artifacts can also reproduce the
executable inventory:

```sh
python3 research/extract_toolkit_executable_surface.py \
  --executable /path/to/CBusToolkit.exe \
  --map /path/to/CBusToolkit.map \
  --check
```

The first two commands fail when a source inventory changes without regenerating
the register. The coverage command exits nonzero until the versioned census is complete,
every obligation is defined and implemented, every applicable acceptance
dimension has matching passed evidence, every attached artifact matches its
recorded SHA-256 under the trusted root, and no required case is skipped.

Each obligation tracks implementation and applicability independently from
the required acceptance dimensions: nominal behavior, error behavior, invalid
input, profile variation, original Toolkit/C-Gate differential behavior,
physical behavior, and persistence/recovery. A dimension can be marked not
applicable only with matching passed evidence for that applicability decision.
The passed receipt must include an `applicability_receipts` entry naming the
exact obligation and dimension, `decision: not_applicable`, and a nonempty
reason. A general passed test for the dimension cannot waive that dimension;
duplicate entries within one evidence record, unreferenced decisions, and
decisions contradicting the obligation state are rejected. A passed offline
analysis may carry a decision without claiming that it exercised the physical
or original-differential dimension.
`coverage` reports accepted, not-applicable, blocked and unassessed counts for
each dimension. Their percentages remain `null` until the denominator is
complete, alongside the implementation and overall acceptance percentages.

A dimension is `blocked` only when an `acceptance_blockers` entry for it gives a
`reason_kind` and a nonempty list of `blocker_ids`. Each ID must name a fixture
in the packaged `hardware_fixture_roster`, which is projected from the
digest-bound [hardware fixture matrix](../research/hardware-fixture-matrix.json).
At least one named fixture must still be unavailable. Reason
`hardware_fixture_unavailable` admits only the physical dimension.
`power_cycle_rig_unavailable` also admits persistence/recovery when a
power-cycle rig is named. Blocked cases stay in the required denominator, and
`physical_acceptance` reports the number of unavailable fixtures behind them. A
blocked dimension is never accepted or not applicable. `unassessed` means that
no requirement or blocker has been decided.

## Workflow completion criteria

Criteria are fixed per workflow before any status changes. There is one record
for each of the 26 Toolkit help workflow families in `toolkit-surface.json`,
one for the C-Gate command service, which is not a Toolkit help family, and
one placeholder, `workflow:unallocated-umbrella`. Each record names:

- `minimum_dimensions`: the acceptance dimensions every member obligation must
  require. Nominal, error and invalid-input behavior are always required.
- `oracles`: which of `gui` (original Toolkit), `model` (original project,
  database or unit-specification model), `cgate` (native C-Gate) and
  `physical` judge the workflow. An original-differential minimum needs a GUI,
  model or C-Gate oracle.
- `physical_evidence` and `persistence_evidence`: `required`, `conditional` or
  `not_required`. `required` must match the minimum dimensions, and required
  physical evidence needs a physical oracle. `conditional` means each
  obligation declares the dimension when it applies, for example a bus-routed
  C-Gate path or a database operation that writes a unit.

`ledger_workflows` allocates each of the 42 ledger rows to one workflow. The
derived C-Gate path and function obligations inherit their row's workflow.
Every obligation carries one `workflow_id` and a `required_dimensions` list.
The validator rejects an obligation with no workflow, an unknown workflow, a
list of workflows, or required dimensions that omit a workflow minimum. A required
dimension cannot be `not_applicable`, and a `blocked` dimension must be
required. The builder also rejects criteria that do not cover exactly the
Toolkit workflow families, or a ledger row without exactly one allocation.

`coverage` reports each workflow's criteria and its obligation, defined,
implemented, accepted and blocked counts. Its accepted percentage is `null`
under the same rule as the overall percentage. Four cross-workflow rows
(`toolkit-surface-census`, `toolkit-differential-acceptance`,
`unit-hardware-acceptance` and `preferences-and-update-workflow`) are
placeholder members. Seven families have no obligation yet: Application log,
Barcode, Controllers, Relay and dimmer logic, Protocol reference, Timers and
Wireless. The denominator is not ready while any workflow is empty or any
obligation remains in the placeholder.

## Denominator versioning

`denominator_history` lists every denominator as `version`, `counts`
(obligations, scope items and workflows), `digest` and `reason`. The digest is
the SHA-256 of canonical JSON containing the sorted obligation IDs, sorted
scope-item IDs and each obligation's workflow allocation. The last entry must
match `denominator_version` and the register's current counts and digest.
Changing the version, counts, membership or workflow allocation without
appending a reasoned entry fails both the builder and the packaged validator.
Versions must be unique.

The earlier entries were reconstructed from the Git history of
`parity-obligations.json`: 39 umbrella obligations (two versions), 481 after
the C-Gate path expansion, 484 after the `SESSION_ID` pilot, 486 after the
topology and project-documentation rows and 487 after the DALI row. The last
two changes reused the label `provisional-2026-09-28.1`; their history entries
version them retroactively as `provisional-2026-09-29.1` and `.2`. The
current version, `provisional-2026-09-30.1`, adds workflow allocation without
changing membership.

## Evidence invalidation

Every evidence record has an `invalidates_on` rule: sorted,
repository-relative `inputs` and a `fingerprint_sha256` over their bytes,
computed as the canonical JSON of `{path: sha256}`. When the attached report
records its own `source_fingerprint`, the rule must name exactly those inputs
and digest; a declaration cannot narrow the recorded source closure.

With a source checkout, the validator recomputes each fingerprint and rejects
a stale record or a missing input. `coverage --evidence-root <toolkit-cli>`
uses the checkout only when the evidence root is the `toolkit-cli` directory
of a Git checkout and the running `cbus_toolkit` package was loaded from that
checkout. An installed wheel refuses to recompute: it reports
`evidence_fingerprints_verified: false` with an
`evidence_fingerprint_refusal` reason, withholds percentages and cannot
report `complete: true`.

## Closure receipts

A roadmap check box is only a claim. The builder records checked items as
`closed_work_item_ids`, and each needs a `closure_receipts` entry with the five
fields from the roadmap's closure-receipt rule:

1. `scope`: the receipt's obligation IDs, parent register obligations, native
   scope, required case IDs and reasoned `not_applicable` or `rejected`
   decisions.
2. `integration`: 40-hex integrated revisions, hash-bound source changes and
   installed artifacts, exact commands with pass, failure, error, skip and
   exit counts, preserved failed attempts, and `required_skips`, which must be
   empty. A command with skips needs a skip disposition.
3. `expected_behavior`: the independent basis and a statement for each of the
   transport, service, physical-effect, persistence and recovery layers.
4. `documentation`: capability rows, feature documents, AI references and
   issue links. From a source checkout, the documents must exist.
5. `limitations`: remaining limitations, an empty `within_required_scope`
   list and an invalidation rule with conditions, inputs and fingerprint.

The receipt artifact is bound by SHA-256. Under a trusted root, its
`work_item` and `required_case_ids` must match the record. `coverage` reports
`closed` only when the receipt is valid, its artifact bytes are verified and
its fingerprint is recomputed and current. Otherwise it reports
`receipt_unverified`, `stale_receipt` or `claimed_without_receipt`, and the
last two are listed as blockers. A receipt for an unchecked item is rejected.
P9.01 ([#60](https://github.com/mitchell-johnson/cbus/issues/60)) is the only
closed item. Its fingerprint covers the diagnostic composer, the package-bundle
producer and the four case modules.

## Validation rules

The validator rejects duplicate JSON keys, non-finite numbers, duplicate or
missing IDs, orphaned scope items, resolved domains with unknown counts,
unknown states, unknown ledger/work-item/evidence references, unsafe artifact paths,
changed evidence bundles or record digests, changed source artifact hashes,
substituted feature ledgers, unexplained skips and required skipped cases.
Every scope-item kind must have exactly one counted source-inventory domain.
Renaming, omitting or duplicating a counted domain is invalid even if all
obligations and evidence otherwise appear complete; a `census_complete` flag
cannot hide an unbound source surface.
Work-item references are checked against the packaged 59-ID authoritative roster,
so a syntactically valid but unplanned ID is rejected. The exact parsed evidence
object must equal the duplicate-key- and non-finite-safe parse of the digest-bound
evidence bytes.
Receipts also require explicit test IDs, environment identity, artifact roles
and an exit code consistent with the result. A passed record must name a
recognized machine-readable report artifact. With an evidence root, the
validator reads that report and checks its executed case IDs, per-obligation
and per-dimension coverage, applicability and scope decisions, result, source
revision and command against the
evidence declaration. The current C-Gate SESSION_ID differential additionally
checks its cmqttd endpoint, native input digest, zero failures/skips and every
reported native/Rust normalized payload pair. Rehashing a report and its
declarations cannot turn a failed or unrelated case into accepted evidence.
An original-differential oracle hash must match an attached input artifact.
Skipped case IDs must be unique and cannot also appear among the executed test
IDs. The source-checkout validator reopens and hashes every attached artifact.
Without `--evidence-root`, an installed wheel validates the
packaged receipt structure and declared digests but cannot reopen research
artifacts that are not shipped in the wheel. It therefore reports
`evidence_artifacts_verified: false`, withholds functional percentages and
cannot report `complete: true` even if all declared states are accepted.
The release acceptance runner and installed-wheel auditor verify the attached
artifacts against their source checkout or immutable snapshot root. Snapshot
preparation includes every attached artifact named by the evidence bundle,
including nested research paths, and fails if one is missing or escapes the root.
Physical evidence must name a physical environment and stable
hardware references. Original-differential evidence must bind its Toolkit or
C-Gate oracle by SHA-256. An accepted or not-applicable dimension requires
evidence; an accepted dimension also requires a passed record naming that
exact obligation and dimension.

Each C-Gate path obligation has a stable `cgate-path:` ID derived from its
command path, a `source_scope_item_id`, the exact packaged contract ID and
digest, and an explicit mapping to the `cgate-command-transport` ledger row.
The validator requires one and only one such obligation for each of the 431
primary and 11 supplement path scope items; missing, duplicate, swapped and
orphaned mappings fail. These path obligations keep implementation status,
original-differential acceptance, physical acceptance and applicability in
separate fields. All are currently provisional and `in_progress`: a reachable
dispatch route is known, but complete selector/state/effect behavior is not
accepted. Original acceptance remains `unassessed`. Physical acceptance is
`blocked` for the 234 bus-routed paths, by their interface, reference-network,
bridge-topology and device fixtures, and `unassessed` for local paths.
Applicability remains `unresolved`, and no evidence receipt is attributed to
them.

The first reviewed functional pilot defines `cgate-function:session-id-query`,
`cgate-function:session-id-all`, and `cgate-function:session-id-tag`. Each maps
to the historical `cgate-command-transport` ledger row, one public-help syntax
anchor and its own C-Gate path contract. The original C-Gate 3.4.0.2001
loopback capture pins observed nominal and error commands. A fresh cmqttd
listener with synthetic PCI matched all nine scoped native response payloads,
with zero skipped cases. The three `original_differential` dimensions are
accepted only for that owned IPv4 loopback profile. The native capture
stored tag-stripped payloads: Rust client-tag echo was checked on the wire,
but native tag-prefix framing remains outside this receipt. The refreshed
source-bound receipt compares the internal Console row and requires CRLF from
both Rust servers; the prior external-row-only receipts are stale.
The three implementation statuses remain `in_progress`; the
broad path contracts remain provisional. A second, source-bound offline report
verifies that this owned loopback profile has no bus-I/O boundary and records
`physical: not_applicable` for each of the three functions. This is an
applicability decision, not a physical-device test. Broader applicability
remains unresolved. TLS, non-loopback
peers, ACCESS/LOGIN variants and broader response/event behavior remain open.
The pilot raises the register to 484 obligations, with 3 defined and 0 fully
accepted. `census_complete` and functional percentages remain false/null.

A scope record can use `nonfunctional_with_evidence` only when one of its
`evidence_ids` names a passed receipt containing
`scope_disposition_receipts: [{"scope_item_id": "...", "decision":
"exclude_nonfunctional"}]` for that exact record. Failed, unrelated, orphaned,
unknown or differently classified receipts cannot remove source material from
the functional denominator.

Evidence receipts identify the source revision, exact command, input/output
artifact hashes, obligation IDs, acceptance dimensions, result and any
non-required skips. Native binaries, site projects, credentials and raw vendor
materials remain private; a sanitized receipt still binds their retained
artifacts by hash.

`research/acceptance.py` records the same derived progress for installed-wheel
runs. `research/audit_wheel_acceptance.py` recomputes it from the wheel's own
register and evidence bundle. Historical wheels without these files remain
auditable but can never report full parity.

## C-Gate contract expansion

Every maintained C-Gate path now has the same seven structured axes: selector
grammar, session states, target forms, authorization, response/event
envelopes, effects/routing, and implementation/acceptance. Each axis is split
into named subaxes with a `resolved` value, or a `partial` or `unresolved`
reason, and source references. A `partial` subaxis carries native evidence that
does not yet meet its resolution rule. An aggregate axis is `resolved` only
when all of its subaxes are resolved. The inventory binds every row and its axes by SHA-256, binds the
source files and the exact `requires_programming_auth` function, and is copied
into the parity register by contract ID and digest. The packaged validator
rejects altered rows, source-inventory substitution, count drift and a scope
row that no longer matches its packaged contract.

Native fixture adapters read eleven digest-pinned owned C-Gate 3.4.0.2001
fixtures (six application families, then DEPLOY_QUEUE, FILE, NET, PORT and
PP/PROGRAMMER) for 100 leaves. Argument arity, value domains and the command
envelope become `resolved` only when the fixture keeps both an accepted and a
same-class rejected native observation for the path; otherwise they are
`partial` with the retained observations. Each value cites the fixture path and
SHA-256, and the packaged validator rejects a fixture binding that differs from
the inventory sources. Shape-only fixtures record the JSON pointer and
attribution basis for every observation. The adapters also reconcile the 64
declarative model arities that have native observations and record the one
contradiction, `AUDIO OUTPUT_ERROR_CODE` with a Z form, in
`native_application_fixture_adapters`.

The current inventory resolves the command path for all 442 paths, connection
and recovery-mode behavior for all 442, peer access policy for all 442, and the
optional programming LOGIN gate for 398. Forty-four programming-gate rows
remain invocation-dependent. The five TELEPHONY leaves have an observed
`Operate` entry floor on absent objects, while later permission for configured
targets and successful physical delivery remains unresolved.
`RECALL_LAST_NUMBER_REQUEST` remains outside the optional operation-based
LOGIN gate. Their authorization axes remain partial.

The inventory also records 431 exact native handler-entry role probes, each
captured at all nine ACCESS levels against owned C-Gate 3.4.0.2001 loopback
sessions. Their pinned fixtures are
`rust/testdata/fixtures/native_cgate_authorization_probe.json` (31),
`rust/testdata/fixtures/native_cgate_authorization_expansion_probe.json` (58)
and `rust/testdata/fixtures/native_cgate_programming_authorization_probe.json`
(40 PP, PROGRAMMER and DEPLOY_QUEUE leaves), plus
`rust/testdata/fixtures/native_cgate_media_authorization_probe.json` (44 Audio,
Security and Media Transport leaves), and
`rust/testdata/fixtures/native_cgate_admin_authorization_probe.json` (22 CONFIG,
FILE, PROJECT, NET, LABEL and Measurement leaves), plus
`rust/testdata/fixtures/native_cgate_application_authorization_probe.json` (24
application leaves) and
`rust/testdata/fixtures/native_cgate_dali_authorization_probe.json` (126 DALI
paths, including 66 repeated `poll` selector invocations),
`rust/testdata/fixtures/native_cgate_remaining_authorization_probe.json` (31
PORT, ACCESS, database, identification and utility paths), and
`rust/testdata/fixtures/native_cgate_unprobed_authorization_probe.json` (22
additional database, utility, transform and session paths), and
`rust/testdata/fixtures/native_cgate_final_authorization_probe.json` (33
safe family/help, session and absent-target entries from the final 44-path
sweep). The other eleven paths showed native parser, comment, session or
cmqttd-only extension behavior without a role gradient. `ACCESS LOAD` used
one separate owned child for each role because loading even a missing file can
replace the native credential table.
Each observed lower role returned `420 Access denied.`, while the recorded
minimum role advanced past that entry gate. The generator checks each fixture,
capture script, local harness, Rust handler registry and role gradient before
emitting these known facts. All 431 `handler_roles` subaxes remain
`unresolved`: one invocation does not establish other selectors, later
object-level authorization or successful physical delivery. The corresponding
authorization axes remain partial and none gains functional acceptance.

A pinned, sanitized original C-Gate 3.4.0.2001 command-session trace, the
owned native session-selector matrix, public HELP syntax and production
endpoint now expand five command paths:
`SESSION_ID`, `SESSION_ID ALL`, `SESSION_ID TAG`, `EVENT` and `QUIT` (including
the observed `EVENTS` and `EXIT` aliases). Their absence of C-Bus address/route
targets, lack of project or programming-session preconditions, and
connection-state effects are structured and source-bound. All five paths have
resolved arities: the selector matrix confirms that native `EVENT` uses its
first mode word and that `QUIT`/`EXIT` ignore trailing words. `SESSION_ID`, `SESSION_ID ALL`, and the
`QUIT`/`EXIT` verb choice have resolved value domains. Tag text limits and
`EVENT` mode case/numeric forms remain unresolved. Native
`SESSION_ID ALL` ignores trailing words, a tag can be set only once, `EVENT`
starts at `e0s0c0`, and `QUIT`/`EXIT` flush `204` before EOF. The original trace
also includes an internal console session in `SESSION_ID ALL`; both Rust servers
now emit its native-shaped `cmd1` row. The original trace
did not exercise every ACCESS role, malformed selector, transport, timeout or
event-interleaving case, so those response/event and functional-acceptance
subaxes remain unresolved. The source digest and required native cases are
checked during generation; fixture weakening fails closed.

The 70 declarative model arities remain known but unresolved until each is
reconciled with the production parser. Across all paths, five argument-arity
subaxes, three value domains, five full session-state axes, five target-form
axes and nine state-effect subaxes are now resolved; the other 437 target-form
axes and 433 command-specific effect subaxes remain open. Response framing is
resolved for all 442, but full response/event axes only for the two comment
forms. Routing and physical-I/O boundaries, endpoint routes and native
obsolescence statuses are resolved for all 442. All 442 functional-acceptance
subaxes remain unresolved. These are contract-census facts, not acceptance
evidence.

## Current result

The current register, denominator version `provisional-2026-09-30.1`, has 28
workflows, of which 21 have members. It has 42 provisional umbrella
obligations, 442 provisional C-Gate path obligations and three defined
`SESSION_ID` functions, with zero fully accepted obligations and three
evidence records. One work item, P9.01, has a verified closure receipt. Two
evidence records accept only
the original-differential dimension of the three scoped functions: the
nine-case payload comparison and the eleven-case exact numeric-tag wire
comparison. The third marks their physical dimension not applicable to the
owned loopback profile.
The 487 records overlap and
are not a deduplicated functional denominator. All 22,156 source records and
15 source domains remain unresolved. Executable forms, controls and event
bindings are now counted. C-Gate paths have a deterministic per-axis contract
inventory and a one-to-one obligation mapping, while the unresolved subaxes
above, functional deduplication,
undocumented Toolkit branches and catalogue firmware profiles remain open.
The legacy ledger still reports 18 implemented, 22 in
progress and 2 pending rows, or 42.86% of category labels. That value is
explicitly marked as not being a functionality estimate.

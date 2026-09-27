# Functional parity register

`cbus-toolkit coverage` now derives its completion result from packaged
functional-obligation and evidence records. The 39-row feature ledger remains
visible as historical planning information, but changing its labels cannot
make the completion gate pass.

The initial register is intentionally provisional. It accounts for every
committed source surface currently available without treating unlike records
as equal functions:

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

## Files and regeneration

- `src/cbus_toolkit/parity-obligations.json` contains the source inventory,
  provisional scope mappings and obligation records.
- `src/cbus_toolkit/parity-evidence.json` contains evidence receipts. It starts
  empty because a historical path or test filename is not acceptance evidence.
- `src/cbus_toolkit/parity.py` validates both documents and derives progress.
- `research/build_parity_register.py` regenerates the provisional register
  deterministically from the committed documentation/executable surface
  censuses, feature ledger, Rust capability matrix and parity roadmap.
- `docs/toolkit-executable-surface.json` is the sanitized Toolkit 1.18.0
  executable inventory. It records names and hashes for 412 parsed Delphi form
  resources, 10,102 component/control instances and 1,892 event bindings.
- `research/extract_toolkit_executable_surface.py` reproduces that inventory
  from an explicitly supplied Toolkit executable and MAP. The inputs are
  identified by SHA-256 and remain outside Git.

Run:

```sh
PYTHONPATH=src python3 research/build_parity_register.py --check
cbus-toolkit coverage --require-complete
```

Maintainers with the retained vendor artifacts can also reproduce the
executable inventory:

```sh
python3 research/extract_toolkit_executable_surface.py \
  --executable /path/to/CBusToolkit.exe \
  --map /path/to/CBusToolkit.map \
  --check
```

The first command fails when a source inventory changes without regenerating
the register. The second exits nonzero until the versioned census is complete,
every obligation is defined and implemented, every applicable acceptance
dimension has matching passed evidence, and no required case is skipped.

Each obligation tracks implementation and applicability independently from
the required acceptance dimensions: nominal behavior, error behavior, invalid
input, profile variation, original Toolkit/C-Gate differential behavior,
physical behavior, and persistence/recovery. A dimension can be marked not
applicable only with matching passed evidence for that applicability decision.
`coverage` reports accepted, not-applicable, blocked and unassessed counts for
each dimension. Their percentages remain `null` until the denominator is
complete, alongside the implementation and overall acceptance percentages.

## Validation rules

The validator rejects duplicate JSON keys, non-finite numbers, duplicate or
missing IDs, orphaned scope items, resolved domains with unknown counts,
unknown states, unknown ledger/work-item/evidence references, unsafe artifact paths,
changed evidence bundles or record digests, changed source artifact hashes,
substituted feature ledgers, unexplained skips and required skipped cases.
Work-item references are checked against the packaged 59-ID authoritative roster,
so a syntactically valid but unplanned ID is rejected. The exact parsed evidence
object must equal the duplicate-key- and non-finite-safe parse of the digest-bound
evidence bytes.
Receipts also require explicit
test IDs, environment identity, artifact roles and an exit code consistent
with the result. Physical evidence must name a physical environment and stable
hardware references. Original-differential evidence must bind its Toolkit or
C-Gate oracle by SHA-256. An accepted or not-applicable dimension requires
evidence; an accepted dimension also requires a passed record naming that
exact obligation and dimension.

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

## Current result

The current register has 39 provisional umbrella obligations, zero accepted
obligations and zero evidence receipts. All 22,156 source records and 15
source domains remain unresolved. Executable forms, controls and event
bindings are now counted, while their functional deduplication, undocumented
Toolkit branches, selector/state/effect expansion and catalogue firmware
profiles remain open. The legacy ledger still reports 18 implemented, 19 in
progress and 2 pending rows, or 46.15% of category labels. That value is
explicitly marked as not being a functionality estimate.

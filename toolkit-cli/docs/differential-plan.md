# Differential acceptance plan (Phase 4 scaffolding)

Phase 4 only: ledger/census inventory plus an empty differential harness.
No Toolkit parity is claimed. The harness starts red so later phases must
supply independent original-Toolkit evidence before any slot can flip.

## Authoritative inputs

- Feature ledger: `../src/cbus_toolkit/capabilities.json` — **38 areas**,
  `census_complete: false`. Statuses (`implemented` / `in_progress` /
  `pending`) describe implementation categories, not Toolkit parity. Two
  acceptance IDs remain `pending`: `toolkit-differential-acceptance` and
  `unit-hardware-acceptance`.
- Status narrative: [implementation-status.md](implementation-status.md) —
  `cbus-toolkit coverage --require-complete` intentionally returns nonzero
  while this work remains; no completion percentage is reported.
- Documentation census: [toolkit-surface.md](toolkit-surface.md) — **3767
  indexed help topics** in 21 branches, **209 public C-Gate command blocks**,
  56 mapped typed-wrapper candidates, **118 configuration-dialog
  candidates**. Topic and command acceptance is `unassessed`; raw forwarding
  and wrapper presence do not establish workflow acceptance.

## Matrix shape

Implemented in `../src/cbus_toolkit/differential.py`:

- One row per ledger area (38 rows), preserving the ledger `status`,
  `limits`, and `evidence` fields verbatim.
- Per row, three workflow slots (`nominal_workflow`, `error_path`,
  `device_firmware_variation`) and three negative-path slots
  (`invalid_input`, `unsupported_profile`, `hardware_divergence`), all
  starting at `unassessed`.
- Per-row `differential_status: pending` and `evidence_paths: []`.
- Matrix summary: `ledger_areas: 38`, `accepted_areas: 0`,
  `complete: false`, `census_complete: false`.

## Honesty gates

- `tests/test_differential_matrix.py` enumerates all 38 areas x
  workflow/negative slots and asserts the matrix is empty/red.
- `tests/test_coverage_require_complete.py` asserts `coverage
  --require-complete` still exits 1 with `complete: false`.
- The pre-existing `test_cli.py::test_coverage_cannot_claim_completion`
  guard is preserved; no status inflation was made in `cli.py`.
- `capabilities.json` keeps `census_complete: false`; do not flip it until
  the executable-level census and its acceptance mapping are complete.

## Fresh-wheel relationship (scaffolding only)

The full fresh-wheel acceptance run (installed wheel, all native gates)
is not executed in this phase. This harness only records where future
per-area original-Toolkit comparisons and negative-path evidence will
attach. Later phases add vectors, system tests, and evidence paths without
inventing endpoints, credentials, or vendor specifications; reserved
ledger fields stay intact and provisioning-gated skips are reported.

## What Phase 4 does not build

Phases 1–3 and 5–14 are not built here: no protocol/transport/MQTT/C-Gate
behavior changes, no MMI/unravel work, no UI or snapshot semantics, no
factory-prep or specialist-app mocks, and no compatibility-gate changes.

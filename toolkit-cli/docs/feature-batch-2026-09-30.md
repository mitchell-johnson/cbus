# DALI, SENLL and Toolkit workflow batch — 2026-09-30

This batch advances both the Python Toolkit CLI and cmqttd's embedded C-Gate
service. Full Toolkit and full C-Gate behavioral compatibility remain unfinished.
The completeness gate still fails deliberately; its census is incomplete, so
the 487 tracked obligations cannot establish a percentage of complete parity.

## Delivered behavior

| Workflow | Implemented scope | Remaining boundary |
| --- | --- | --- |
| DALI extended settings | Native extended-proxy compilation across 21 global and 15 line families; Python physical admission for the exact 133 advertised global leaves; nullable scene creation; durable EXT_ONLY chunk journals; concurrent raw/typed edit ownership and bounded regular-file inputs | Typed physical line intent, whole-proxy replacement, broader original GUI workflows and gateway/downstream/power-cycle acceptance |
| SENLL | Broadcast timer, Power Fail selection and Global status interval alongside the existing dialog controls; original forced-save order and five admitted native database profiles | Loaded Global values 0..2 require an explicit valid selection; collision-driven shared-key reassignment, older identities, optical/timing/power-failure behavior and full original GUI execution |
| Classic DLT | Database dynamic-update blocking, saved XML TEXT variant edits, indicator mode, inversion and clock visibility | Original complete form, language-definition changes, physical label-transfer lifecycle, display rendering and persistence of unnamed raw bits |
| Thermostat | One recovered form save, including dependent fan/slave-plant/relay-drive changes and bounded dialog/template helpers | Preference-dependent conversions, complete GUI lifecycle, remaining controls and physical behavior |
| Document Project | Explicit saved native XML adapter; recovered output/bridge/DMX bodies, bounded usage/action projections and status intervals | Remaining bodies, native registry/locale ordering, full original page bytes/visuals, printing and progress/cancel lifecycle |
| eDLT metadata | Native Language identity uses ID; explicit ambiguous language collections are refused before label-dependency planning | Original degenerate-language normalization and session history; complete image-dependent and original parent workflows |

The detailed contracts remain authoritative: [DALI](dali-commissioning.md),
[sensors](sensors.md), [classic DLT labels](classic-dlt-label-controls.md),
[classic DLT display](classic-dlt-display.md), [thermostat settings](thermostat-settings.md),
[Document Project](project-documentation.md) and the
[implementation ledger](implementation-status.md).

## Verification

Checks used synthetic projects, scripted gateway/PCI peers, owned loopback
original C-Gate services and isolated installed wheels. No house network, live
broker, Windows VM or running Docker installation was used for this batch.
The following scopes overlap; their totals must not be added together.

| Check | Result and evidence |
| --- | --- |
| Final merged DALI/sensor/display/fixture installed wheel | 150 tests and 861 subtests passed; zero failures, skips or deselections. [Source/wheel receipt](dali-senll-merged-acceptance-summary.json) |
| Installed packaged parity context | Three tests and 24 subtests passed; source-import prohibition and incomplete/full-parity boundaries retained in the same receipt |
| SENLL/PIR source plus original database | 28 tests and 490 subtests passed with no skips; five SENLL profiles, save/close/load and unrelated-field preservation. [SENLL receipt](light-level-sensor-acceptance-summary.json) |
| Integrated Document/DLT/thermostat source scope | 299 tests and 90 subtests passed with no skips; profile-specific original receipts remain linked from their contracts |
| Classic DLT display source scope | 46 tests and 63 subtests passed with no skips, including original instruction execution and five original C-Gate database profiles |
| Final eDLT metadata source and consumers | 132 tests and 137 subtests passed; one case-sensitive-filename test skipped on case-insensitive temporary storage and four explicit original real-unit/project opt-ins deselected |
| Final metadata-only installed wheel | 72 tests and 36 subtests passed with no skips or failures; four original real-unit/project opt-ins deselected. Every other packaged Python/JSON file matches the preceding green wheel |
| Rust | 43 DALI tests and one GOC2 acknowledgement regression passed; workspace formatting and strict Clippy checks passed, and the release workspace built |
| Original command differentials | For each of cmqttd and cgate-mock: nine session cases, eleven tagged-session cases, twelve Unit XML cases and two combined Network cases passed; three physical-applicability cases also passed |

The initial merged source run recorded 86 passes, two harness failures and
798 passing subtests. The two cases subsequently passed in a separate narrow
run. One test read structured error evidence from stdout instead of stderr;
the other timed out during a healthy 287-chunk deployment. Only that case's
client budget was increased. Earlier receipts also retain the three corrected
CLI admission failures and two missing staged Document Project fixture files.
Those earlier runs remain historical failures, not retroactively green runs.

The final metadata refusal correction has separate source and installed-wheel
acceptance in the merged receipt. Carry-forward evidence for other workflows
requires identical packaged Python bytes and an unchanged daemon binary; it
does not turn a previous wheel into a test of a later file.

The metadata scopes' opt-in deselections are not acceptance of those original
real-unit/project cases. The platform skip likewise remains unverified in this
environment.

The full Cargo/Python suites were not run, following the requested focused-test
policy. Offline or scripted acceptance does not replace original GUI or
physical acceptance. CI results must be evaluated for the published commit.

## Reproducing checks

From `rust/`, run `cargo fmt --check`,
`cargo clippy --workspace --all-targets -- -D warnings` and
`cargo build --release --workspace`. The focused Rust filters and exact
Python selections are retained with the acceptance receipts.

From `toolkit-cli/`, use the native setup in [testing](../../docs/testing.md), set
`CBUS_CMQTTD_BIN` to the freshly built daemon and run the modules listed in
the feature contracts. Installed-wheel checks must run outside the source
checkout and verify import paths. Native services and private vendor inputs
must remain explicitly configured; no vendor executable, specification or
site project belongs in Git.

The parity receipts were regenerated by executing the actual differentials
against freshly built cmqttd and cgate-mock. The regenerated native inventory
contains 491 modules and 234 required native modules. The functional register
contains 22,156 source records, 487 obligations and three qualified evidence
records; `census_complete` remains false. Refresh and check those inventories
after their inputs change rather than replacing receipt fingerprints.

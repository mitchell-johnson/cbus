# Combined Toolkit CLI feature integration — 3 October 2026

This successor combines eight reviewed Python feature branches with the published
Time/Date, DIN save and applied-repository recovery behavior. It preserves the
Python Toolkit CLI and Rust MQTT/C-Gate products. The Rust sources are unchanged
in this batch; accepting Python adapters does not establish full Toolkit parity.

| Feature | Resulting admitted behavior | Reviewed feature head |
| --- | --- | --- |
| SENLL controls and application events | Explicit eight-block collision/callback histories and opt-in live event filtering/counting | PR82, fe0348ba |
| SENLL inventories and Scene controls | Fresh zero-key inventories, causal refresh, Scene allocation and enabled-block save projection | PR86, dfac5862 |
| SENLL Global interval | Ordinary setup normalizes loaded interval 0..2 to 3; explicit selections remain bounded | PR88, 71ddb37b |
| SENLLA surface | Read-only 13-field component view for SENLLA / 5754PE / firmware 2.4.00..2.4.99 | PR91, 5a9c48d0 (provider successor) |
| DIN controls | Ordered slider, Synchronise and Stagger callbacks beside the retained scalar and one-pass Toolkit-save APIs | PR83, 7600b7eb |
| NCC diagnostics | Offline supplied-transcript admission, next-step diagnostics and redacted model results; no physical executor | PR84, c8542c4a |
| Neo per-unit input panel | Source-pinned ordinary-profile indicator controls and load/save projection, distinct from bulk Unit Magic | PR85, bf18c491 |
| Thermostat references and settings | Enabled setback/schedule resolution, causal application/group creation and combined settings save | PR87, 8338a9f2 |

These profiles retain exact identities, current metadata and complete preservation
checks. Instructions and exclusions are in the existing feature guides; earlier
feature receipts remain historical records of their exact source heads.
They are not relabeled as acceptance of this integrated source tree.

The separate PR92 Level-prompt/Level-OID TagName work is excluded from this
batch. Review found that its initial admission rule unnecessarily rejected
missing or opaque existing Level Value attributes. A narrow compatibility
proposal and red/green pure regressions are retained privately; the corrected
successor still needs implementation and backend/required Rust integration
validation. [Issue96](https://github.com/mitchell-johnson/cbus/issues/96) tracks
that regression; issue90 covers the separate Level-OID TagName behavior. The
unfinished SENLLA write/lifecycle profile is also excluded.

The SENLLA provider successor corrects omitted BitSize metadata using the
native memory codec's effective one-bit layout and ignored bit ArraySkip.
Integer layouts and flag values 0/1 remain strict. Two new pure model tests and one offline public CLI test
cover omitted metadata, all eight flag combinations, neighboring
memory bits and read-only input preservation. The provider receipt remains
its own historical source/wheel scope; complete unit save is still excluded.

## Integration and evidence ownership

The isolated integration starts at published main 86dd5c87. Sensor branches are
integrated in dependency order 82 → 86 → 88 → 91, followed by the disjoint
DIN, updated NCC, Neo and thermostat branches. CLI dispatch is composed in the
current source context, and the shared backend helper extension is applied once.
Every inherited Time/Date, repository-error and DIN save guard remains active.

The complete published implementation-status body is retained and bounded peer
notes are added. Make and CI requirements use the union of existing selectors
and the 146 new owned-backend cases; the 27 SENLLA read-only model/CLI cases are
separate. Metadata is regenerated with maintained producers after all input
changes settle. Current owned captures cannot grant new original/native credit.

## Focused validation

The selected scope is 65 whole affected modules, including the shared transport,
parent, programming, DIN scalar/save, event, metadata and CI requirement modules.
Sixty-four require passing bodies. The one wholly provision-gated thermostat
native module remains collected with explicit skips and no acceptance credit.
Both source and fresh installed wheel execute the same selection.

The new public backend roster contains 146 exact cases, 73 for each backend.
Its lost-successful-save cases remain explicit and must prove no replay or inverse
mutation. The existing 28 Time/Date and 20 DIN-save journeys are preserved within
the same scope. Counts for these subsets are never added to parent totals.

The fresh wheel must match every source Python/JSON file in its ZIP and installed
package before and after testing. A runtime import guard records the actual
pytest process at startup and termination, and inherited guards observe Python
CLI children. Intentional test-local import traps are kept distinct from package
origin checks. An installed-console probe uses no source PYTHONPATH.

Fresh owned session, tagged-session and DBSETXML comparisons run against the
immutable release cgate-mock/cmqttd pair. Sanitized publications preserve all
non-coordinate technical payloads and retain raw archives privately. Contract
inventory, physical applicability, parity register and recursive skip census
must validate their current declared inputs. The global coverage gate remains
nonzero until all functional acceptance requirements are met.

<!-- integrated-validation-outcome:start -->
Source and fresh installed wheel each passed **1,002 parent tests and 3,305
separate subtests**, with **37 disclosed skips** and no failures. All 65 modules
were collected and all 64 body-required modules passed. Both executions passed
the 146 new backend IDs, preserved Time/Date28 and DIN-save20, and all 27 SENLLA
model/offline-CLI cases; these subsets are inside the parent totals.

All 4,076 frozen inputs and the immutable binary pair stayed unchanged. All 387
source Python/JSON, wheel ZIP and installed-package files matched before and
after testing. The actual pytest PID had an exact installed-package startup and
terminal record; 6,348 observed records across 3,250 processes had no import
violations. Child terminal records are not inferred where absent. The separate
installed console help probe passed without source PYTHONPATH.

Independent raw recount covers 194 records per phase (146 new plus 48 preserved),
988 CLI calls, 984 connections and 11,382 tagged commands. It verifies 194 cleaned
PIDs, 776 simulator PCI startup frames and 24 dropped upstream successful replies
with no later request on those invocations. Other selected public bodies are not
part of that raw aggregate. Some raw records have no pytest nodeid; identity
subsets and record aggregates remain separate proofs.

The six owned comparisons retain their 4,075-input capture epoch. Current checks
verify all 1,171 declared bindings across 218 distinct paths. Both downstream
4,076-input metadata epochs pass all three commands with zero output changes;
the earlier three intentional generation changes remain historical. All 471
Rust inputs and both binaries exactly match the prior accepted four-gate epoch,
so Rust tests/builds were not repeated.

The installed `coverage --require-complete` exits 1: census and denominator are
incomplete, with no functional percentage available. Its default call grants no
trusted artifact/fingerprint credit. The explicit checkout-root call reports a
missing retained original-native experiment artifact; it is not a trusted-root
validation pass. Original/native and hardware acceptance remain open.

The [integrated release receipt](../research/fixtures/combined-cli-owned-release-20261003.json)
binds the actual terminal artifacts, exact skipped identities/reasons, package
proofs and independent reviews. Publication CI has a separate outcome.
<!-- integrated-validation-outcome:end -->

## Limits and remaining work

No complete Python or Rust workspace suite is repeated for this Python-only
integration. The prior required Rust four-gate epoch is reusable only when all
471 Rust inputs and the immutable binary pair are byte-identical. Any subsequent
Rust edit requires the applicable gates on its actual integrated source.

Original Toolkit/C-Gate execution, WinForms dispatch, rendering, broader
firmware/device domains, physical programming and power-cycle acceptance remain
open. No house network, physical lights, Windows VM or deployed Docker service
is operated by this batch. Publication CI has its own outcome and is not inferred
from these local focused runs.

The category ledger remains 18/42 (42.9%). Its categories are not a functional
denominator. The functionality census remains provisional and the global
percentage cannot honestly be reported as complete. See
[implementation status](implementation-status.md) and the maintained GitHub
issues for the remaining original/native, device and release work.

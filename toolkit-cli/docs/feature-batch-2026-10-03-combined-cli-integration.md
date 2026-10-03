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
| SENLLA surface | Read-only 13-field component view for SENLLA / 5754PE / firmware 2.4.00..2.4.99 | PR91, 3b07731b |
| DIN controls | Ordered slider, Synchronise and Stagger callbacks beside the retained scalar and one-pass Toolkit-save APIs | PR83, 7600b7eb |
| NCC diagnostics | Offline supplied-transcript admission, next-step diagnostics and redacted model results; no physical executor | PR84, c8542c4a |
| Neo per-unit input panel | Source-pinned ordinary-profile indicator controls and load/save projection, distinct from bulk Unit Magic | PR85, bf18c491 |
| Thermostat references and settings | Enabled setback/schedule resolution, causal application/group creation and combined settings save | PR87, 8338a9f2 |

These profiles retain exact identities, current metadata and complete preservation
checks. Instructions and exclusions are in the existing feature guides; earlier
feature receipts remain historical records of their exact source heads.
They are not relabeled as acceptance of this integrated source tree.

The separate PR92 Level-prompt/Rust OID work is excluded from this batch. Review
found that its initial admission rule unnecessarily rejected opaque existing
Level Value attributes. A narrow compatibility proposal and red/green pure
regressions are retained privately; that successor still requires backend and
required Rust integration validation. The unfinished SENLLA write/lifecycle
profile is also excluded.

## Integration and evidence ownership

The isolated integration starts at published main 86dd5c87. Sensor branches are
integrated in dependency order 82 → 86 → 88 → 91, followed by the disjoint
DIN, updated NCC, Neo and thermostat branches. CLI dispatch is composed in the
current source context, and the shared backend helper extension is applied once.
Every inherited Time/Date, repository-error and DIN save guard remains active.

The complete published implementation-status body is retained and bounded peer
notes are added. Make and CI requirements use the union of existing selectors
and the 146 new owned-backend cases; the 24 SENLLA read-only model/CLI cases are
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
Combined validation is pending. Planned modules, rosters and earlier feature
counts are not evidence that this assembled candidate has passed.
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

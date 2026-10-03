# IOPE delay inspection and owned interop harness corrections

This batch is based on `1cc79977ddcc7b4912e9329706d9cd94e8f99b5f` and tracks
bounded work in issues #40 and #77. It does not close either issue or establish
full Toolkit parity.

## Delivered behavior

`cbus-toolkit iope-workflow output restrike-delay-time ORDINAL` decodes the
stored byte into numeric minutes and seconds. `restrike-delay-choices` lists
the complete admitted selector inventory, ordinals 1 through 254. Stored bytes
0 and 255 remain inspectable but unlisted. The arithmetic comes from the
committed IOPE source review; localized GUI strings remain unverified.

The extension changes only the public parser and its two new dispatch paths.
The original standalone workflow, output editor and native acceptance
receipts remain unchanged. Tests check literal boundary values, strict input
admission, the full inventory, absence of file/network access and legacy
dispatch preservation.

Owned interop tests retain their strict PID and exact loopback listener
inventory checks while suppressing irrelevant `lsof` mount warnings. Heavy
owning-parent Add/Reset/Scene workflows have an explicit 90-second outer
process budget, including Selector, Static/Language Add and Lighting/widget
paths. Ordinary calls retain 20 seconds, standalone Lighting exports retain
30 seconds, and the wire timeout remains three seconds. A subprocess timeout retains the attempted call, partial
stdout/stderr and wire rows before propagating the original exception. It
does not retry the uncertain operation. Connected-but-empty wire rows and
zero-connection refusals retain their complete empty call inventories.

The initial Rust read/storage changes were dropped after capacity review:
main's PR #80 already supplies stronger streaming storage, snapshot-free
reads and a sixteen-backup workload. No Rust changes belong to this batch.

## Focused validation

All counts below are separate executions and must not be added together:

| Selection | Result |
| --- | --- |
| Source display/output/workflow/barcode modules, before bulk-relay revision | 29 passed, nine backend-dependent skips, 86 passing subtests |
| Final source feature/helper/relay selection | 35 passed, nine backend-dependent skips, 86 passing subtests |
| Source IOPE alias, native receipt guards and timeout/empty-wire regressions | 15 passed, five provisioning skips, 22 passing subtests |
| Source legacy dispatch receipt guards | Four passed, seven provisioning skips, 22 passing subtests |
| Fresh installed-wheel display/output/workflow/alias/helper cases | 36 passed, 108 passing subtests, no skips |
| Previously failing current-main Selector cases on mock and daemon | Six passed, no skips, 154.23 seconds |

All 388 package files match between source, wheel ZIP and installed package.
The wheel imported from its isolated Python 3.13 `site-packages`; its SHA-256
is `84c97eb0da7f9284daf9c420bb9d8d71ca7db9c613da507bdcbf3780e139073b`.
Independent review found no defects in the feature and timeout corrections.
The later bulk-relay correction was separately reviewed and tested.

## Required validation and remaining acceptance

The required source run completed with exit 2: 10,025 passed, 1,410
provisioning skips and 44,486 passing subtests, with one failure in the
committed skip-census check. Adding the new fault-relay regression module
during that run made the census stale (751 versus 752 modules). The census
was regenerated; all three census tests and five subtests then passed. This
failed source epoch and its focused repair remain separate from the final
full-source retry. That retry completed with exit 0: **10,032 passed, 1,410
provisioning skips and 44,486 passing subtests** in 1h11m40s. All fifteen
scoped feature, helper, documentation and census inputs stayed fixed.

A subsequent interop epoch was interrupted with exit 2 after one failure,
337 passes, one vendor-specification skip and 158 passing subtests in
1h03m41s. The Global lost-first-save test timed out during an earlier bulk
`PP GET *`, before reaching its intended save fault. Its relay forwarded
each continuation as a separate small write. The owned relay now batches
ordinary replies per received chunk, splits the chunk once and enables
TCP_NODELAY. Preceding continuation bytes are flushed before a dropped
terminal or change callback. Failed Global journeys retain fault wire
evidence in `finally`. No wire timeout, fault assertion or retry policy
changed.

Six synthetic cases check literal 844-row replies, dropped terminals,
callback ordering, refusal without forwarding (including document bodies),
and a deterministic single send for a bulk chunk. These plus four existing
helper regression cases passed in both source and the installed wheel.
The previously failing Global case passed against mock and daemon (two
passes in 53.03 seconds). Small old/new timing samples do not prove the
sole cause of the loaded timeout.

The final full interop retry passed the mock selection: **390 passed, one
vendor-specification skip and 158 passing subtests**, in 1h13m18s. The
daemon selection then reached a separate provisioning failure: portable
`XML_TO_SQL` returned 408 because the `sqlite3` executable was absent. The
monolithic Make run was interrupted with exit 2 after one daemon failure,
226 passes, one skip and 69 passing subtests in 17m58s.

SQLite 3.46.1 was provisioned from Debian's official package into the
workspace, and the formerly failing node passed (one test, 59.51 seconds).
The complete daemon retry passed with exit 0: **531 passed, one
vendor-specification skip and 69 passing subtests**, in 1h37m16s, with that
executable on PATH and `TMPDIR=/tmp`. Source and selected Rust binaries did not change for this
repair. The completed source and mock scopes are retained; no monolithic
Make exit-0 claim is made across these separate epochs. The prior epochs passed six modeled protocol comparisons:
64 primary checks and four combined-network checks, plus two XML framing
tests. These modeled comparisons provide no original-execution credit.

Earlier work on the superseded `5b446ed3` base had failed broad checks. The
source run reported 22 failures: four changed native-bound IOPE sources,
17 sanitizer tests affected by sandbox-generated Git markers in temporary
directories, and one stale skip census. Isolation restores the IOPE sources;
the sanitizer remains strict and runs with temporary archives outside a Git
checkout; the census is regenerated. That base's interop run reported ten
heavy-parent outer-timeout failures. Its targeted successor passed 20 cases
on both servers after the harness corrections. Those predecessor outcomes
remain separate from this current-main candidate and receive no current
acceptance credit.

The first current-main interop epoch was interrupted after three additional
20-second Selector process timeouts: 270 passed, one vendor-specification skip
and 158 passing subtests in 35m28s. Its concurrent source epoch was interrupted
without failures after 3,697 passes, 1,053 skips and 5,715 passing subtests in
40m25s so the remaining wrappers could be corrected together. A later early
source run was also interrupted while finalizing the census. None is a
completed current gate. The final wrapper audit and empty-wire compatibility
regressions passed; all three observed Selector failures and their daemon
counterparts passed before the complete suites restarted.

The retained checks and input/log fingerprints are in
[`iope-delay-inspection-owned-checks-20261003.json`](../research/fixtures/iope-delay-inspection-owned-checks-20261003.json).
Both this batch and the independent large XML export batch have 752-module
censuses; combining both feature modules requires regenerating for 753.

Native/vendor/hardware skips are not acceptance.
The completion gate still exits 1 with `complete=false` and
`census_complete=false`; the full original workflow and physical gates remain
open. No original instructions, GUI, private site service or physical endpoint
executed for this batch.

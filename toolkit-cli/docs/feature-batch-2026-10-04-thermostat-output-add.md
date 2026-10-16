# Typed thermostat output Add — 4 October 2026

The [settings owner](thermostat-output-add.md) now accepts ordered output Add
outcomes interleaved with existing selections for PC_TSA, PC_TSA5, PC_TSB and
PC_TSB5. Accepted Add creates and selects a Group; cancellation retains the
previous reference without OK validation. Earlier creations remain in the
shared graph even if a later selection replaces them.

The source-pinned rules cover all 23 plant, damper and relay controls, first
numerically free address 0–254, evolving name/address inventories, 32 UTF-16
units before source trimming, ASCII-only uppercase duplicate comparison and
accepted-only exact Project.TagName validation. Every intermediate assigned
address is checked against the decoded parameter.

An owned-backend failure with éPump followed by two spaces and Ω exposed name
loss in SAFE creation. The accepted Add adapter now follows the recovered
Group save path: DBADD under the freshly verified application OID, fresh
new-object OID verification, then Address and source-encoded quoted TagName
writes. The Rust dispatcher decodes a quoted DBSET tail once before database
routing. Unquoted DBSET, DBSETSAFE and DBADDSAFE retain their prior contracts.

Full-plan preflight, freshness and preservation checks remain in the existing
owner. A changed transaction has at most one PP save and one final target
project save; its backup source save is separate. Uncertain Add, field or save
replies stop without retry, deletion or later writes.

## Frozen validation

The [release receipt](../research/fixtures/thermostat-output-add-owned-release-20261004.json)
binds the uncommitted execution tree by exact hashes on base
3faee4e9fd71da0d7fbac1104442d7605600cb7c. It retains private log/trace
identities without publishing private input locations.

| Check | Result |
| --- | --- |
| Focused source, 18 selected modules | 227 parent passes, 1,404 separate subtests, 11 skips |
| Fresh noneditable installed wheel, same selection | 227 parent passes, 1,404 separate subtests, 11 skips |
| Owned backend cases, in each run | 16 Add + 16 ordinary outputs + 16 optional levels + 24 remote references, all passed |
| Package inventory and bytes | All 380 source, wheel and installed files equal |
| Execution inputs | All 4,026 tracked/unignored repository files and both debug binaries unchanged |
| Static Add source reproduction | 211 checks, 120 method spans, five DFM resources, 67-method handler scan |
| Focused Rust database workflows | 56 passed, including the new quoted-value regression |
| Rust required non-suite checks | Formatting, workspace/all-target Clippy with denied warnings, release workspace build passed |
| Complete feature coverage | Exit 1; full parity remains unfinished |

Counts within and between rows overlap and must not be added. The 11 skips
comprise four optional original-file static checks and seven vendor-native
integration cases. The new Add static receipt was independently reproduced
outside that selected pytest run and exactly matched its committed fixture.
Static inspection executes no original instructions.

The actual installed console ran with child PYTHONPATH removed. It retained
an added heating group after reselection, created two relay groups, preserved
double ASCII spaces, NBSP-only and quote/backslash/hash names, performed one
PP save and one final target save, and passed independent close/reload
preservation. Its wire assertions use literal expected quoted values.

The new Rust regression fails on the old parser and passes after the fix.
It checks pending and existing Group/NetVar objects, OID and path writes,
exact OID scalar and full Network XML readback, supported named-path reads,
save/load/restart and absence of PCI I/O. Numeric-path scalar diagnostic
fallback remains outside the exact-342 readback profile. Both debug binaries
were freshly built; 470 Rust inputs remained unchanged through the required
checks. Validation used Rust/Cargo 1.92.0.

Six modeled C-Gate differential receipts, the contract inventory, parity
register and skip census were refreshed before the final freeze. An
independent outcome audit re-parsed both JUnit/trace pairs, matched the exact
72-case backend roster, rehashed current inputs/packages/binaries and checked
the installed-console and Rust receipts. It found no blocker.

## Development evidence and boundaries

Development failures are retained separately from final acceptance. The
initial cancellation oracle incorrectly expected a consumed project label;
the following run exposed real doubled-space loss without normalizing the
expected name. After the storage fix, fault-test corrections handled complete
C-Gate error responses and distinguished the numeric owned export profile
from the named/native incomplete-object profile.

For a lost successful DBADD reply, the owned numeric project export is 344
and unchanged because it omits the pending object. It is not an inventory of
pending objects. Separate fresh OID and direct object reads prove that the
issued incomplete Group exists without Address/TagName. PP and existing
graph state remain unchanged; no subsequent owner mutation or save occurs.
The final frozen source and wheel each pass all 16 new backend cases.

The Rust zero-test filter attempt was rejected as acceptance and rerun with
the exact test name. Earlier readback-oracle and build-selection mistakes
remain recorded. A private console-harness mapping omission was caught and
fixed before its first execution. No failed attempt was relabeled as a pass.

No full Python/Rust test suite, fresh original instruction execution,
Schneider native server, Windows GUI or physical thermostat ran. Native and
hardware acceptance remain deferred under issue #72. Issue #95 tracks the
quoted-DBSET fix; issue #42 retains thermostat parity work. Application
changes, output Edit controls and complete initialized form/message behavior
remain open. Release/status annotations were written only after frozen
execution and the independent audit; runtime, tests, CI selection and
packaged metadata remain unchanged.

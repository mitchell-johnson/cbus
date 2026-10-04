# Thermostat damper controls — owned release, 2026-10-04

Seven explicit damper events now compose with output Select/Add/Edit inside one
fresh settings owner: FormShow, after-show, group-change, checkbox binding,
warning Click, InstalledZones assignment and UpdateDamperGroups. See the
[operator guide](thermostat-damper-controls.md) and
[release receipt](../research/fixtures/thermostat-damper-controls-owned-release-20261004.json).
Issue [42](https://github.com/mitchell-johnson/cbus/issues/42) remains open.

Fresh model caches begin nil. Removing and reinstalling zones preserves live
cached object identities and names. Nil and unused callbacks take distinct
source branches; warning Click observes checked state without assigning the
model Boolean. Final form save owns modulation's plant factor and ControlledZones.
Source review caught the reserved-address boundary: first-free creation scans
0–254 and refuses if only reserved address 255 is free. No-op histories write nothing;
graph-only histories skip PP save while persisting their graph through project save.

The proof has two execution stages per lane:

| Epoch | Parent PASS | Parent FAIL | SKIP | Separate subtest PASS | Selected modules | Backend PASS / started | Pytest / auditor exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Retained source-final1 | 349 | 4 | 7 | 1060 | 22 | 182 / 186 | 1 / 1 |
| Retained wheel-final1 | 349 | 4 | 7 | 1060 | 22 | 182 / 186 | 1 / 1 |
| Corrected source-final2 | 78 | 0 | 0 | 0 | 1 | 78 / 78 | 0 / 0 |
| Fresh installed wheel-final2 | 78 | 0 | 0 | 0 | 1 | 78 / 78 | 0 / 0 |

The first runs remain failed predecessors. Four lost-save assertions expected a
period after `200 OK`, but the actual successful tagged reply has none. Only the
backend test changed: it now checks the exact observed no-period reply and captures
fault evidence before assertions. All 17 loss assertions remain, including no
retry, no rollback, backup/save counts, backend-success membership, client-side
reply loss and whole PP/graph preservation. The corrected 78-case module then
passed in both source and a freshly built installed wheel. The 22-module cohort
was not rerun after the test correction, so this report claims no unified green
22-module or 186-body epoch. Counts overlap and are not summed.

The seven source-data skips from each earlier run remain disclosed:

- `tests/test_thermostat_damper_controls.py::DamperControlTests::test_fresh_source_data_matches_annex`
- `tests/test_thermostat_output_add.py::OutputAddTests::test_optional_static_source`
- `tests/test_thermostat_output_default_ascii_static.py::ASCIIDefaultSourceTests::test_fresh_pinned_source_data_matches_published_facts`
- `tests/test_thermostat_output_edit.py::OutputEditTests::test_optional_static_source`
- `tests/test_thermostat_output_groups.py::OutputGroupTests::test_optional_static_source`
- `tests/test_thermostat_remote_levels.py::RemoteLevelTests::test_optional_static_source`
- `tests/test_thermostat_remote_references.py::RemoteReferenceTests::test_optional_static_source`

The current 78 backend cases (39 per server) cover 70 positive histories, two context
refusals, two stale-value refusals and four actual lost successful save replies.
Each lane records 148 CLI calls/connections, 8,820 tagged commands, 78 cleaned service
processes and 312 startup frames. The scoped raw reader checks whole 109-parameter PP snapshots, structural
project graphs, OID/opaque Level preservation, cache histories and successful
fresh readback. Source-independent literals, raw review and installed package/origin
checks are separate scopes; no original workflow acceptance is inferred.

Between the earlier and corrected freezes, one of 4,133 paths changed: the backend
test. All 390 product package files remained byte-identical. Both current epochs
and isolated installed coverage preserve their full source/reference closures,
source/ZIP/installed package equality, 473 retained Rust inputs and verified binary
pair. Origins are actual pytest/CLI startup and terminal loaded-module snapshots,
not continuous import tracing. The earlier wheel and proof snapshots are retained.

Static EXE/MAP data inspection checks 92 method spans, 33 structural assertions and
five bindings without executing original instructions. The normal Make roster
preserves 829 prior selectors and adds 78, for 907. It registers 186 thermostat backend
identities (108 inherited + 78 damper); registration does not mean 186 were rerun in
the correction epoch. Five metadata commands, including three check-only commands,
exit 0 with no generated output changes. No full suite or Rust rebuild was run.

Actual installed `coverage --require-complete`, in an isolated cwd without
PYTHONPATH or a trusted evidence root, exits 1 and remains incomplete. The ledger
stays 18 implemented / 22 in progress / 2 pending (18/42 category rows), with 487 total
obligations (484 provisional, 3 defined) and zero fully accepted. Census and denominator readiness remain false;
this default observation does not verify evidence fingerprints or artifacts.
No copied-root diagnostic is claimed in this phase.

Complete quick-zone Include/Exclude, automatic notification multiplicity, queued
host-message delivery, application migration, output Delete exposure, rendering,
full original form lifecycle, native-server and physical thermostat acceptance
remain outstanding. No current CI-green or main-merge claim is made. The public
receipt contains sanitized counts, normalized IDs and hash/byte descriptors;
private paths, raw skip messages and vendor instruction bodies stay private.

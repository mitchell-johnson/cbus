# Thermostat optional remote levels — 3 October 2026

The existing `thermostat settings preview|apply` owner accepts separate
`--setback-levels accept|decline` and `--schedule-levels accept|decline` choices.
Both default to decline. The basic family refuses schedule acceptance. Choices
apply only to enabled features whose non-unused resolved groups lack Level
addresses 1–31. Group 0 is admitted; group 255 is skipped.

Accepted prompts create missing addresses in setback On/Off, then schedule
On/Off/Override order. Each new Level has Value equal to Address and the exact
recovered zone label. Existing Levels retain their independent Value, name,
OID, position and opaque data, including addresses outside 1–31. The planner
reports prompt requirements, response use and all proposed records. See the
[operator workflow](thermostat-settings.md) and
[static source annex](thermostat-remote-levels-source.md).

The native owner resolves all application/group creation first, checks each
parent identity, admits the returned Level OID, explicitly initializes Value,
and writes the final label. OID field addressing preserves the retained native
NetVar compatibility contract. The complete graph guard checks the resulting
records and all existing metadata before the single owning PP/project save,
then checks again after reload. Graph-only additions require zero PP saves.
Lost create or field responses stop without replay, deletion or continuation
to a target save; the command retains partial-write evidence.

The shared Rust backend correction makes OID-addressed Level TagName updates
change the exported Level instead of only returning success. Issue #90 records
the discovery and validation. The initial OID-parent creation attempt and the
later misleading OID label success were both caught by focused tests. Numeric
Level field addressing was rejected after review of the retained native
NetVar restriction. All preliminary failures and the mixed development epoch
remain separate from final frozen validation.

## Focused validation

The [release receipt](../research/fixtures/thermostat-remote-levels-owned-release-20261003.json)
binds the exact frozen source, fresh wheel, binaries and retained raw evidence.
Source and a fresh noneditable installed wheel each pass **159 parent tests and
1,250 separate subtests**, with **nine skips**. Each run executes all 16 new
Level cases and all 24 existing remote-reference backend cases. These scopes
overlap and their counts are not additive.

The new cases cover all four aliases, both choices for each applicable prompt,
new/existing groups, partial levels with independent Values, complete no-ops,
group 0 and unused group 255, graph-only saves, and lost successful Value or
TagName replies. Literal wire and complete graph assertions cover exact
creation order, identity guards, labels, preserved metadata, save/reload and
uncertain-write termination. The actual installed console also passes an
accepted group-0 graph-only journey with PYTHONPATH removed from its process.

All **379** source/wheel/installed package files match; actual test imports
come from the installed package. All **2,734** scoped files and both new backend
binaries remain unchanged throughout final execution. Six modeled compatibility
receipts, the parity register and skip census were refreshed before freezing.

Rust validation passes the 55 affected database workflow tests plus the
copied-OID project-selection guard; the new regression also passes separately.
`cargo fmt --check`, workspace Clippy with warnings denied, and the release
workspace build pass. New binaries were built in a separate target; the earlier
shared DIN binaries remain unchanged. An independent Rust review and final
source/native and outcome reviews are retained by hash in the release receipt.
The full Rust and Toolkit suites were not run, following the request for speed.

The nine skips comprise two optional static-input tests and seven native-server
settings tests. The new static source node passes separately with pinned inputs,
and the independent parent reproducer matches its committed 133-check receipt.
Original native/hardware execution remains separate. Preserved development
attempts include the unsupported numeric scalar/sliced-XML assumptions in the
new Rust regression, corrected to OID scalar and full-network XML checks; the
production command grammar was not widened to satisfy those assumptions.

## Evidence boundaries

The static reproducer verifies 133 checks across 21 original method spans.
It establishes the missing-address predicate, prompt/role order, names and
final records without executing original instructions. This command projects
accepted/declined outcomes; it does not reproduce modal UI, generic-name and
retag storage callbacks, intermediate project-save locks or complete parent
lifecycle. Whole-plan validation precedes writes, unlike the original base
form's possible accepted-setback mutation before a later validation failure.

Original native acceptance for this new composition and physical thermostats
remain deferred under #72. The thermostat category remains `in_progress` and
complete Toolkit feature parity remains unproven. No full-suite pass is claimed.

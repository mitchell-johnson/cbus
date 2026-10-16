# Thermostat ordinary output groups — 3 October 2026

The existing `thermostat settings preview|apply` owner now accepts repeatable
`--output-group PARAMETER=ADDRESS` selections and `--resolve-output-groups`
for load-only resolution. These cover fourteen cooling/heating outputs, four
dampers and five internal relays on PC_TSA/PC_TSA5/PC_TSB/PC_TSB5. Explicit
selections run after ordinary model loading and preserve control order,
including repeated parameters and temporary unused choices for fan swaps.

One shared graph resolves the required application 172 and communication group,
the bounded selected output application, setback references, outputs, dampers,
relays and programmable schedule references. Own-prefix automatic renames and
unique generated-name reuse follow the recovered ordinary load path. Their
effects remain even when a later selection chooses another group. This does
not invoke the template allocator. Loaded control gates, per-step fan
exclusions and collection-local identity validation are explicit; a permitted
slave damper selection still saves 255.

The owner checks the fresh OID and previous name before each rename. Ordered
creations and renames share full-project freshness and preservation guards
with remote references and optional levels. Graph-only changes use zero PP
saves; other edits use one PP save and one final target project save after a
backup. An uncertain rename stops without replay, deletion or continuation.
See the [operator workflow](thermostat-settings.md) and
[source annex](thermostat-output-groups-source.md).

## Focused validation

The [release receipt](../research/fixtures/thermostat-output-groups-owned-release-20261003.json)
binds final inputs, checks and retained private evidence. Source and a fresh
noneditable installed wheel each pass **187 parent tests and 1,296 separate
subtests**, with **ten skips**. Both execute all **56 selected backend cases**:
16 new output cases, 16 existing optional-level cases and 24 existing remote
reference cases. Counts overlap and are not additive across runs.

The new cases cover all four aliases, ordered temporary-unused fan swaps,
repeated selections, automatic rename/create effects retained after reassignment,
generated-peer reuse, basic damper normalization, internal relay group 0,
missing application 172/communication group, graph-only persistence, refusals
before backup, and a lost successful Group TagName response. Literal wire and
complete graph assertions check object identity, independent existing Level
addresses/values, nonempty DLT data, PP save counts and a separate second
save/close/load cycle. The actual installed command also passes a PC_TSB5
create/select/save/reload journey with its child PYTHONPATH removed.

All **380** source/wheel/installed package file inventories and bytes match.
The installed test imports remain within its site-packages. All **4,016**
tracked and unignored repository files plus both binaries are unchanged across
final execution. Release and status annotations were added after that freeze;
no runtime, test, CI selection or packaged metadata changed. Six modeled
compatibility receipts, the parity register and skip census were refreshed.

The static parent reproducer independently matches **221 checks, 122 original
method spans and four DFM resources**. Its optional test passes separately.
Independent source, native-owner, orchestration and outcome reviews are retained
by hash. Rust is unchanged: all 469 files in the PR92 build manifest match,
and its frozen binaries are reused. This batch does not claim a new Rust build
or test run. Full Rust and Toolkit suites were not run, following the speed
request.

The ten skips comprise three optional static-input tests and seven native
settings tests. No new original instruction, Windows/native-server or physical
execution occurred. Preliminary failures remain recorded separately: an
unsupported synthetic Group Description field, an omitted empty TagsDLT field
on a second synthetic Level, an initial import-path setup error and a concurrent
source-fixture read during development. The fixture corrections preserved the
strict graph comparison and nonempty DLT data; no runtime contract was widened.

## Remaining boundaries

Typed Add dialogs, application changes, ordered zone histories, complete
initialized Windows control/message behavior, broader manager/locale name
matching and physical thermostats remain open. Selected applications are bounded
to 48–95 or 203; that range is a product boundary, not a recovered GUI filter.
Whole-plan validation precedes mutation rather than reproducing original
invalid-form partial effects. This is component-source and owned-backend
acceptance; native/hardware acceptance remains deferred under #72.

The thermostat category remains `in_progress`, and `coverage --require-complete`
exits 1. Issue #42 tracks continued work toward full Toolkit feature parity.

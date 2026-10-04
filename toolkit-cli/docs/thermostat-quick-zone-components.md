# Thermostat plant and queued-change components

This checkpoint implements two internal building blocks for the remaining
thermostat work in issue 42. They are included in the Python package but are
not yet admitted as new settings CLI operations. Existing Select/Add/Edit and
explicit damper operations retain their previously documented behavior.

## Implemented source-model behavior

`PlantTypeModel` implements all twelve direct plant parameter branches and
their separately read fan-speed branches. Its live installation getter is
called at each recovered probe position, rather than choosing a branch from
one cached installation name. It shares the owner's values, references and
graph resolver; actual changed assignments call internal synchronous hooks.
Input scalars must already have undergone source model loading. Raw invalid
Boolean initialization is outside this component.

The Group allocator uses the communication Group's live `[CGNN]` prefix,
ASCII-only name equality, exact per-owner output/damper attribute identity
exclusions and the selected application's owned address manager. That profile
sorts Group255 first, then addresses ascending, including immediate insertion
while updates suppress publication. Full-name lookup returns the actual first
match, including Group255. New allocation scans prefixed anchors backwards,
then falls back to the first unused address 0..254. A missing requested address
can be created directly. Existing Group/Level metadata remains attached to
the retained objects; it is not copied onto replacements. A typed capacity
failure preserves preceding assignments and creations for the future panel
owner's specific error7327 branch.

`PlantChangeQueue` models explicit delivery of the source-owned plant form
message1059 (`0x423`, both parameters zero). A history position selects an
actual event token issued in that same private owner. Copies, foreign tokens,
future delivery and repeated consumption refuse. Delivery consumes the event
before invoking its handler, including when that handler raises. Each delivery
reads the live model through the owned handler; enqueueing does not capture a
plant-state snapshot. Diagnostic JSON contains no transferable continuation.
This does not execute PostMessage or reproduce Windows queue scheduling.

## Executed validation

One combined selection of the two complete test modules passed in current
source and a freshly built, separately installed wheel: **76 parents per lane,
zero failures, errors, skips or subtests**. Both JUnit/execution-trace audits
passed with both required modules present. The allocation suite contains
independently transcribed whole synthetic 109-parameter/project records across
all twelve plants, identity/name/allocation cases, live repeated probes,
partial capacity failure and retained opaque metadata. The event tests cover
exact-once effects, fault consumption, ownership and diagnostic-copy isolation.

All 3,628 frozen Toolkit inputs (tracked files and the four new code/test files)
stayed unchanged through execution and terminal
readback. All 392 package files matched source, wheel ZIP and installation;
26 product-module origins in each actual pytest process matched the appropriate
source or installed package. These terminal observations are not continuous
import tracing. Parity register `--check` exited0.

Earlier author tests remain separate: the plant module initially passed62
and failed1 because a new test invented setter interleaving between two
installation probes. Its corrected, source-pinned full-module successor
passed63. A missing `--selection` audit invocation exited2. Root preparation
also retained a missing checkout virtual environment, a denied default UV
cache initialization, its dependent missing-environment install attempt and
an installed-wheel audit invoked outside a Git repository. The successful
successors do not erase those histories; no extra test execution was needed
to correct the audit working directory.

No CLI, backend service, original program, native C-Gate or physical thermostat
was exercised by this checkpoint. No broad Python suite ran. The separate
Rust diagnostic validation is not acceptance of this Python component.
The sanitized [receipt](../research/fixtures/thermostat-quick-zone-components-owned-20261004.json)
binds the executed scopes and supporting artifacts.

## Remaining integration

Connect these components to one fresh settings owner using the pinned
source-owned constructor, attribute/reference notification and control-read
roster, then test that complete composition. That owner must implement quick-zone predicates and controls,
InstalledZones dispatch, the four type/mode handlers and exact UsedZones
reads, parent Begin/End/finally guards, plant defaults, Vent updates, stage
rules, error7327 handling and queued plant delivery in source order. Initialization
of the CBus/UI/Temperature and programmable Time/Schedule child forms also
contains observer reads and bounded control effects; those must be modeled
or explicitly refused before admitting a high-level control history.

The actual twelve plant choices are source-pinned, but offering them as CLI
operations does not itself prove this lifecycle. Application migration, Delete,
other manager/locale profiles, original framework timing, native-server and
physical acceptance remain outstanding. Issue42 stays open. The historical
18/42 category ratio is unchanged and is not a percentage of full functionality.

# Old Bytecraft report dependencies

This note records the exact old `DIMPR12` registration:
`TDIMPR12`, `TDIMPR12CGateAgent`, firmware `0` through `1.9.02` under the existing
native registration comparison. Missing or malformed firmware fails closed.
The shared consumers now also admit the exact `TDIMPR12L1` /
`TDIMPR12L1CGateAgent` partition at `1.9.03` through `9`; its additional logic
roles are described in [the L1 guide](project-documentation-wireless-l1.md).
The evidence in this note retains the old-profile scope. DIMPR12A selects
the existing DIN ErrorReportOutput implementation, not these consumers.

Explicit byte-valued `Application` and at least twelve `GroupAddress` values are
required. The first application and first twelve groups project the original
channel objects. Each matching application/group identity appends `Channel N`
in channel order, retaining repeated groups and address 255. The native pipe
separator becomes the report's `<br/>`; no unused-group, DMX or scene predicate
filters this output pass. Missing or malformed consumed PP returns an
unrecovered result instead of inventing loader defaults.

The static helper and retained fixture pin the exact unit and agent registrations,
output/MaxChannels/logic VMT slots, twelve-channel constant, empty inherited
output consumer, native channel order and primary-application group loader.
The two assessment spans are reproduced against the pinned EXE/MAP. This is
static source evidence; original loader execution and original generated-page
comparison remain unperformed.

Input usage scans matching output channels first, then all 33 scenes in order.
Either on or off inclusion makes a used scene qualify, including Basic off-only
records. Its label is one-based `Scene N`, with `(Unused)` when the recall group
is unused. Repeated matching channels retain repeated descriptions. A known
nonprimary query or a query matching no channel returns empty before reading
scene records.

Other usage visits the inherited primary Area group, then application-203
C-Bus Disable and DMX Switch groups. Address 255 remains a real identity; no
unused filter suppresses these labels. Missing consumed fields preserve known
labels and a partial result independently of body/scene data.

Actions scan all 33 scenes including index zero, skip only unused scenes and
append every matching `<li />Trigger Scene N` or `<li />Advanced Trigger Scene N`
in zero-based order. Basic mode compares the recall selector Address; Advanced
compares only its Trigger application/group identity. Level Value and output
group use are not consulted. A known non-202 query returns empty independently
of scene records. Complete explicit records are required for a scene scan.

The [packed scene projection](project-documentation-bytecraft-loader.md) pins
the previously omitted Boolean normalization; high mask channels are preserved.
The [bounded body](project-documentation-bytecraft.md) separately consumes DMX,
curve, level, lock and restore fields. L1 and broader loader/history acceptance
remain excluded. These projections add no programming or hardware support.

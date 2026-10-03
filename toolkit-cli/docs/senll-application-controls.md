# SENLL application and group controls

`sensors light-level-plan` and `cgate unit sensor-light-level` accept an
explicit ordered on/off control history for the existing **SENLL ST7
2.0.01..2.4.99** profile. Each repeated `--on-off-control` selects either
`application=primary|secondary` or `group=0..254|none` (`255` also means none).
The history initializes the bounded fresh sensor projection, performs its
source-owned callbacks in order and then uses the existing forced save. It never edits
`BlockAllocation`: this original SENLL class constructs **zero InputKeys**.

```sh
cbus-toolkit sensors --spec-dir PRIVATE_SPECS light-level-plan sensor.json \
  --on-off-control application=primary \
  --on-off-control application=secondary \
  --on-off-control group=20

cbus-toolkit cgate --host HOST unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run sensor-light-level \
  --spec-dir PRIVATE_SPECS --on-off-control application=primary
```

Python callers pass the same operation list:

```python
plan = sensor.plan(values, on_off_controls=[
    {"application": "primary"},
    {"application": "secondary"},
    {"group": 20},
])
```

There must be 1..64 operations, each containing exactly one field. Boolean,
floating point, string group numbers, extra fields and caller-supplied caches
are refused by the Python API. The CLI parses integer group text and `none`.
The admitted application profile requires primary Lighting 48..95 and secondary
Lighting 48..95 or absent255. A secondary selection with absent application2
is refused. Other application families, two unused applications and retained
models with nonzero key collections remain outside this feature.

Do not combine a history with any flat application/group edit:
`--on-off-application`, `--on-off-group`, `--level-group`, `--broadcast-group`
or `--enable-group`. Those edits change graph dependencies and have no declared
position in this history. The Python keyword counterparts are refused too.
Scalar indicator, target/margin, broadcast timer, power-up and status-interval
options retain their existing final save behavior.

The flat application/group options retain their numeric profile and collision
refusal. They normalize only the on/off block's
unavailable secondary selection; they do not claim the complete inherited
application-load callbacks. `control_history` is null for this legacy path.
Complete snapshots additionally perform the inherited native scene save on
both this path and the explicit history path.
Both paths now include fresh Global interval initialization: a stored
`StatusReportInterval` of 0..2 becomes 3 before an explicit valid selection.
An ordered history records its raw and initialized values in
`global_status_initialization` before `on_off_controls`. Explicit interval
selection retains its later `flat_dialog_edits` position. Read
[Global interval notes](senll-global-status.md) for source and stale-state guards.

## Load and callback order

An explicit history loads application objects first. When the complete source
inventory is present, its primary Area getter runs before all eight secondary
bits and group references. An explicit history then loads all eight secondary bits and all eight group
references from the original snapshot. After the inherited update block ends,
an absent application2 makes the original refresh clear every true secondary
bit in ascending block order. These actual Boolean changes can cause group
collisions before the hidden Corridor, Join and PEC references are loaded.
For example, primary56, absent secondary255, eight raw group20 values and
mask254 produce groups `[20,255,255,255,255,255,255,255]` and mask0 under
`--on-off-control application=primary`. That final control is then a Boolean
no-op. The legacy flat path continues refusing this collision case.

For a changed on/off Boolean, the callback selects the destination application
from the already changed value, scans all eight blocks in ascending order and
skips itself, nil references and unused groups. It compares existing group
objects in the destination application. On the first collision it immediately
clears the switched block to the destination's unused255 group; later scan
iterations therefore see255. The key migration loop has zero iterations.
Finally, it rebinds the block's application and group. A same Boolean selection
does not run these callbacks, so an existing duplicate remains unchanged.

Non-unused group changes then invoke the multisensor callback. A reference equal
to the loaded PEC, Corridor or Join group clears to the selected application's
unused255 group. This comparison does not test enabled, active or supported
flags. PEC and Corridor reference the primary application; Corridor is loaded
even when `CorridorLinkActive` is false. Join retains the original precedence:

- Either single/dual control group assigned: application203 with the **single**
  control group, including its255 value.
- Otherwise either single/dual ordinary group assigned: primary application
  with the **single** ordinary group, including its255 value.
- Otherwise application255 with group255.

Both single and dual create-enabled getters establish their group objects in
the selected branch. The dual field determines the branch and supplies its own
established object, but does not replace the single callback reference. Thus a
primary20 object loaded only through DualJoin can survive an application switch
when SingleJoin is22 or255. Control-group precedence loads both objects in
application203 and does not establish ignored ordinary Join groups.
The unconditional primary PIR enable getter also establishes its object even
with zero occupancy keys. It does not reserve an on/off callback group; its
field is still cleared later by the forced save. Neither of these later getters
can satisfy an earlier missing-application2 load lookup.
Only an actual group object change invokes the callback. Selecting the current
object leaves it unchanged, including a current duplicate or hidden reference.

Each step rebuilds the combo exclusions from the current graph. Other blocks
and the maintenance PEC group exclude non-unused objects; the current on/off
object remains available. Hidden Corridor and Join comparisons run after an
accepted group change, separately from those combo exclusions.

## Established objects and persistence

The bounded model establishes group objects from the initial raw block getters
and, at their actual load positions, the source-owned hidden getters. It retains
those facts across later switches and clears. Thus an original secondary20
object can be selected again after clearing, returning to secondary and choosing
group20. A later hidden getter cannot enter an earlier load decision.

A destination numeric group absent from those established objects requires
additional source metadata or an original creation/declined-creation decision.
An explicit history refuses that case before staging PP. It neither creates metadata nor interprets
arbitrary numeric input as proof that an object exists. This also applies to
noncollision rebinds during the missing-application2 load refresh.

Snapshots containing any of `AreaGroupAddress`, `SceneTablePointer`,
`PatchEnable` or `SceneTable` must contain all four. Their exact byte layouts
are validated and all **47 consumed fields** participate in native schema,
stale-snapshot and readback checks. No flag or supplied catalogue/cache selects
this profile. Complete snapshots require the proven Lighting application profile
on the flat path as well. When all four are absent, the earlier 43-field profile retains
its bounded inventory and behavior.

The Area getter establishes its primary object before the missing-application2
refresh. Scene getters establish primary objects after that refresh and before
the hidden getters. The first SceneTable group255 suppresses the entire scene
walk; otherwise every raw pair is examined, including pairs after padding.
Duplicate groups within a scene keep their first level and require only their
first getter. The same group in another scene loads separately. Area and Scene
facts supply authority; they do not add collision reservations or callbacks.
An object loaded only from a Scene cannot satisfy an earlier load lookup.
`metadata_profile`, `source_inventory` and `unmodelled_group_inventories`
record the admitted inventory. Offered groups still do not represent the
complete native network catalogue.

## Inherited scene save

The CLI now preserves the native enabled-scene serialization for complete
snapshots. Exactly `PatchEnable=[157,64]` disables writing the table and pointers;
all other two-byte values enable it. Area and Patch are always preserved.
This extends save fidelity without exposing arbitrary scene editing.

Scene zero starts at raw offset zero; pointer zero is ignored. After every pair,
including an ignored duplicate or group255, only equality with the next pointer
advances one scene. Unordered, odd and duplicate pointers retain this behavior.
The loaded collection is padded to eight scenes. At most four nonempty scenes
with at most ten commands each use fixed 20-byte slots, packing nonempty scenes
in source order and setting pointers162/182/202/222. Other histories compact
the commands. Compact pointers use original scene indices and stop at the first
empty current scene, even if later nonempty scenes were packed into the table.
A single scene with eleven to forty commands therefore uses compact mode.
First-group255 histories save an empty table when enabled. These rules can
change a later reopened native history again; no canonical round-trip guard is
imposed. PP values are compared numerically, without claiming native text-token
formatting equivalence.

Before staging, apply recomputes the required table/pointer changes from the
immutable original inventory. Forged bytes and omitted normalization refuse.
The inherited scene save runs before the final SENLL forced fields.

Inspect `control_history` before applying. It records `phase_order`, initial
graph, ascending load callbacks, requested controls, before/after graph,
first collision index, scanned indices, hidden callback names, the independently
loaded `dual_join_group_after_load` and `pir_enable_group_after_load`, and each step's
offered/excluded group values. `input_key_count=0`,
`block_allocation_mutated=false` and `forced_save_last=true` express the bounded
model. Indices are zero-based. The existing plan retains the untouched original
PP expectations, native schema/identity guards and stale-snapshot comparison.
The SENLL forced save still runs last, including its clearing of Join and
Corridor fields after their earlier callback effects.

The existing native command stages this plan and owns its PP save. Existing
failure evidence and no-replay behavior remain applicable. A project save and
its persistence are separate from this subset parameter workflow. Native
staging/readback or maintained-backend tests do not establish original GUI,
physical sensor or power-cycle acceptance.

## Evidence and focused verification

The [sanitized static receipt](senll-application-controls-source.json) records
26 independently read method ranges and hashes from the pinned Toolkit EXE
`9d01721a…` and MAP `f96f05ce…`. It was produced through
`research/pir_sensor_review.py`'s `Review.code` static disassembly. No original
instructions, original GUI, native vendor service or hardware were executed.
Existing [sensor source evidence](light-level-sensor-review.json) continues
owning registration, parameter layouts, forced-save fields and dialog bindings.
The [Area/Scene static annex](senll-inventory-source-review.json) records the
independent getter, collection and serializer review for the complete inventory.

Focused producer verification uses `test_senll_control_history.py`,
`test_cli_senll_controls.py` and `test_light_level_sensors.py`. The new tests
include literal forward/reverse collisions, all eight load transitions,
same-Boolean behavior, hidden reference precedence, source-timeline refusal,
combo rebuilding, strict schema and metadata boundaries, stale apply and a
public console invocation using a temporary synthetic specification. Broader
Toolkit parity and issue41 acceptance remain unfinished.
The added `test_senll_source_inventory.py`, `test_native_sensor_scenes.py` and
`test_cgate_senll_inventory_interop.py` cover causal inventory authority,
noncanonical scene histories, source-derived apply guards and full project
save/reopen on both owned backends, including lost successful PP-save replies.

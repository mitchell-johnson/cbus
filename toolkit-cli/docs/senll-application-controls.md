# SENLL application and group controls

`sensors light-level-plan` and `cgate unit sensor-light-level` accept an
explicit ordered on/off control history for the existing **SENLL ST7
2.0.01..2.4.99** profile. Each repeated `--on-off-control` selects either
`application=primary|secondary` or `group=0..254|none` (`255` also means none).
The history initializes a fresh sensor model, performs its source-owned
callbacks in order and then uses the existing forced save. It never edits
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

The old flat options and unchanged-dialog save retain their previous numeric
profile and collision refusal. They normalize only the on/off block's
unavailable secondary selection; they do not claim the complete inherited
application-load callbacks. `control_history` is null for this legacy path.

## Load and callback order

An explicit history first loads all eight secondary bits and all eight group
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

The dual field determines the branch and does not replace the single reference.
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

A destination numeric group absent from those established objects requires an
original metadata creation or declined-creation decision. An explicit history
refuses that case before staging PP. It neither creates metadata nor interprets
arbitrary numeric input as proof that an object exists. This also applies to
noncollision rebinds during the missing-application2 load refresh.

Inspect `control_history` before applying. It records `phase_order`, initial
graph, ascending load callbacks, requested controls, before/after graph,
first collision index, scanned indices, hidden callback names and each step's
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

Focused producer verification uses `test_senll_control_history.py`,
`test_cli_senll_controls.py` and `test_light_level_sensors.py`. The new tests
include literal forward/reverse collisions, all eight load transitions,
same-Boolean behavior, hidden reference precedence, source-timeline refusal,
combo rebuilding, strict schema and metadata boundaries, stale apply and a
public console invocation using a temporary synthetic specification. Broader
Toolkit parity and issue41 acceptance remain unfinished.

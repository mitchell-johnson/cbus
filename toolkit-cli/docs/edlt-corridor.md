# eDLT Corridor controls

`EdltCorridor` implements the original Corridor group controls, timer validation
and Corridor/key conflict check for **KEYGL5 / 5055EDL firmware 5.5.00**. It
composes those controls with one original model load/save cycle and calculates
all five configuration CRCs. Native application stages database parameters;
saving remains an explicit programming-session operation.

```python
from cbus_toolkit.edlt_corridor import EdltCorridor, CorridorEdit

editor = EdltCorridor(spec)
requirements = editor.requirements(parameters)
plan = editor.plan(parameters, cache=application_cache, edits=[
    CorridorEdit("office_group", 255),
    CorridorEdit("link_group", 1),
    CorridorEdit("corridor_group", 42),
    CorridorEdit("office_group", 2),
    CorridorEdit("seconds", 300),
])
review = plan.as_dict()
result = editor.apply(database_programming_session, plan)
# database_programming_session.save_to_source() is a separate explicit save.
```

`configure(session, *, cache, edits=())` combines planning and local staging.
Edits also accept dictionaries with exactly `field` and `value`. The sequence is
limited to 64 actions, executed in the supplied order. Group requests are exact
integer bytes; timer requests are exact integers from 0 through 65535.

## Group lists and validation

The three role lists use the effective primary application and preserve the
caller's complete ordered group list. Each excludes the other two stored group
numbers. Address 255 is always inserted first as `<Disabled>` for Link or
`<Unused>` for Office/Corridor. Office and Corridor selections are disabled
while Link is 255; the timer remains enabled. An unavailable or disabled
selection raises `CorridorSelectionError` before any PP writes. The helper does
not insert temporary releases or reorder edits.

An existing group which is filtered out by another role remains stored, with
`selected: null` and a blank original control selection. Existing duplicate role
values are preserved. A role referencing a group explicitly absent from the
complete cache becomes 255 during the original binding phase, even when its
control is disabled. These are different cases and are reported separately.

The original Corridor validator rejects an enabled Link group used by a retained
key-function model in the same application. Lighting, Shutter, Fan, Timer, RCP,
Multi Level and fixed-application Enable models participate. Scene triggers and
blank/end-marker models do not. A known absent key group contributes no conflict;
this lookup reads raw group byte 6 and does not invoke the separate mutating
GroupAddress getter. `CorridorConflictError` retains the matching widget and
application/group evidence. This is the Corridor validator, not full-unit
validation.

## Timer display and stored seconds

The original schema stores a 16-bit timer. The original UI clamps its displayed
value to 60..64800 seconds, then writes on validation. Its model setter first
compares the current stored value with the displayed value; a changed assignment
passes through the original byte clamp. These observations are intentionally
preserved:

| Initial stored seconds | Requested seconds | Final display | Final stored |
| --- | --- | --- | --- |
| 254 | 300 | 300 | 255 |
| 300 | 300 | 300 | 300 |
| 300 | 256 | 256 | 255 |
| 0 | omitted | 60 | 60 |
| 65535 | omitted | 64800 | 255 |

Before the original form is shown the designer timer value is 60. The plan
records that stage, the shown state, every requested edit and final validation.
`timer.displayed_seconds`, `timer.stored_seconds` and `display_equals_stored`
must be interpreted separately. An omitted timer can change when the controls
validate. Raw model setters and forced DateTimePicker operations are outside the
public action contract.

## Cache and save boundaries

The cache is an [ApplicationCache](edlt-application-cache.md), including its
LifecycleCache facts. Require a named effective primary application, its complete
ordered group list, all lifecycle facts, and known consistent presence facts for
retained key-function groups. Unknown facts fail planning. Group names can be
duplicated; numeric addresses cannot. The caller declares cache contents and
completeness. The helper neither creates metadata nor checks cache freshness.

One `EdltLifecycle.load` retains the widget/scene objects; its unchanged
`prepare_save` is called once. The four final Corridor fields are overlaid on
that save projection, followed by fresh CRC calculation. This preserves loaded
scene references and MRA save propagation. The plan is a terminal whole-unit
projection, not a resumable form state or a composition with application edits.
`after_load`, `after_controls`, `before_save`, final changes and control facts
are exposed for review.

Apply requires the supported schema and matching database session identity,
validates every supplied phase strictly, reconstructs the canonical plan and
rejects stale parameters. It compares all parameters after staging. Ordinary
failures attempt rollback only while the existing connection remains usable;
interruptions retain their original exception and `edlt_corridor_evidence`
without replay. `CorridorApplyError` is an `EdltApplyError` and preserves command
and cleanup causes. No hardware destination is supported by this helper.

## Evidence and limits

The [original vector fixture](../research/fixtures/edlt-corridor-original-vectors.json)
contains 74 independently captured Windows cases: 63 accepted, 10 unavailable
selections and one Corridor conflict. Each accepted case compares all 874
parameters after load, after controls and after save/CRC, plus the actual role
lists, selected values, enabled state and timer stages. Twelve combined cases
exercise Lighting, Scene, MRA, sequential role changes, disabled secondary
application, existing duplicate roles and missing cached groups.

The [probe](../research/NativeEdltCorridorProbe.cs) uses the pinned original
Toolkit 1.18.0.2754, CBusLogicModel 7.14.0.0 and eDLT 7.16.0.0 assemblies in a
Windows x86 process. Actual original ComboBoxAddEdit and TimerSelector controls
run the declared bindings and business methods. An owned outer host replaces
full FrmBaseUnit construction. The fixture and acceptance record pin original source, assembly,
compiled probe, input, output, runner and loaded framework provenance. Earlier
153-case research and the 12-case timer supplement retain their negative and
forced-diagnostic observations separately; they are not all supported saves.

The [acceptance record](../research/fixtures/edlt-corridor-acceptance.json)
records final Python 3.13 and 3.10 results and native reports. Each native matrix
uses a unique closed database project on owned loopback C-Gate. Ten accepted
cases compare all 874 staged parameters and five CRCs, logical raw bytes
`0x132..0x136`, and the complete parameters and raw bytes after a separate save,
close and load for that case. Two rejected cases leave staged parameters
unchanged. Projects are removed afterward; no network is opened.

The final combined suite passed **10 tests with zero skips** on Python
**3.13.14** (28.378 s) and **3.10.20** (35.333 s). The captured-vector comparison
checks 165,186 parameter values per run, independently of native persistence.
Sources and test inputs were hashed before and after each native run and
confirmed unchanged. Earlier native runs remain historical evidence of their
original scope; the final records identify the strengthened phase guards and
per-case reload checks.

Full FrmBaseUnit initialization, interactive metadata creation, other bound
widget panels, application changes, physical transfer, runtime Corridor timing
and hardware power-cycle behaviour remain outside this verified scope.

## CLI

```sh
cbus-toolkit edlt corridor-plan snapshot.json --metadata corridor-cache.json \
  --edit link_group=42 --edit office_group=1 --edit seconds=256
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-corridor --metadata corridor-cache.json --edit seconds=300
```

Edits run in argument order, up to 64 per operation. Remove `--dry-run` to save
to the database source, then save the project for disk persistence. The plan
reports displayed and stored timer values separately. [CLI acceptance](../research/fixtures/edlt-ordered-control-cli-finalization-acceptance.json)
covers offline/native plans, guards, interruption evidence and full save/close/load
readback on Python 3.13 and 3.10.

The CLI retains staging evidence if the final readback, save, programming cleanup
or connection cleanup fails. A lost save reply reports an uncertain save; a
confirmed save remains confirmed when later cleanup fails. It does not replay
or roll back an uncertain save. Fresh per-command evidence also survives an
interruption that refuses exception attributes, without borrowing a previous
operation's evidence.

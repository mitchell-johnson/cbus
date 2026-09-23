# eDLT Time and Date widgets

`EdltTimeDateWidget` implements the original TimeAndDateData display settings for KEYGL5.xml, catalog5055EDL, firmware5.5.00. It edits complete database PP snapshots, produces a reviewable plan, verifies native readback, and leaves saving explicit. It does not set the clock or select a Timekeeping source.

```sh
cbus-toolkit edlt time-date-plan --help
cbus-toolkit cgate unit edlt-time-date --help
```

The typed Python API is:

```python
helper = EdltTimeDateWidget(spec)
plan = helper.plan(values, page=0, position=1, slices=2,
                   display='time-date', date_format=1,
                   time_format='24-hour', leading_zero=True)
result = helper.apply(database_session, plan)
# The caller may then explicitly save the staged database session.
```

All original UI placements are supported. `page=0` selects the standby screen, where single-slice widgets occupy positions1..5 and two-slice widgets may start at positions1..4. A covered second slot cannot be selected until the previous two-slice widget is reduced to one slice. Functional pages permit a single-slice Time/Date widget at every normal position: page1 positions1..5 in single-page mode, or pages1..4 positions1..4 in multiple-page mode. The navigation widget is a different type and is outside this helper.

`page_mode` preserves the current setting when omitted. `slices=None` retains an existing Time/Date type, otherwise chooses one slice. `display=None` retains a valid existing display byte. An invalid existing display requires an explicit valid choice; the helper does not guess how a rendered WinForms control would coerce unsupported data.

| Display | Byte1 | Single-slice type | Two-slice type |
|---|---:|---:|---:|
| `time` |0|10|11|
| `date` |1|10|11|
| `time-date` |2|10|11|

The six fresh records contain the type and display bytes followed by30 zero bytes. Existing bytes2..31 are preserved. Original `TimeAndDateData.SetToDefault` changes no record bytes; its inherited behavior resets a functional widget's restore value only when its type actually changes. Same-type edits retain that restore value. Standby widgets have no schema RestoreLevel parameter, so one is never invented.

## Neighbor changes and preservation

Changing a widget into type11 sets the immediately following widget's type to0, including a configured HVAC Temperature, Measurement, or Time/Date neighbor. The next widget's opaque bytes remain intact. The plan exposes its before and after records under `adjacent_before_hex` and `adjacent_after_hex`.

Assigning type11 to a widget already of that type makes no adjacent change. Even an existing configured hidden neighbor remains unchanged by the original type setter and `BeforeSavePPData`. Changing type11 to10 also leaves the neighbor as it is; it does not reconstruct data from before the earlier conversion. The helper reproduces these distinctions and reports the changes, including configured neighbors, before application.

The original property's raw setter permits some placements absent from its UI and throws at widget21 while leaving a notification flag set. These are negative fixtures. The helper rejects off-UI placements before any native edit.

Plans also apply the separately verified functional terminator normalization: changed blank/terminator types reset their restore values, same-type values remain intact, and a unit with no active functional widgets places its terminator at widget6. Shared text and scene payloads are preserved. This is a staged widget-edit scope; it does not emulate every unrelated GUI load/save transformation or repair malformed raw layouts.

## Unit-wide formats

Format options apply to the entire unit, including other Time/Date widgets and applicable navigation displays. Omitted settings retain their values. Plans explicitly report `global_format_changes` and `global_formats_apply_to_whole_unit`.

| Date code | Original format |
|---:|---|
|0|`dddd dd Mmm`|
|1|`ddd dd Mmm`|
|2|`ddd dd/mm`|
|3|`ddd mm/dd`|
|4|`dd/mm`|
|5|`mm/dd`|
|6|`dd Mmm`|
|7|`Mmm dd`|

| Time option | Original value |
|---|---:|
|`12-hour`|3|
|`24-hour`|1|
|`12-hour-lowercase` (am/pm)|0|
|`12-hour-uppercase` (AM/PM)|2|

`leading_zero` is boolean. The three fields share address0x119: date uses bits0..3, leading zero bit4, time bits5..6. The untouched bit is preserved by parameter writes. UnitSpec defaults are date1, time3, leading zero0.

Toolkit help18911 describes Timekeeping application messages from C-Touch, Wiser, or CNI, and occupant adjustment of the local clock through the eDLT's on-device Tools page. The audited Toolkit model/spec contains no TimeSource widget field or wall-clock-setting PP field. Those independent time-distribution/device operations are not implemented by this helper. The original DLL exposes eight date choices and five standby positions; some bundled help text has older counts.

## Validation and evidence

Canonical plans retain their complete expected state. Applying checks exact profile/schema, database-only source, unchanged PP values, and reconstructed options before writes. It verifies the entire resulting PP state; ordinary failures roll back attempted parameters while the connection remains usable. A disconnected stream is not reopened or retried. Results distinguish native PP verification from saving and physical device verification.

`research/NativeEdltTimeDateProbe.cs` executes unchanged original CBusLogicModel.dll and the original eDLT.dll availability method without rendering UI or accessing hardware. It covers all six literal display records, all64 original format combinations, all21 normal widget locations plus navigation, configured neighbor types, opaque/default/same-type behavior, and original save normalization. A separate mode applies original properties and `BeforeSavePPData` to explicit full native PP fixtures and calculates all five CRCs using the original assembly.

`tests/test_edlt_time_date.py` compares those independent vectors and original full-parameter outcomes with Python plans, checks every supported placement and global-format combination through native C-Gate raw bytes, and saves/closes/reloads the entire database state. The original full-save fixtures use an explicitly staged empty-scene representation so unrelated GUI scene compaction is not hidden inside widget evidence. Root CLI acceptance lives in `tests/test_cli_edlt_time_date.py`.

Machine-readable acceptance counts, source hashes, runtime report paths and scope are in `research/fixtures/edlt-time-date-acceptance.json`. The vendor assemblies and UnitSpec are user-supplied research inputs and are not distributed with the package. Hardware display rendering, actual clock behavior, navigation widget authoring and other device/firmware profiles remain outside this accepted scope.

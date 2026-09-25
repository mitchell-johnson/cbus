# eDLT Measurement and Percentage parent composition

`EdltParentForm` composes one **KEYGL5 / 5055EDL firmware 5.5.00**
Measurement panel edit and the parent form's proximity percentage control
through the retained eDLT model lifecycle. It is the first bounded workflow
that joins these controls with `AfterLoadPPData`, source-pinned binding
semantics, `BeforeSavePPData`, all five configuration CRCs, stale-plan checks,
full readback and database save.

For several distinct widget edits in one retained save, use the
[ordered parent transaction](edlt-parent-transaction.md). It accepts
Measurement, Lighting and proximity activation operations, rejects overlapping
byte ownership and performs one terminal lifecycle/CRC projection.

Preview a database export without I/O:

```sh
cbus-toolkit edlt parent-form-plan unit.json \
  --metadata lifecycle-cache.json \
  --page 1 --position 1 --device-id 42 --channel 3 \
  --gain-value '1.5' --offset-value '-2.5' \
  --measurement-culture en-NZ \
  --wake-mode primary-event --group 42 --level-percent 50
```

Apply the same plan to a C-Gate database unit:

```sh
cbus-toolkit cgate unit \
  --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 \
  edlt-parent-form --metadata lifecycle-cache.json \
  --page 1 --position 1 --device-id 42 --channel 3 \
  --gain-value '1.5' --measurement-culture en-NZ \
  --wake-mode primary-event --group 42 --level-percent 50
```

Use `--dry-run` before `edlt-parent-form` to stage and verify the complete
result without issuing `SAVE`. The native workflow accepts database
destinations only and checks the exact unit type, catalogue number and firmware
before reading PP values.

## Composition contract

The API takes separate control mappings so unsupported fields fail closed:

```python
from cbus_toolkit.edlt_parent_form import EdltParentForm

editor = EdltParentForm(spec)
plan = editor.plan(
    current,
    metadata=lifecycle_cache,
    measurement={
        "page": 1, "position": 1, "device_id": 42, "channel": 3,
        "gain_value": "1.5", "measurement_culture": "en-NZ",
    },
    activation={
        "wake_mode": "primary-event", "group": 42,
        "level_percent": "50",
    },
)
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

Measurement accepts the same exact pairs, decimal culture profiles, text
references, built-in icons and placement settings as
[`EdltMeasurementWidget`](edlt-measurement.md). Activation accepts wake mode,
numeric group, percentage, trigger action, activation page and first-key
behavior. The percentage and action options select the same stored
`ProximityLevel` byte and remain mutually exclusive.

The planner performs these phases in order:

1. validate a complete profile snapshot and caller-supplied lifecycle cache;
2. execute the retained model's load normalization without binding controls;
3. validate the complete Measurement edit, resolving Gain before Offset;
4. convert the percentage with the original Decimal arithmetic and validate
   its visibility against the resulting wake mode;
5. overlay only the validated control fields on the retained model;
6. serialize retained scenes, MRA state, functional terminators and the other
   original save hooks;
7. calculate all five CRCs; and
8. before mutation, rebuild the canonical plan and compare the full live
   source snapshot. Writes are followed by a full readback. Failures attempt
   reverse-order rollback while the connection remains usable.

This ordering is deliberately stronger than an interactive form. The original
form commits `OnPropertyChanged` bindings immediately and default bindings when
their control validates. Its Save path validates the active control, serial
number, Scene widget configuration and unit model before the save callback; it
does not explicitly call `ValidateChildren` for every inactive control. The
CLI validates every supplied value before its first PP write, avoiding a
partially committed inactive edit.

## Percentage cross-control behavior

The original `NumUpDownPercentage` is bound to `ProximityLevel` with the
default `OnValidation` update mode. `ProximityMode` is an
`OnPropertyChanged` binding:

- mode 2 (`primary-event`) shows the percentage panel and interprets the byte
  as an event level;
- mode 3 (`trigger-event`) hides that panel and interprets the same byte as an
  action selector; and
- modes 0 and 1 retain the hidden byte without an event meaning.

The parent plan reports `meaning_before`, `meaning_after`, `visible_after`, the
raw byte, the exact bound percentages before and after, and whether conversion
occurred before mutation. For example, entered percentage `50` stores byte 127;
the exact percentage obtained when that byte is rebound is
`49.803921568627450980392156863`. A percentage supplied for a resulting mode
other than 2 is rejected. Switching to trigger mode can instead use
`--action-selector` and preserves the explicit reinterpretation in the report.

## Original order and evidence

`FrmBaseUnit.LoadUnit` schedules `BackgroundWorker.LoadUnitThreadMain` and then
calls `SetEDLTFrm`. The synchronous form-construction branch is:

1. `InitializeComponent`;
2. bind the base unit and network sources;
3. `PopulateWidgetPanels`;
4. recursively `SetUpControls`; and
5. `SetupForm` subscriptions and dependent controls.

The worker branch performs `ReadPPData` → `AfterLoadPPData` →
`CreateUnitLogic` → `LoadSucceeded`, followed by `OnLoadCompleted`. The source
does not impose a total order between completion of that worker branch and the
synchronous form construction. The Python planner removes this race by
completing the retained load model before projecting any control edits and
reports that difference explicitly.

When a Measurement widget is selected, its binding branch is `ShowWidget` →
`BaseWidget.SetWidgetData` → base data-source setup → Measurement data-source
setup. `PopulateWidgetPanels` constructs the Measurement panel fourth, after
Enable, Fan and HVAC, but its Measurement-specific data bindings are installed
when a type-12 widget is selected.

`InitializeComponent` constructs `NumUpDownPercentage`, starts initialization,
adds its `PercentageValueAsByte` binding, assigns byte 2, then assigns numeric
`Value=1` and ends initialization. `SetEDLTFrm` assigns the actual `EDLTUnit` to
`bsMainUnit` later, causing the binding to read the model's current
`ProximityLevel`; the two designer values are therefore transient. The control
constructor wires its internal textbox's focus, click and mouse-up events to
SelectAll. Retained native observations did not see corresponding click action
events, so the plan records those handlers as source facts without claiming
their runtime interaction.

Measurement `BigIconIndex` and `Precision` use `OnPropertyChanged` bindings.
Channel, DeviceID, prefix, suffix, function status, Gain and Offset use
`OnValidation`. Gain and Offset additionally register `TextChanged`, `Enter`
and `Validating` handlers in that order. The proximity mode uses
`OnPropertyChanged`; both the trigger action selector and percentage byte use
default `OnValidation` bindings to the same `ProximityLevel` property.

[`edlt-parent-form-evidence.json`](../research/fixtures/edlt-parent-form-evidence.json)
pins the six inspected original source hashes, initialization and save order,
and hashes of the retained native Measurement and Percentage captures. The
native captures establish actual Measurement panel validation and actual
standalone `NumUpDownPercentage` behavior. The new Python differential tests
show that each composed control matches its standalone accepted model and that
all fields outside the declared control/save effects equal an unedited retained
lifecycle save.

[`edlt-parent-form-acceptance.json`](../research/fixtures/edlt-parent-form-acceptance.json)
records the focused, related-regression, full offline and Rust-loopback gates.
It records the optional native test as skipped rather than promoting it to
acceptance.

The original full `FrmBaseUnit` has **not** been executed end to end for this
composition. The plan reports `native_parent_form_executed=false` and
`winforms_focus_and_dialog_behavior_verified=false`. It does not model
per-keystroke text restoration, caret selection, focus changes, message boxes,
row rendering or operator timing. The optional native C-Gate test verifies a
database save/close/load when its endpoint and vendor specification are
provided; that is native persistence evidence, not original GUI execution or
physical-device evidence.

## Preservation and remaining boundaries

The result contains four deltas: `after_load`, `controls`, `before_save` and
`crc`. `preservation.composition_delta_from_unedited_lifecycle` lists every
field added by the two controls relative to an otherwise identical lifecycle
save. Planning fails if composition changes any other field. Selected
Measurement opaque bytes 14..31, all nonselected widgets, static strings not
allocated by this edit, retained scenes and the existing MRA source remain
unchanged except for independently documented lifecycle normalization.

Caller metadata is authoritative and is never created or refreshed by this
workflow. Cache freshness, physical transfer, display rendering, incoming
measurements, physical wake/event behavior, other firmware/catalogue profiles,
other culture profiles and the rest of `FrmBaseUnit` remain separate work.

Run the focused portable checks from `toolkit-cli/`:

```sh
PYTHONPATH=src:. python3.13 -m unittest \
  tests.test_edlt_parent_form tests.test_cli_edlt_parent_form -v
```

The portable checkpoint contains 14 passing tests. One additional test is
gated by `CBUS_CGATE_TEST_HOST` and `CBUS_UNITSPEC_DIR` and performs a fresh
native database create, apply, save, close and reload. Offline success does not
claim that optional native test ran.

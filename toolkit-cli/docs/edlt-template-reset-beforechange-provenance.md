# eDLT template reset and BeforeChange provenance

This review joins existing [Reset evidence](edlt-reset.md), the retained
[rebind proxy capture](edlt-template-rebind-recovery.md), and fresh static
inspection of the original methods. It runs no new original method, IL VM,
Windows control, project, or device operation. It does not close template Apply.

The source images are eDLT.dll 7.16.0.0, SHA-256
`75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3`,
and CBusLogicModel.dll 7.14.0.0, SHA-256
`34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`.
Private text inspection used the task-6 `managed-pass` IL. Method bodies remain
private; the committed report describes their contracts and offsets.

## Reset evidence must retain its origin

`FrmBaseUnit.ResetUnit(bool)` (`060002e8`, RVA `19004`, IL SHA-256
`758439e6df67570d72e98ea8678c1b573b54345ffabd9b3122a0c1d194607490`)
calls `ShowWidget(0)` before testing the specification or resetting PP data.
After BeforeChange it calls **CBusBaseUnit.ResetToDefaults**, not the similarly
named CBusBaseModel method. On the silent path, a false ResetToDefaults result
bypasses the assignment that would make ResetUnit return false (`0097–00af`).
The template caller discards ResetUnit's Boolean. A true return is therefore
not a reset-state certificate.

CBusBaseUnit.ResetToDefaults (286 IL bytes) is a local model operation:

- A null UnitSpec returns false before setting initialization mode (`0000–0009`).
- It sets the static `PPAttribute.bInitialiseMode` to true, then visits
  `UnitSpec.Descendants("Param")` in XML order (`000a–0025`).
- It excludes UnitAddress, SerialNumber, Project, NetworkAddress,
  ConfigVersionMinor and ConfigVersionMajor. Unknown PP names are skipped.
- UnitName uses the default string directly. Other defaults pass through
  FormatValueFromUnitSpec: trim, split on literal spaces preserving empty
  slots, replace `$0` then `$` with `0x`, replace a whole `0x` token with
  `0x0`, and rejoin with spaces. The current value gains `0x` only for the
  comparison when it lacks that exact prefix.
- Equal strings are skipped. The special WidgetType skip requires current
  comparison `0x0` and default exactly lowercase `0xff` (`00c6–00ec`).
  Numerically equivalent uppercase `0xFF` is a different path.
- Otherwise it calls raw `PPAttribute.Value` and explicitly marks the PP
  changed (`00ee–00f7`). Raw setter slot semantics remain relevant.
- Its only finally disposes the enumerator. Ordinary completion sets
  initialization mode to true again (`0116–0117`), rather than restoring an
  entry flag. There is no encompassing rollback for partial assignments.

ResetUnit then zeroes byte 1 on the old widget objects, calls AfterChange,
selects the single widget numbered 10, sets its type to 10 and its byte 1 to
literal `0x2`. These operations are distinct from the default assignments and
from later BeforeSave/CRC/persistence.

The existing EdltResetControls implementation admits one bounded profile:
all 874 raw PP values, complete application cache, explicit tab and binding
variant, supported initial widget types and navigation 0 or 1. Its retained
Windows partial-form matrix proves that admitted transition, including dirty
and raw spelling phases. It does not recover arbitrary prior control history.
A reset prelude should consume the issued reset graph and exact context from
that transition. A caller-supplied numeric default image, generic PP overlay,
or Boolean is not equivalent provenance. A prelude need not run BeforeSave or
persist anything to make its post-reset raw/dirty phase useful.

## The seven radio writes are binding-dependent

BeforeChangePpAttributes (`060002dd`, RVA `1851c`) directly performs only timer
Stop followed by these Checked=true requests in order:

| Radio | Checked binding / paired PP radio | Source group |
| --- | --- | --- |
| radioButton5 | getter-only IdleIndicatorBrightnessByFixedLevel / ppRadioButton5 | IndicatorIdleBrightnessControlGroup |
| radioButton3 | getter-only IdleScreenBrightnessByFixedLevel / ppRadioButton3 | BacklightIdleBrightnessControlGroup |
| rbColourIndicatorOffFixedColour | no direct Checked binding / ppRadioButton1 | IndicatorOffColourControlGroup |
| rbColourIndicatorOnFixedColour | no direct Checked binding / ppRadioButton2 | IndicatorOnColourControlGroup |
| radioButton4 | getter-only EnableIndicatorBrightnessByFixedLevel / ppRadioButton4 | IndicatorActiveBrightnessControlGroup |
| radioButton6 | getter-only EnableScreenBrightnessByFixedLevel / ppRadioButton6 | BacklightActiveBrightnessControlGroup |
| rbRestorePreset | DisableLevelStore, explicit update mode 1 | EnableLevelStore |

The first six paired controls share their respective GroupBox in
InitializeComponent. The four getter-only brightness bindings use the
four-argument Binding constructor; they are not direct writable model
properties. The fixed-colour radios also supply Visible bindings to their
colour ComboBoxes in SetEDLTFrm (`020e`, `022f`). No direct CheckedChanged
subscription for these seven radios appears in FrmBaseUnit's initializer.
This does not mean they lack binding or group-induced notifications.

PPRadioButton.set_DataBindingObject assigns its object, then, when nonnull,
calls SetUpDataSource and SetUpDataBindings. SetUpDataSource reflects the named
property and retains its PPAttributeDataSourceLogic instance. SetUpDataBindings
clears existing bindings before binding Checked to that instance's IsEnabled
with explicit DataSourceUpdateMode 1 (`0031–0033`, OnPropertyChanged).
ResetControlBinding invokes this setter and then SetUpDataBindings again.
Consequently object identity and the successful completion of both setup calls
matter; recording the setter dispatch does not establish a usable binding.

EDLTUnit.AfterLoadPPData constructs each of the six group logic objects with
the named PP as both value and enable attribute, `bHide=true`, and
`DisabledValue=255`. The constructor calls are at `0380`, `03cf`, `041e`,
`046d`, `04bc`, and `050b`. Their lists resolve PrimaryApplication's Groups.
PPAttributeLogic's constructor subscribes to the enable PP; its own
`_ppEnableAttribute_PropertyChanged` body is empty. Other data-source and
unit subscriptions are separate and cannot be inferred from that empty body.

There is a useful **conditional data fixed point** after the retained reset:
if each actual retained logic object still references the intended fresh PP,
its DisabledValue is 255, and it receives IsEnabled=false while that PP's
ValueAsInt is 255, the setter branches directly to return (`0014 → 0057`).
It does not assign, normalize raw casing, mark dirty, or issue its own
NotifyPropertyChanged. Likewise DisableLevelStore(true) returns without a
write or its own notifications when EnableLevelStore.ValueAsInt is already
zero (`0018 → 005e`). Thus the six `0xFF` groups and `0x0` level store are
fixed points of these particular setter invocations.

This statement does not establish that those setters were delivered, that no
opposite true invocation or other event ran, or that all current radios and
binding sources refer to the fresh graph. An IsEnabled=true invocation on a
disabled source takes EnableLogic instead. A copied PP dictionary cannot
establish the object-identity, group-state, subscription, or reentry conditions.
The bounded Reset matrix reports the six groups unchanged in its tested first
BeforeChange, with EnableLevelStore's conditional zero branch. The second
BeforeChange after panel recreation remains a separate control-history gate.

## Returned callbacks are not successful editor restoration

SetupForm subscribes to PP, unit, network, and widget events. Its shown method
does not first unsubscribe or deduplicate those subscriptions. The actual
subscriber inventory after repeated reset/setup depends on retained object
identities and earlier setup/disposal. The rebind proxy records delegate
creation and adds; it does not execute event handlers.

SetUpControls catches individual ComboBox and PPRadio binding-setter failures,
logs/displays them, and continues. SetupForm catches early setup failures,
logs them and calls OnFormClosed, then continues its later setup section.
The original OnFormClosed attempts to clear bindings, suppress control events
and dispose controls/form before its own close dispatch and panel disposal.
The existing proxy treats it as opaque, so a recorded close call proves none
of those disposal effects. An expanded AfterChange returning after child
dispatch is still not a control-restoration certificate.

[`edlt_template_rebind_outcomes.py`](../research/edlt_template_rebind_outcomes.py)
classifies only the existing hash-pinned 31-case capture. It imports no
interpreter and executes no original method. Its
[report](../research/edlt_template_rebind_outcomes.json) separates:

- 7 `dispatch_only` cases: the interpreted method returned without an observed
  injected failure; actual callback effects remain unverified.
- 3 `returned_with_caught_failure` cases: two SetUpControls binding failures and
  one SetupForm PP-subscription failure. The latter records OnFormClosed and
  subsequent setup callbacks, not actual successful closure or recovery.
- 21 `propagated_failure` cases: the top interpreted invocation failed. Earlier
  proxy changes may remain, and finally callbacks may follow the failed call.

The compact capture omits mechanical calls, including the failed get_Controls
call in case 12. The classifier preserves the configured index and explicitly
marks that omitted callback. It copies the full-trace hash as capture
provenance without claiming to recompute it from the reduced callback list.
All original effects, persistence and Apply authorization fields remain false.
This report is research evidence, never an accepted runtime receipt.

To regenerate this small report without vendor code or a VM:

```sh
python research/edlt_template_rebind_outcomes.py --output /tmp/new-rebind-outcomes.json
```

The remaining gates are panel construction/disposal and bindings on the same
fresh graph, the second BeforeChange's actual notification history, ordered
assignment and AfterLoad/rebind effects, active-control validation, and the
separate terminal save/close/load proof. Existing reset evidence and these
static fixed points can narrow those gates; they do not silently satisfy them.

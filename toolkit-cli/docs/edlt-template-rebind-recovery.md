# eDLT template parent rebind recovery

The research harness replays six unchanged, hash-pinned original eDLT method
bodies through a bounded IL interpreter and explicit synthetic proxies. It
establishes their callback order, recursion, branch decisions and exception
dispatch under those proxy inputs. It does **not** execute an original
WinForms form, original control bindings or original model callbacks.

This is evidence for [#45's parent transition](https://github.com/mitchell-johnson/cbus/issues/45#issuecomment-5906824162),
used by [#43's template workflow](edlt-template-workflow.md). It does not
remove the template Apply refusal.

## Executable evidence

- [edlt_template_rebind_metadata.cs](../research/edlt_template_rebind_metadata.cs)
  runs in the existing owned Mono runtime, reads metadata with Mono.Cecil and
  obtains raw IL-byte hashes from the original PE image. It never loads or
  instantiates a vendor type. Its private output contains decoded instructions
  and exception regions; that vendor instruction stream is not committed.
- [edlt_template_rebind_proxy.py](../research/edlt_template_rebind_proxy.py)
  interprets those instructions. Each external call goes through an explicit
  named proxy dispatcher. Unknown instructions, calls, types, inputs, excessive
  recursion and excessive instruction counts fail closed. Interpreter failures
  cannot masquerade as original caught `System.Exception` failures.
- [edlt_template_rebind_vectors.json](../research/edlt_template_rebind_vectors.json)
  records source/runtime hashes, 14 method proofs and their direct call graph,
  plus 31 synthetic cases. It retains meaningful callback traces and a SHA-256
  of each complete trace. No assembly, unit specification or full IL body is
  included.

The focused capture passed **31 cases**, **6,142 interpreted instructions** and
**1,972 dispatched calls**. Its managed compile/read stage completed in about
one second. These are proxy observations, not 31 original Toolkit workflows.
The retained source is `eDLT.dll` 7.16.0.0 from Toolkit 1.18.0.2754, SHA-256
`75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3`.

| Interpreted method | Token | RVA | IL bytes |
| --- | --- | --- | --- |
| BeforeChangePpAttributes | `060002DD` | `1851C` | 96 |
| AfterChangePpAttributes | `060002DE` | `18588` | 84 |
| PopulateWidgetPanels | `06000308` | `1ABB4` | 532 |
| ResetControlBinding | `0600030A` | `1AF24` | 108 |
| SetUpControls | `0600030C` | `1B090` | 195 |
| SetupForm | `0600030E` | `1B288` | 607 |

The additional eight methods are call-graph recovery only: WidgetPage's
setter, ClearControlsRecursively, ResumeDrawing, ShowSelectedWidget,
ShowWidget, UpdateNavigationControl, FilterWidgets and the page-tab handler.
Their real effects are not inferred from a recorded call.

## Newly resolved callback contracts

**BeforeChangePpAttributes** stops the redraw timer and checks seven original
radio controls in source order. The fixture injects a failure before each of
its eight calls. Each unhandled failure stops the remaining calls and retains
the earlier proxy changes. It does not assert that a checked-radio assignment
has no WinForms notification or PP side effect.

**AfterChangePpAttributes** calls AfterLoadPPData, SetupForm, gets the form's
Controls collection, recursively sets up controls, populates applications,
resets bindings with `true`, updates navigation, shows the selected widget,
invokes the page-tab handler with `(this, null)`, then starts redraw. The
fixture covers failure before each of those ten calls and an expanded pass
through the interpreted SetupForm and SetUpControls bodies. AfterLoad and
the remaining model/navigation/widget/page callbacks are explicit opaque
proxies; no refreshed PP image is produced.

**PopulateWidgetPanels** first disposes every old panel, then clears the panel
list. It constructs panels in this order: Enable, Fan, HVAC, Measurement, MRA
Source Control, MRA Source Select, MRA Zone, Multi Level, Room Courtesy, Scene,
Shutter, Timer, Time/Date single-slice, Time/Date two-slice, Lighting and Page.
The Page panel receives the current PageWidget model before joining the list.
Every new panel is added to the container and docked; `ShowWidget(0)`,
application population and `ResumeDrawing` follow. There is no restoration
of already disposed panels if disposal fails, or of the cleared list if a
constructor fails. The fixture captures both failure boundaries. Constructors,
Dispose, SetWidgetData, docking and drawing all have proxy effects only.

**SetUpControls** traverses child-first. A BaseWidget is skipped **together
with its descendants**. For other controls it recurses, binds a
ComboBoxAddEdit, then binds a PPRadioButton. Each of those two binding setters
has its own catch: log the exception, display the diagnostic message box and
continue traversal. The fixture proves the child-before-parent order, the
BaseWidget skip, both caught setter failures, and a later control still being
visited. Message boxes and log writes are only recorded callbacks.

**ResetControlBinding** is different: it recurses into all controls, including
BaseWidget descendants. It calls SetUpDataBindings on ComboBoxAddEdit and,
for PPRadioButton, sets DataBindingObject before SetUpDataBindings. There is
no local binding-setter catch. Its enumerator disposal runs when a setter
throws, and the failure propagates. Replacing one traversal with the other
would therefore change both selected controls and failure behavior.

**SetupForm** subscribes to PP PropertyChanged events, calls
ResetControlBinding, subscribes to unit, network and widget PropertyChanged
events, then sets WidgetPage to 1. The encompassing catch logs an exception
and calls `OnFormClosed(null)`, but execution then **continues** into later
setup. That later section adds ComboBox/DataGridView handlers, invalidates the
form, sets WidgetPage to 0 then 1, adds selection handling, updates navigation,
clears old restore controls and constructs 16 restore controls for widget
indices 5 through 20, before BringToFront/Refresh. The fixture captures a PP
subscription failure, the close callback and the subsequent 16-control setup.

Consequently, an ordinary return from SetupForm, SetUpControls or
AfterChangePpAttributes does not by itself establish successful rebinding.
A safe lifecycle adapter must retain caught binding/setup failures and avoid
advertising a successfully rebound editor after those failures.

## Proxy assumptions and remaining apply gates

The form and controls are plain synthetic objects. Enumerators traverse fixed
snapshots; value-type enumerator address operations refer to the corresponding
proxy object. The fixture does not simulate WinForms reentrancy or collection
changes caused by real control disposal. Delegate creation and subscription
are recorded without invoking their handlers. A property assignment changes
only the proxy field; it does not run OnValidation, OnPropertyChanged, cached
metadata lookup, notifications, UI validation or native rendering.

The supplied unit has two placeholder PP objects, 21 placeholder widgets and
a placeholder network. These are enumeration inputs, not a retained original
model. The restore-control container starts empty. ClearControlsRecursively
is recorded only under that checked empty-container precondition; a nonempty
container is refused. Repeated real SetupForm/Reset histories and actual
event-subscription lifetime remain unproved.

Before enabling template application, capture a complete original loaded form
with the admitted control history and prove the effects of these callbacks on
the same PP/model/cache objects: initial reset, panel disposal/construction,
BeforeChange events, ordered assignment, AfterLoad rebuilding, both binding
traversals, page/selection refresh and later validation/Apply. Recover the
remaining callback bodies and actual control notifications where they affect
state. Verify failure, cancellation and unchanged persistence before Apply,
then one save/close/load result. Rendering and physical behavior remain
separate gates.

A stage receipt can truthfully distinguish `dispatch_completed` from
`control_binding_effects_verified`. For the present proxy evidence the latter,
`original_form_executed`, `model_callbacks_executed`, `persisted` and physical
verification must remain false. Caught-error and close-callback observations
must survive even when the interpreted method returns normally.

## Reproduction

Use explicitly supplied private inputs and a fresh scratch directory:

```sh
python research/edlt_template_rebind_proxy.py \
  --edlt-dll /private/toolkit/app/eDLT.dll \
  --mono-root /private/owned-mono/6.12.0 \
  --output /tmp/owned-edlt-rebind-new \
  --verify-fixture research/edlt_template_rebind_vectors.json
```

The runner pins the original assembly, Mono runtime/compiler, mscorlib,
Mono.Cecil and JSON serializer; hashes its own sources before and after;
compiles only the small metadata reader; and runs both managed commands inside
a network-denied macOS sandbox. It never adopts a running C-Gate instance or
opens a project, physical endpoint or GUI. Scratch output retains compile and
metadata stdout/stderr, raw decoded metadata, executable and the full report.
A first nested-sandbox attempt failed before compilation; its failure receipt
remains separate from the successful capture.

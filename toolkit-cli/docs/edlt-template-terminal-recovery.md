# eDLT template terminal validation, save and failure boundary

Fresh static inspection of the pinned original assemblies and a 14-case branch
proxy clarify the terminal contract. They do **not** establish a complete
original template load, parent form, native save, cancellation rollback, or
active-control binding flush. The callable template API remains preview-only.

This follow-on starts from `7a23fb5d` and changes no existing lifecycle code.
Evidence is in
[`edlt_template_terminal_evidence.json`](../research/edlt_template_terminal_evidence.json).
It records 27 method tokens/RVAs/IL hashes and six copied-method receipts. The
originals are eDLT.dll `75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3`,
CBusLogicModel.dll `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`,
and SharpContainer.dll `5cba17be19a783e4b0c1e99025c9556fea605b97003ed6a3e9f3f182fb2c3ed0`.

## Apply and OK validate, then dispatch

`FrmBaseUnit.Save(bool)` (`0600030b`, RVA `1afb8`) performs this sequence:

1. `ValidateSerialNumber` at IL `0001`; false returns immediately.
2. Enumerate `unit.Widgets.Where(WidgetType == 6)` and call
   `ValidateSceneWidgetConfig` at `0038`; false returns immediately.
3. Call `EDLTUnit.IsValid(ref errors)` at `004f`. A false result formats the
   collected errors, calls `InvalidFormDialog`, and returns false. `IsValid`
   itself calls both corridor-linking and scene validation before combining
   their Boolean results (`CBusLogicModel` token `0600045f`, RVA `121c0`).
4. Call `SaveDialog(bCloseDialog)` at `00b3` and return true at `00b8–00b9`.

That true value means the validation path reached a void dispatch. It does not
mean a save succeeded. `SaveDialog` (`060002eb`, RVA `19220`) checks for a
subscriber and otherwise returns without work. The proxy confirms a true Save
result when there is no subscriber. `Save` has no exception handler that turns
validator or callback exceptions into false; the proxy confirms propagation.

`btnApply_Click` (`06000319`) calls `Save(false)` and discards its result.
`btnOk_Click` (`0600031e`) normally calls `Save(true)` and discards its result.
Normal OK does not directly call Close after checking successful persistence.
In Global Programming mode, OK instead closes its parent form if one exists,
without calling Save. These distinctions must survive any future adapter.

The subscription runs through
`SharkUnitDialogFactory.FrmKeyUnitSaveUnitDialogRequest` (`060000af`, RVA `3f64`)
to the void `FormSaveUnitEvent`. That wrapper catches subscriber exceptions,
logs/displays them and returns normally. The native host's event recipient and
save-destination dialog are outside this proxy. Consequently even an ordinary
return through this wrapper cannot establish a committed database unit.

## Active-control validation is a separate unresolved boundary

There is no explicit `Validate`, `ValidateChildren`, `EndEdit`, binding
`WriteValue`, or `ActiveControl` access in these Apply/OK/Save method bodies.
Save starts directly with serial validation. Existing
[`edlt-parent-form.md`](edlt-parent-form.md) describes default OnValidation
bindings and an active-control validation step in the interactive save path.
That step must be understood as a UI focus/binding dependency, not an explicit
call recovered inside `Save`.

The proxy invokes handlers directly, so it cannot establish WinForms focus
transfer, cancellation by an active editor's Validating event, or the value
that a default binding would flush before a real click. It also does not
validate inactive controls. A future headless transaction must consume explicit
validated edit values or a proved binding-flush receipt; directly invoking Save
on an uninitialized form does not supply that evidence.

## BeforeSave and persistence are later operations

The managed forwarding method `SharkUnitDialogFactory.SaveUnit` (`06000099`,
RVA `3614`) locates the form and calls
`FrmBaseUnit.SaveUnit(database, physical, saveDlt, false, false)`. The latter
stores save options and starts its progress/worker workflow; its return type is
void. It is distinct from the validation-and-dispatch method above.

`SaveUnitThreadMain` (`060002ef`, RVA `19880`) calls the model's
`CBusBaseUnit.SaveUnit` at `0054`. A false return shows a failure message. An
exception is caught, logged and shown as failure; the outer finally closes
progress. On a true model result with `ShouldAlsoSaveDLt`, it calls
`SaveDlt(true)` and discards that Boolean, then sends the default-language
command. A completed progress window is not an adequate persistence receipt.

`CBusBaseUnit.SaveUnit` (`0600020d`, RVA `6f34`) first calls virtual
`BeforeSavePPData(saveDb, saveNw)` at `0003`, before parameter collection or
`SaveDBUnit`. The eDLT override (`06000468`, RVA `12cf0`) composes Application
from its primary/secondary attributes, calls `SaveStaticText(false)` then
`SaveScenes(false)`, suppresses widget list events, sets MRA globals, adjusts
functional terminators and forced widget values, then reenables list events.
Its database-unit-plus-network-save branch also reads firmware through the
communicator. A future offline preparation must explicitly exclude that branch.

For the ordinary database-only, CRC-enabled, specification-present path,
model normalization precedes `CalculateCRCForPPAttributes` at `0170`, parameter
collection/bitfield completion, then `SaveDBUnit` at `032b`. The returned Boolean
is retained, but `AfterSavePPData` at `061f` still runs on an ordinary false
result. The method has enumerator-disposal finally blocks, not an encompassing
rollback transaction. Exceptions after any eager normalization or persistence
call leave their earlier effects outside those finally blocks. Physical and
combined save branches require separate evidence; this research performs none.

## Load failure and cancellation do not provide rollback

`TemplatesDialog.BtnLoadClick` (`060001e7`, RVA `f368`) discards the result of
`ResetUnit(true)` before rebuilding and assigning. A second failure is present
inside `ResetUnit` (`060002e8`, RVA `19004`): its local result starts true; when
`ResetToDefaults` returns false at `006e`, silent mode jumps from `0097` to
`00af`, skipping the false assignment at `00ad`. It continues clearing widget
byte 1, runs `AfterChangePpAttributes`, rewrites the unique widget number 10 to type 10
with byte 1 `0x2`, and can return true. A missing UnitSpec returns false earlier
at `0060–0061`, but the template loader also ignores that result. These are
static findings, not runtime Reset acceptance.

During the template's ordered assignment loop, `bInitialiseMode=true` is set
at `0310`. Setter/changed-flag exceptions skip its reset at `034f`, while earlier
assignments remain. The loop's finally only disposes its enumerator. The outer
catch displays failure; its finally only shows the temporarily hidden control.
There is no restoration of raw values, dirty flags, graph, initialization flag
or earlier project/cache side effects in this handler. A failure before
`AfterChangePpAttributes` also leaves that rebind phase unexecuted.

The template dialog's Close button has DialogResult.Cancel. The caller ignores
ShowDialog's result; no template rollback is wired to Close. The parent Cancel
handler (`0600031a`) calls `OnFormClosed(null)`. The inspected close methods
clear bindings, dispose controls/panels, send the form-closed event, and clear
the panel list. They contain no PP restoration, model reload or save. External
closed-event subscribers were not executed; there is no proven promise that
closing restores the pre-template in-memory model or its external side effects.

## Required future safe stage contract

A safe implementation should make these deliberate differences explicit:

1. Before reset, bind a stage to one immutable source snapshot, identity,
   ordered raw PP collection and complete model/cache graph. Own the graph and
   process-level initialize/list-event flags, including their entry values.
2. Run reset, reconstruction and ordered assignments on an isolated stage.
   Require reset postconditions as well as its return value; the original
   silent Boolean can mask failure. Preserve repeated child assignment order.
3. On reset, setter or rebind failure, restore flags in a finally and discard
   the whole unpublished stage. Any external project/cache mutation needs its
   own journal and verified compensation; restoring PP strings alone is not
   graph rollback. Refuse staging if that isolation cannot be established.
4. Validate explicit control edits and the serial/scene/model gates before
   terminal normalization. Run the retained BeforeSave/model serialization and
   CRC preparation once over that stage, with an explicit database-only scope.
5. Publish only after successful full validation. Until persistence begins,
   cancellation must discard the stage without changing the original model.
   Report stage-ready separately from save-request-dispatched.
6. At persistence, verify a fresh source guard and use one explicit commit
   boundary with a correlated result and fresh readback. After an uncertain
   save, retain evidence and forbid automatic replay or claimed rollback.
   Distinguish PP persistence from project-file durability and DLT label work.

These requirements are a proposed safe contract. Neither the proxy nor this
document enables template apply. Full reset/rebind state fidelity, active-control
binding behavior, native host save routing and accepted failure recovery remain
blockers for an original-equivalent complete workflow.

## Reproduction and limits

[`edlt_template_terminal_original.py`](../research/edlt_template_terminal_original.py)
compiles the small owned
[`edlt_template_terminal_probe.cs`](../research/edlt_template_terminal_probe.cs)
with pinned Mono 6.12 and Cecil 0.11.1. Cecil reads the original files as metadata.
It copies the six selected methods' opcodes, branches, locals and exception
regions into a new owned assembly, rebinding model/UI dependencies to recording
stubs. Framework LINQ, collections and string formatting execute normally.
The generated assembly admits only framework/Cecil/owned runtime dependencies;
the runner verifies actual loaded paths and hashes. Vendor input files are
hashed before and after. Every compiler/metadata/proxy subprocess denies network.

```sh
python research/edlt_template_terminal_original.py \
  --app-root /path/to/original/toolkit/app \
  --mono-root /path/to/owned/Mono/6.12.0 \
  --output /tmp/new-edlt-terminal-run \
  --verify-evidence research/edlt_template_terminal_evidence.json
```

All 14 explicit cases passed: the three rejected validation gates, accepted
dispatch with/without subscriber, Apply/OK requests, both global-OK branches,
Cancel routing, and exceptions in serial, scene, model and callback stages.
The scene filter selected only the two type-6 synthetic widgets. No original
validator, form, control binding, model save, native C-Gate project, or physical
device executed. The proxy confirms terminal branch composition only; it is
not a fresh original full-form acceptance fixture. Generated executables and
local disassembly stay outside the repository.

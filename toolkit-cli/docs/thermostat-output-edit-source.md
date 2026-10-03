# Thermostat output Edit source evidence

The ordered output history supports an accepted Edit dialog or a direct
cancellation for the group currently selected by an enabled output, damper or
internal-relay control. Edit changes the existing object's TagName. It retains
the object's address, OID, references, Levels and other metadata. It composes
with ordinary load, selection and Add in the existing settings owner.

The source is Toolkit 1.18.0.2754. The EXE SHA-256 is
`9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`; the MAP SHA-256 is
`f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`.
The [sanitized receipt](../research/fixtures/thermostat-output-edit-source-review.json)
records 337 checks: 211 inherited Add checks and 126 Edit checks. It binds 138
method spans, five DFM resources, 23 thermostat selectors and a 70-method Edit
hook scan. The [Add annex](thermostat-output-add-source.md) supplies the shared
name validation, controller preparation, Project.TagName and wire formatter
evidence. Neither receipt contains original instruction bytes, full disassembly,
decoded unit specifications or private file coordinates.

Reproduce the receipt with explicit local inputs:

```sh
.venv/bin/python research/thermostat_output_edit_static.py \
  --exe "$TOOLKIT_EXE" --map "$TOOLKIT_MAP"
```

This reads, hashes, decodes and checks bytes. It does not execute original
instructions, a Windows form, a vendor service or physical I/O. The optional
source test reports a skip when those inputs are absent.

## Ordered accepted and cancelled outcomes

```json
[
  {"op":"edit-output-group","parameter":"HeatStage1Output","outcome":"accept","name":"Bedroom  heat"},
  {"op":"edit-output-group","parameter":"HeatStage1Output","outcome":"accept"},
  {"op":"edit-output-group","parameter":"CoolStage1Output","outcome":"cancel"}
]
```

The target is the control's current group identity at that position in the
history. Accepted Edit permits an optional final name; it has no address input.
Cancellation permits no name and does not invoke OK validation. A later
selection of a different group retains the earlier accepted rename. An Add
followed by Edit operates on the newly created identity in the same evolving
inventory.

`TFlashCxGroupComboBox.DoButtonEditClick` spans `0xbc5d90..0xbc5f2c`. It gets the
bound application at `0xbc5dbd`, sets GroupAssign's new-object flag to false at
`0xbc5e16`, reads the currently selected group at `0xbc5e6f`, and binds that same
object into the dialog at `0xbc5e7d`. It calls `SetValues` at `0xbc5e8c` and the
modal form at `0xbc5ebe`. Unlike Add, it does not create an object or assign a
different reference. Both modal outcomes then refresh the list and invoke
`DoIndexChange` at `0xbc5ec7` and `0xbc5ecf`, without a modal-result comparison
between the modal call and refresh.

`SetValues` (`0xbc356c`) hides the editable address control in the Edit branch
at `0xbc38ad..0xbc38b8` and displays the existing address at
`0xbc38e0..0xbc38fb`. In `actOKExecute` (`0xbc2dc4`), Edit reads that existing
address at `0xbc2dff` and skips the address-selector path at `0xbc2e07`. It also
skips the new-address collision test at `0xbc2f0b`. Capacity exhaustion is not an
Edit refusal.

## Names, including an omitted over-limit name

An explicit entered name is bounded to 32 UTF-16 code units before source Trim.
This is the typed final-text profile, not an arbitrary keystroke history. Source
Trim removes only leading and trailing units at or below `0x20`. OK refuses an
empty result, exact equality with the containing Project.TagName, or another
group with the same ASCII-uppercase name. The duplicate lookup at `0xbc2f6c`
receives the edited object as its excluded identity (`0xbc2f57`). Reusing the
current name is therefore allowed unless another identity conflicts. The
comparison converts only ASCII `a`–`z`; Python `strip`, `upper` and `casefold`
would change the rules. NBSP is preserved, and `é` and `É` remain distinct.

An omitted name preserves the **full programmatically preloaded TagName**, even
when it exceeds 32 UTF-16 units. `SetValues` reads the existing TagName at
`0xbc35ee..0xbc35f6` and calls `TControl.SetText` at `0xbc3605`. `SetText`
(`0x6f62d8`) passes the whole Unicode string through `SetTextBuf` (`0x6f56d0`),
which sends `WM_SETTEXT` (`0x0c`). The no-window default handler copies the whole
string with `StrNew` at `0x6f7b11`; the window-backed handler dispatches through
`CallWindowProc` at `0x6fc330`. `GetText` (`0x6f62a0`) later allocates using the
actual `WM_GETTEXTLENGTH` result and retrieves the whole text. No source clipping
or MaxLength check appears along this preload/readback path or in OK.

`TCustomEdit.DoSetMaxLength` (`0x6852f0`) instead sends `EM_LIMITTEXT` (`0x00c5`).
Microsoft documents that this limits user entry while leaving existing text and
text copied by `WM_SETTEXT` unaffected. The omitted-name behavior follows from
those pinned source calls composed with the documented Windows contract; it is
not a newly executed Windows acceptance result. [Microsoft EM_LIMITTEXT
documentation](https://learn.microsoft.com/en-us/windows/win32/controls/em-limittext).

Accepted omitted names still undergo Trim and every OK-only validation. They
must also fit the product's command framing and XML representation. Direct
cancellation neither validates the loaded name nor consumes Project.TagName.
The explicit-input length rule must not silently truncate the omitted branch.
The source's empty `TCGateObject.TagNameBeforeChange` (`0xf48228..0xf4823c`)
does not add another name validator.

## Exact storage overload and existing-object dispatch

After validation, OK assigns the same model Address at `0xbc2f85`, trims the
TagName again at `0xbc2fa1`, assigns it at `0xbc2fc5`, and invokes storage save
for Edit at `0xbc2ff7`. This call uses the group VMT slot `+ 0x80`: the class
reference at `0xf23cd4` points to VMT `0xf23d2c`, whose slot at `0xf23dac`
resolves to **`TPersistableObject.StorageSave` at `0x7f409c`**. The similarly
named overload at `0x7f405c` is not this call target.

The selected overload spans `0x7f409c..0x7f4160`. It obtains the agent at
`0x7f40f8` and invokes agent VMT `+ 0x88` at `0x7f4119`. The group-agent class
reference `0x1210ae8` points to VMT `0x1210b40`; its slot `0x1210bc8` resolves
to `TCBusGroupCGateAgent.AgentSave` at `0x1210d28`. For an existing nonblank
OID, the branch at `0x1210d69` bypasses `CreateGroup`. Inherited AgentSave at
`0xcac354` calls `UpdateTag` (`0xcac614`) through `0xcac37e`. It writes the
TagName through the existing `!OID` and the original quoted `DBSET` command.
It does not write the unchanged Address to storage. GroupAgent then requests
Project.Save at `0x1210ded`.

The inherited formatter escapes backslash and double quote. If the escaped text
contains adjacent ASCII spaces, it escapes **every** ASCII space, then quotes
the whole value. Other UTF-16 units, including NBSP, remain unchanged. This
source path cannot be replaced with a plain whitespace-normalizing command
tail or a silently rewritten name.

An accepted same-name Edit still reaches original StorageSave and Project.Save.
The owned transaction may omit a redundant unchanged TagName write; that is an
explicit storage projection, not a claim to reproduce the original save call
count. Likewise, complete preflight and one final owning settings/project save
do not replay the original per-object saves or partial failure prefixes. An
uncertain write is not retried. The source's exception handler and eventual
modal result are not authority to report an unverified owned write as successful.

## Active controls, optional hooks and refresh boundaries

Each operation retains the ordinary loaded role's visibility and enabled gates.
The Edit portion of `UpdateEnableState` (`0xbc54fc`) additionally requires a
bound application, active controller, nonnil `TCBusGroup` and a group for which
`IsUnused` is false (`0xbc561a..0xbc56e7`). `TCBusGroup.IsUnused` at `0xf27e14`
compares the address with 255 at `0xf27e25`. Edit does not require Add capacity or
`GetCanAddGroups`. The source's action-button mask exposes Add and Edit; generic
Delete/Clear methods do not establish a thermostat Delete workflow.

The generic Edit handler (`0xbbe3f0`) permits optional before/after hooks at
fields `0x550` and `0x570`. The receipt resolves their published properties,
checks all 23 selectors in four thermostat DFMs, and scans 70 methods: 67 panel
methods plus three combo constructors. There are no direct assignments to the
Edit method/data slots `0x550`, `0x554`, `0x570` or `0x574` in that scope.
Combined with fresh zero-filled construction and prepared controllers, this
supports the admitted ordinary controls. It is not a whole-program claim about
arbitrary external event injection.

Refreshing the combo posts the existing `0x426` rendering notification. A
TagName change can also trigger the manager's sort notification:
`HandleTagNameAfterChange` (`0xf47b04`) checks sort style 3, enables a 1 ms timer
through `0xf487e0`, and the timer handler (`0xf48708`) calls `DoFullSort` at
`0xf4875b`. The bounded workflow preserves numeric identities and uses numeric
first-free Add and duplicate-existence Edit checks. It does not infer manager
order from XML, emulate timers or claim the Windows message loop ran.

Full GUI state, arbitrary text-entry histories, application migration, generic
Delete/Clear, original service interoperability and physical programming remain
outside this source-backed storage workflow.

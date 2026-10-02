# eDLT SceneManager Add dialogs

KEYGL5 / 5055EDL firmware 5.5.00 supports pure planning and guarded database
application of accepted or cancelled Trigger Group and Action Selector Add
outcomes. Supply these ordered operations to existing `edlt
scene-manager-plan`, `edlt scene-manager-state`, or `cgate unit
edlt-scene-manager --auto-metadata` commands:

```json
[
  {"op":"add-trigger-dialog","scene":1,"name":"Evening"},
  {"op":"add-action-dialog","scene":1,"name":"Off"},
  {"op":"add-action-dialog","scene":2,"cancel":true}
]
```

Each operation requires `scene` 1..8. Optional `address` selects a free 0..254
address, optional `name` replaces the seeded text, and `cancel:true` records a
cancelled outcome without adding the provisional object or changing its
binding. Omit `cancel` or use false to accept. Application Add remains refused:
the retained original maximum depends on the low byte of the hosting form
pointer, so a deterministic candidate range is not established. Corridor Add
and the separate Activation Action Add are outside this addition.

Use `--project-xml` and an exact `--unit` for offline commands. A supplied
manual cache cannot authorize object creation. Parent transactions may put
these rows inside their single `scene-manager` operation; the existing parent
transaction still stages the complete graph and performs one terminal PP save.

Action Add requires that scene to have a non-255 Trigger Group, including one
accepted earlier in the same operation list. It does not read the Action Selector
getter before allocating the new Level.

The plan exposes `automatic_metadata.add_dialogs`, `requested_operations`,
`resolved_operations` and `planned_creations`. Accepted outcomes lower to
ordinary `set-trigger`/`set-action` edits. Requested dialog rows remain bound to
the issued native plan and are replayed when checking stale metadata, so a newly
occupied address or changed name prevents mutation. Cancelled rows remain in
the dialog receipts even though they produce no editor operation. Cancel does
not cancel other operations or the existing load/save getter side effects.

Both allocators choose the first missing address 0..254; 255 is reserved. Trigger
Group seeds `Trigger Group N`; Action Selector seeds `Level N`, with its stored
Address and Value equal to the accepted address. Existing exact-address getters
retain their distinct `Group N` and `Action Selector N` names and may create
Action 255. Allocation observes initial getter-created objects and earlier
ordered operations. Creation uses dependency order with first creation order
within each kind for dialog-bearing histories. Existing exact-only histories
retain their address order.

The retained Level form uses the Action Selector noun when rewriting a
noun-prefixed name after an address change. Consequently, an untouched `Level N`
seed stays unchanged if the operator selects a different address. A second Add
can seed the same name if the earlier dialog selected another address; that
second dialog must supply a distinct name or it fails duplicate validation.

Trigger Group validation trims the proposed name before duplicate comparison.
Level Add checks the entered name using ASCII case-insensitive comparison,
then trims the stored name. Thus `Evening` conflicts with `EVENING`, while
` Evening ` can be accepted and stored as `Evening` alongside it. This original
quirk is preserved rather than replaced by a stronger uniqueness policy.
Trim-empty Level names report 2211, duplicate entered names 2212 and a trimmed
name equal to the Project TagName 2213. Accepted names additionally pass the
existing native metadata transport fence: 1..128 trimmed Unicode characters
without ASCII control characters or DEL, and valid UTF-8 encoding. Dialog-bearing plans require an explicit Project TagName scalar from XML for
that comparison; the command Address remains separate. They refuse literal
`#`, repeated internal spaces, non-ASCII whitespace, and U+FFFE/U+FFFF before
backup or mutation because these cannot survive the current database transport
or XML 1.0 readback exactly. Ordinary and astral Unicode are admitted. These
are explicit software input bounds, not recovered original refusal rules. The
older separate parent ComboBox Add path still compares the project Address,
which is outside this SceneManager correction. The complete source inventory supplies duplicate
and address checks; no partial cache is guessed.

Native apply requires the exact database Unit source, its network lock,
closed/idle project networks and caller-declared exclusive project use. The
existing transaction saves/copies the source backup before creation, initializes
new Levels by issued OID, verifies all existing and created metadata in the admitted project XML schema, stages PP,
attempts one PP SAVE when needed, and saves/closes/loads the project. Connected
failure before the first persistence save reverses known created objects or
reloads the pre-creation source after an ambiguous creation. Once PP SAVE or the
target PROJECT SAVE has been attempted, an uncertain result is retained with
no retry or rollback. These separate commands are not a server-wide atomic
transaction.

[Source evidence](../research/fixtures/edlt-scene-add-dialog-evidence.json)
pins the original EXE/MAP and method ranges. The exact pure rules are in
[`edlt_scene_add_dialog.json`](../../rust/testdata/vectors/edlt_scene_add_dialog.json).
This is composed static/model software support. No original instructions,
Windows dialog, physical display or C-Bus programming were executed for this
addition. Full original parent event history and physical acceptance remain
open under issues 45/48/50.

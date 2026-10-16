# Thermostat output Edit controls

`thermostat settings preview|apply` supports accepted and directly cancelled
Edit outcomes for the ordinary output selectors on PC_TSA, PC_TSA5, PC_TSB and
PC_TSB5. Use repeatable `--output-operation JSON` records, mixed with the
[Select and Add controls](thermostat-output-add.md) in command-line order.
The same decoded specification and loaded control eligibility apply.

```sh
cbus-toolkit thermostat settings preview //HOME/254/p/4 \
  --output-group HeatStage1Output=12 \
  --output-operation '{"op":"edit-output-group","parameter":"HeatStage1Output","outcome":"accept","name":"Study heat"}' \
  --output-operation '{"op":"edit-output-group","parameter":"HeatStage2Output","outcome":"cancel"}' \
  --spec-dir /path/to/decoded/specifications \
  --host 127.0.0.1 --port 20023 --exclusive-project
```

This selects an existing group before renaming it and then cancels another
Edit. Review the preview, including all ordinary-load effects, before using
`apply` with a new `--backup-project`. Preview does not mutate or save.

## Records and names

| Outcome | Required fields | Optional fields |
| --- | --- | --- |
| Accept Edit | `op: "edit-output-group"`, `parameter`, `outcome: "accept"` | `name` |
| Directly cancel Edit | `op: "edit-output-group"`, `parameter`, `outcome: "cancel"` | None |

Edit binds the object currently selected by that control after all preceding
load, Select, Add and Edit actions. Its address and immutable identity cannot
be edited. A missing selected group, unused address 255 or an ineligible
loaded control is refused. Edit cancellation permits no name/address field,
creates nothing and does not run OK-name validation. Other transaction effects
can still require a save.

For acceptance, an explicit `name` must fit 32 UTF-16 code units before source
trimming. Omission uses the complete programmatically loaded TagName, including
a pre-existing name longer than 32 units. Source Trim removes only edge
characters at or below U+0020. The result must be nonempty, differ exactly from
one scalar `Project.TagName`, and be unique among other groups in the bound
application under ASCII-only uppercase comparison. The selected identity is
excluded from that duplicate-name check. Unicode case pairs and NBSP retain
their original distinction; line-protocol and XML character limits still apply.

Accepted Edit of an unchanged valid name is an explicit owned no-op. This does
not reproduce a redundant original storage callback. A changed shared identity
is visible to all later actions and to every role that references it. Selecting
another group afterward retains the earlier rename; Edit never deletes a group.

## Transaction and receipts

Inspect `output_projection.operations`, `output_projection.edit_dialogs` and
ordered `graph_operations`. Each Edit receipt records its position, selected
identity/address, preceding and shown name, optional operator entry, accepted
name, and whether it changed. Rename operations carry `output_edit: true`.

The owner validates the complete immutable plan, PP/project snapshot and
preceding identity/name before backup or mutation. A changed Edit sends one
source-quoted `DBSET !OID/TagName` at its causal position, preserving Unicode,
NBSP, doubled spaces, quotes and backslashes. It is followed by complete graph
verification. Existing Level Value spelling and absence remain opaque metadata;
new Level creation keeps its strict canonical-byte validation.

All reviewed load, Select, Add, Edit and optional-Level actions share one
settings save owner. PP changes use at most one `PP SAVE_TO_SOURCE`; a graph-only
change uses none. A changed transaction makes one final target `PROJECT SAVE`
and verifies close/reload, with the backup source save counted separately.
Unrelated project and PP fields must remain intact. A complete no-op does not
back up or save.

A lost rename or save reply stops execution with persistence unconfirmed.
The owner sends no retry, inverse rename or later save. Inspect retained
receipts and actual state before preparing a fresh plan.

## Evidence and remaining scope

The source-only [static receipt](../research/fixtures/thermostat-output-edit-source-review.json)
pins the wrapper, name dialog and controller/storage bindings. Scripted adapter
and synthetic Rust-backend tests are separate from original WinForms or
Schneider native-server execution. Current release outcomes are recorded in
[implementation status](implementation-status.md).

Complete original manager sorting/message callbacks, inherited loaders,
arbitrary edit-control keystrokes, full dialog visibility/lifecycle, Delete,
application-change controls and physical thermostats remain outstanding.
Existing default-name admission outside the declared ordinary-load profile is
not widened by Edit. Full Toolkit parity remains unproven.

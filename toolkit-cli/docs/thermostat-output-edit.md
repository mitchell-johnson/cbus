# Thermostat output Edit controls

`thermostat settings preview|apply` supports accepted and directly cancelled
Edit dialogs for the existing cooling, heating, damper and internal-relay
selectors. Edit changes the name of the **currently selected group** while
preserving its address, identity and reference assignments. It uses the same
PC_TSA, PC_TSA5, PC_TSB and PC_TSB5 profiles and loaded control gates as
[ordinary output controls](thermostat-settings.md#output-group-controls).

Pass ordered `--output-operation` JSON records. Existing `--output-group`
selections and [Add operations](thermostat-output-add.md) can appear between
them; command-line order determines which object each Edit targets.

```sh
cbus-toolkit thermostat settings preview //HOME/254/p/4 \
  --output-group HeatStage1Output=12 \
  --output-operation '{"op":"edit-output-group","parameter":"HeatStage1Output","outcome":"accept","name":"Study  heat"}' \
  --output-operation '{"op":"edit-output-group","parameter":"HeatStage1Output","outcome":"cancel"}' \
  --spec-dir /path/to/decoded/specifications \
  --host 127.0.0.1 --port 20023 --exclusive-project
```

This selects existing group 12, renames it to `Study  heat` with both spaces
preserved, then directly cancels another Edit. Preview reads project and PP
state without writes. Review it before using the same history with `apply`
and a new `--backup-project` name. The settings command requires a closed
database network and exclusive project ownership; it does not program a
physical thermostat.

## Records and selected identity

| Outcome | Required fields | Optional fields |
| --- | --- | --- |
| Accept Edit | `op: "edit-output-group"`, `parameter`, `outcome: "accept"` | `name` |
| Directly cancel Edit | `op: "edit-output-group"`, `parameter`, `outcome: "cancel"` | None |

Use an exact output field from the settings document. There is no Edit
`address` field: the original dialog displays the current address as a label.
Unknown fields, invalid outcomes, duplicate JSON keys, nonobject records and
histories longer than 256 operations are refused.

The target must be a non-unused object selected at that point in the history.
Edit of address 255 is disabled, including cancellation. The original loaded
visibility and enable rules still apply: basic units have no damper dialog;
internal relays require PC_TSA5/PC_TSB5 and a loaded master; plant state gates
cooling, heating and damper controls. An application with all 256 addresses
occupied can still Edit. It does not need Add capacity.

Edit after Add targets the new identity. Edit followed by selecting another
group retains the earlier rename. When several output, relay or remote roles
share an object, its new name is visible through every role; their addresses
remain unchanged. Other applications may use the same numeric address and
retain their own objects and names.

## Name entry and omitted names

An explicitly supplied `name` must be text containing at most 32 UTF-16 code
units **before trimming**. Sixteen supplementary characters use all 32 units;
adding one trailing space exceeds the limit. Excess input is refused rather
than silently truncated.

Omitting `name` accepts the complete name preloaded from the currently
selected object, including a name longer than 32 UTF-16 units. The original
dialog loads text programmatically; its entry-length limit does not truncate
that preload. Both explicit and omitted accepted names then undergo the same
source Trim, nonblank, project-name and duplicate checks. An omitted name
with leading or trailing ASCII whitespace can therefore cause a rename.

Source Trim removes edge characters at or below U+0020. NBSP is retained,
including an NBSP-only name. The result must be nonempty and differ exactly
from the containing scalar `Project.TagName`. Duplicate detection compares
names in the current application using ASCII-only uppercase and excludes
only the edited object's identity. A group may retain its current name if no
other object has that name under this comparison; `é` and `É` remain distinct.
Project-name comparison is case-sensitive.

The name inventory evolves after every operation. To swap two group names,
rename the first to a temporary unique name, rename the second, then rename
the first again. Earlier renames and creations stay in the ordered graph
ledger, including a sequence that returns a name to its original value.

Direct cancellation admits no name input, does not consume `Project.TagName`
and does not run OK validation. Existing duplicate, blank or long preloaded
names therefore do not prevent cancellation. It still requires an enabled
Edit control and a selected non-unused group. Other ordinary-load effects or
operations may require a save even when this Edit is cancelled.

After source validation, the native adapter admits representable XML text
without remaining line/control characters. It preserves Unicode, NBSP,
quotes, backslashes and repeated spaces. This command/XML restriction is a
product boundary, separate from the original dialog's name rules.

## Preview, storage and preservation

Inspect `output_projection.operations` and `edit_dialogs`. Each Edit receipt
includes its history position, selected address and identity, previous/shown
name, whether a name was explicitly supplied, entered name, accepted name,
outcome and changed flag. Cancellation has no entered text and retains the
current name. `planned_renames` and `graph_operations` mark explicit Edit
renames with `output_edit: true`; ordinary load renames retain their previous
metadata shape.

The complete ordinary graph load still precedes this history. Native apply
replays the immutable plan and checks full graph/PP freshness before mutation.
Each explicit Edit checks the owning OID and preceding name, then issues one
quoted `DBSET !groupOID/TagName`. The source encoder escapes quotes and
backslashes, escapes every ASCII space when a double space is present, and
quotes the entire value. It does not create, readdress or delete the group.

All graph edits and accepted optional remote levels share the existing
settings owner. If PP values change, it stages them together and performs one
PP save. A graph-only rename requires no PP save. Both mutation paths perform
one final target project save and independent reload/readback; the backup's
source save is reported separately. Full preservation checks retain OIDs,
addresses, TagName attributes, unrelated PP values, descriptions, levels, DLT
data and opaque metadata.

An accepted same-name Edit validates normally but produces no rename. If
nothing else changes, the owned transaction performs no writes or saves.
The original accepted Edit still calls storage save for that case: avoiding
its redundant save is an explicit owned transaction projection, **not** a
claim that original storage callbacks were replayed. Intermediate renames
remain mutations even if the final tag equals the original tag.

After a failure, inspect the attempted/confirmed rename evidence and
`outcome_uncertain`. A missing terminal reply can follow a successful native
write. The command does not automatically retry, delete the object, restore
its name or continue to later graph/PP/project writes.

## Evidence boundary

The [source review](thermostat-output-edit-source.md) pins the selected-object
wrapper, fixed-address Edit mode, validation, save dispatch, control gates,
optional-hook absence and full-text preload. Original tag changes can queue
a manager sort timer; the numeric Select/Add/Edit projection does not infer
native list ordering or run that message loop. Receipts keep
`original_edit_storage_callbacks_reproduced`,
`original_manager_sort_timers_reproduced` and
`complete_form_lifecycle_reproduced` false.

Pure, scripted-native and owned-backend tests establish separate parts of
this bounded workflow. Pure preservation cases cover opaque Group and
TagName attributes. The owned backends reject those unknown attributes during
provisioning; their cases instead preserve admitted project/network metadata,
existing levels and DLT data through save and reopen. These tests do not
execute the Windows application or provide
original native C-Gate or hardware acceptance, which remains deferred under
issue #72. Application changes, ordered zone histories, other parent controls
and full thermostat parity remain open under issue #42. The generic combo's
Delete/Clear methods do not establish visible thermostat controls: this
profile's recovered action mask exposes Add and Edit.

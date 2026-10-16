# Thermostat output Add controls

`thermostat settings preview|apply` supports accepted Add dialogs and direct
cancellation for the existing cooling, heating, damper and internal-relay
selectors. Use repeatable `--output-operation JSON` records, optionally mixed
with `--output-group PARAMETER=ADDRESS`. Their command-line order is retained.
The admitted unit types are PC_TSA, PC_TSA5, PC_TSB and PC_TSB5, with the same
decoded specification and loaded control gates as
[ordinary output selections](thermostat-settings.md#output-group-controls).

```sh
cbus-toolkit thermostat settings preview //HOME/254/p/4 \
  --output-operation '{"op":"add-output-group","parameter":"HeatStage1Output","outcome":"accept","address":12,"name":"Study heat"}' \
  --output-group HeatStage1Output=255 \
  --output-operation '{"op":"add-output-group","parameter":"HeatStage2Output","outcome":"cancel"}' \
  --spec-dir /path/to/decoded/specifications \
  --host 127.0.0.1 --port 20023 --exclusive-project
```

This history creates and initially selects group 12, selects the existing
unused group afterward, then cancels a second Add. The created group remains
in the plan. Review the preview before using the same history with `apply`
and `--backup-project` naming a new backup. Preview reads the project and PP
snapshot but does not create groups or save.

## Operation records

Each `--output-operation` value is one JSON object. Duplicate keys, nonfinite
numbers and nonobject input are refused. The exact parameter names are the
23 existing output fields listed in the settings document.

| Operation | Required fields | Optional fields |
| --- | --- | --- |
| Select existing group | `op: "select-output-group"`, `parameter`, `address` | None |
| Accept Add | `op: "add-output-group"`, `parameter`, `outcome: "accept"` | `address`, `name` |
| Directly cancel Add | `op: "add-output-group"`, `parameter`, `outcome: "cancel"` | None |

A selection admits an integer byte or the same integer-string syntax as
`--output-group`. An Add address must be a JSON integer in 0–254, currently
free in the bound output application. Booleans, strings and fractional values
are not Add addresses. Every selected or accepted address must also fit the
decoded parameter, including an intermediate choice that is later replaced.
Existing address 255 can be selected; Add cannot allocate it.

Omitting the Add address uses the first numerically free address, starting at
zero. This consumes the inventory after ordinary loading and all earlier
accepted Adds. It does not use XML enumeration order or a template allocator.
An exhausted inventory prevents opening Add, including direct cancellation.
Each history is limited to 256 operations.

The provisional name is `Group N` for admitted Lighting applications 48–95 or
`Enable Network Variable N` for application 203. An explicit address changes
this default name to follow that address. An explicit final `name` follows the
address selection and overrides the default. This canonical input order models
a dialog outcome, not arbitrary edit-control keystrokes.

Cancellation accepts no address or name edits and does not run OK validation.
It records the provisional first-free address and seed, but adds no object and
does not change the selected reference. A colliding provisional name therefore
does not prevent cancellation. Ordinary load effects and other operations still
belong to the transaction and can require a save.

## Names and validation

Accepted name text must fit 32 UTF-16 code units **before trimming**. Sixteen
supplementary characters use all 32 units. Excess text is refused rather than
silently truncated. The source trims only leading and trailing characters at
or below U+0020; NBSP and other Unicode whitespace are retained.

The trimmed name must be nonempty, differ exactly from the containing
`Project.TagName`, and be unique among the current application's groups under
the original ASCII-only uppercase comparison. Project-name equality is case
sensitive; group-name equality changes only ASCII `a`–`z`. Thus `é` and `É`
remain distinct. The source does not impose a blanket reserved-label rule,
although a label such as `<Unused>` can collide with an existing group.

Accepted Add requires one explicit scalar `Project.TagName` in the bound
project snapshot. Project Address is not a substitute. Cancellation and
selection-only histories do not consume that field. Unpaired surrogates,
remaining line/control characters and text outside XML's character domain
are refused before mutation as command/XML limits. Trimmed edge whitespace
is permitted. These transport limits are separate from the original dialog
rules.

Every Add uses the selected control's loaded eligibility. The new identity
cannot collide with a currently selected fan peer, but later selections still
apply fan exclusions at each step. Final cooling, heating and damper identity
validation remains separate. Cross-collection sharing is allowed; relays have
no uniqueness requirement. A programmable slave can select a newly added
damper group while its saved damper byte remains 255. Other inherited settings
normalization may still change PP values in that transaction.

## One graph and one save owner

The complete ordinary load precedes this history: application 172/ZoneGroup,
selected ApplicationNumber, setback references, fourteen outputs, four dampers,
five relays and programmable schedule references. Existing selection flags
retain their earlier behavior. `--resolve-output-groups` still requests
load-only resolution; omitting all output flags retains the bounded remote-only
profile. Raw `--set` edits occur before loading. Output fields are edited by
the explicit controls rather than raw `--set`.

Inspect `remote_references.output_operations`,
`output_projection.operations`, `output_projection.add_dialogs`,
`planned_creations` and ordered `graph_operations`. Add receipts include the
position, provisional seed, first-free address, final accepted name/address,
previous and selected identities, and whether an object was created. The
`output_add: true` creation marker distinguishes accepted dialogs from ordinary
getter creations. Later reassignment does not delete an earlier Add.

The owner replays the immutable plan and checks complete PP/project freshness
before backup or graph writes. Accepted Add follows the recovered storage
sequence: `DBADD !applicationOID Group`, then `DBSET !newOID/Address`, then
`DBSET !newOID/TagName`. Fresh parent and new-object OID checks surround these
steps. The name encoder escapes quotes and backslashes, escapes every ASCII
space when two consecutive spaces occur, and quotes the whole value. Unicode,
NBSP and repeated spaces are retained exactly. The semantic object is a
`Group` even in application 203; exported Group/NetVar shape is verified
separately.

All reviewed creations, renames and optional remote levels share the existing
settings transaction. Parameter changes use one `PP SAVE_TO_SOURCE`; changes
confined to the graph use none. A changed transaction uses one final target
`PROJECT SAVE` and close/reload verification, with the backup source save
counted separately. Complete graph and unrelated PP preservation remain
required. A no-op does not save.

An uncertain creation, Address/TagName write or save stops the transaction.
It is not retried, deleted or followed by later writes. Inspect the retained
operation receipts and actual project state before making a fresh plan.
Complete preflight deliberately precedes mutation; this does not reproduce
the original form's partial effects before a later validation error.

The Python owner accepts `output_operations=[...]` in
`NativeThermostatSettings.plan`. The pure `plan_remote_references` accepts the
same records. `output_operations` and the existing `output_selections` are
mutually exclusive; an empty sequence requests ordinary resolution. CLI flags
can be mixed because the CLI converts their order into one operation history.

## Evidence boundary

The [source annex](thermostat-output-add-source.md) and sanitized static receipt
pin the direct Delphi wrapper, address/name rules, controller bindings,
assignment and native name encoding. Static inspection reads the retained
EXE/MAP as data and executes no original instructions.

Pure tests exercise literal control histories and replay/preservation guards.
Native-adapter tests use owned scripted clients; the public backend tests use
the maintained Rust servers and synthetic closed projects. These are distinct
from original Windows-form or Schneider native-server execution. The focused
test modules are `test_thermostat_output_add.py`,
`test_thermostat_output_add_native.py` and
`test_thermostat_output_add_backends.py`; release outcomes are recorded only
after their frozen validation run.

Original native and hardware acceptance remain deferred under issue #72.
Output Edit/Delete actions, application changes, ordered zone histories and
complete initialized GUI/message behavior remain open. Thermostat feature
parity remains `in_progress` under issue #42.

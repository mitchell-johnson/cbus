# IOPE Logic and logic recovery

`cbus_toolkit.iope_logic.IopeLogic` implements the bounded original Toolkit
Logic tab followed, when requested, by its logic recovery modal. It stages PP
changes, verifies readback and restores attempted writes on failure. It does
not save, contact physical equipment or execute the original Windows GUI.

The exact matching specification and explicit `(unit_type, firmware,
catalog_number)` identity are required. Firmware admission is **1.0.00 through
1.2.99**, the existing source/catalogue intersection. A supplied catalogue must
match; `None` means unknown. Native acceptance applies only to revisions in its
separate receipt, not automatically to every admitted revision.

| Type | Catalogue | Active outputs | Logic rows |
| --- | --- | --- | --- |
| IOPE1R1 | 5752PP/1R | 1 | 4 |
| IOPE2R2 | 5752PP/2R | 2 | 4 |
| IOPE2C4 | 5752PP/2R/2D | 4 | 4 |

## Controls and event order

| API control | Domain | Stored field |
| --- | --- | --- |
| `channels[n].logic_groups` | Distinct list of rows 1..4; empty clears associations | `LogicGA13Associations` through `LogicGA16Associations`, index n−1, bits 0..3 of 0x70..0x73 |
| `channels[n].logic_function` | `and` or `or` | `LogicFunction[n−1]`, bit 7, raw 0 or 1 |
| `logic_groups[g].group_address` | 0..254 or unused 255 | `OutputLogicGroupAddress[g−1]`, 0x5C..0x5F |
| `logic_groups[g].level_store` | Boolean | `LogicLevelStoreEnable[g−1]`, bits 4..7 of 0x6E |
| `logic_groups[g].recovery_percent` | Integer 0..100 | `LightLevelOutput[g+3]`, 0x0C..0x0F |

The original IOPE form labels **And / Or for every active channel**, including
IOPE2C4's dimmers. This is the original numeric radio selection, not an inferred
Min/Max alias. Changing associations only affects control availability. An
explicit function requires at least one final channel association; removing
the last association preserves its stored function. A group address selector
requires at least one active output associated with its row. Stored association
bits for absent outputs do not enable it. Unused group 255 does not itself
invalidate an association.

Plans encode this deterministic user-action sequence:

1. Visit selected channels in ascending order: replace their association list,
   then select their function if supplied.
2. Visit selected logic rows in ascending order and assign every requested
   group address while the recovery modal is absent.
3. If any `level_store` or `recovery_percent` control was requested, open the
   recovery modal once. Binding its four rows normalizes **all four** logic
   recovery levels, including unused and unassociated rows.
4. Visit selected logic rows in ascending order: select level storage first,
   then recovery percentage. A percentage selection requires storage disabled.

Assigning a non-unused group triggers the original `TLogicGroup.GroupChanged`
copy sequence. It scans all four logic rows in ascending order **including
itself**, then the active output channels in ascending order. Every same-group
match copies its raw recovery level and storage flag into the selected logic
row. The last match wins. A self match sees any earlier copy already made into
that row. Assigning the current address still runs this sequence; the source
object-reference setter calls its change callback even when the pointer is
unchanged. Assigning 255 skips the copy sequence. Peers are not rewritten.

A group-only edit copies raw recovery bytes without rounding. Once the modal
opens, its binding calls each checkbox handler, which writes the displayed
slider level even when disabled. The exact conversion is:

```text
percent = (raw_level + 2) * 100 // 255
raw_level = percent * 255 // 100
```

Thus `[179, 51, 77, 89]` becomes `[178, 51, 76, 89]` on modal entry.
Explicit percentages use the second formula; 50% stores 127. Checkbox actions
also write the displayed slider level. Logic storage never forces a recovery
byte to 255: the original logic save loop writes level and storage separately.
A recovery change does not propagate to same-group peers. `derived` records
the assignment copy sequence and modal initialization so hidden writes can be
reviewed before staging.

## Group objects and API

The source compares resolved group objects on the unit's primary application.
This workflow admits primary Lighting applications 48..95 and requires positive
caller evidence for every non-255 logic group, active output group and selected
target group. The narrower Lighting bound is an implementation admission rule,
not a claim that the original group component rejects every other application.
Unresolved groups are refused; no groups are silently created. Hidden output
slots beyond the model's output count do not require objects.

```python
from cbus_toolkit.iope_logic import IopeLogic

editor = IopeLogic(spec)
plan = editor.plan(
    current_values,
    identity=("IOPE2C4", "1.2.00", "5752PP/2R/2D"),
    channels={1: {"logic_groups": [1, 2], "logic_function": "and"}},
    logic_groups={1: {"group_address": 21, "level_store": False,
                      "recovery_percent": 50}},
    group_cache={
        "format": "cbus-iope-logic-groups-v1",
        "source": "Caller-owned closed project inventory",
        "applications": [{"address": 56,
                          "groups": [10, 11, 12, 13, 20, 21, 22, 23]}],
    },
)
# Inspect plan.as_dict(), including derived writes, before staging.
result = editor.apply(pp_session, plan)
assert result["saved"] is False
```

The group inventory must describe the actual selected database context.
`show` reports stored values and control editability without claiming that
objects have been resolved. JSON inputs use canonical string row keys (`"1"`
through `"4"`); Python planning uses integer keys. `plan_from_dict` requires the
complete unsaved document. Applying re-plans its canonical controls and compares
all expected values, changes and detail fields, rejecting omitted cascades,
forged inactive writes and changed identities before staging. PP values must
still match the original snapshot, and native field geometry must match.

The dedicated `python -m cbus_toolkit.iope_workflow_cli --spec-dir ... logic`
entry point exposes `show`, `plan` and the closed-database `database` workflow.
Its offline inputs require an identity envelope. The standalone database wrapper
owns explicit PP/project save and fresh-load evidence; this editor never saves.

## Preservation and evidence

`Application`, `OutputGroupAddress` and output `LevelStoreEnable` are read-only
dependencies. The first four `LightLevelOutput` bytes always stay unchanged.
All inactive association/function slots, bits 4..6 of each 0x70..0x73 byte
(including restrike), lower four store bits at 0x6E, and unrelated parameters
are preserved. Only explicit controls, group-copy effects and optional modal
initialization may change values. A plan without controls performs no hidden
modal initialization.

The sanitized source receipt is
[`iope-logic-source-review.json`](../research/fixtures/iope-logic-source-review.json).
It retains the exact next-distinct-MAP intervals and SHA-256 for 58 methods,
five original DFM resources and the four relevant UnitSpec files. Key sources:

| Original source | Address / role |
| --- | --- |
| `TfrmOutputLogic.SetupLevelAssignments` | 0x11922F0; active channel binding and four rows |
| `TfrmOutputLogic.HandleLogicAssociationAfterChange` | 0x1192034; radio enablement only |
| `TfrmOutputLogicGroup.chkChannel1Click` | 0x1190E24; group selector enablement only |
| `TFlashRadioGroup.Click` | 0xBC06E4; numeric ItemIndex 0/1 |
| `TLogicGroup.GroupChanged` | 0xD2992C; ordered copying including self |
| `TObjectReferenceAttribute.SetFlashObject` | 0x7DDBF4; same-pointer EndUpdate callback |
| `TfrmOutputLogicRecovery.SetupRecoveryLevels` | 0x11B58F8; all four recovery rows |
| `TfrmOutputLogicRecoveryLevel.SetCBusUnit` | 0x11B5068; unconditional checkbox handler |
| `TfrmOutputLogicRecoveryLevel.chkLevelStoreEnableClick` | 0x11B5308; slider gating and Changed |
| `TFlashCxTrackBarProperties.DoChanged` | 0xC09ECC; percentage-to-level write |
| `TIOPECGateAgent.LoadOutputs` / `SaveOutputs` | 0x12D8150 / 0x12DCCB8; four output slots then four logic levels |

Original executable SHA-256:
`9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`.
Original MAP SHA-256:
`f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`.
The shared converter evidence is retained separately in
`research/fixtures/din-output-level-original-vectors.json`.

Focused validation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m unittest -v test_iope_logic
```

The tests cover profile/layout bounds, all four storage rows, active-channel
limits, And/Or values, hidden control preservation, self and duplicate-group
ordering, equal-address callbacks, optional all-row normalization, exact level
conversion, object metadata, neighbour masks, stale/forged plans and rollback.
Native database persistence belongs to `tests/test_iope_logic_native.py` and
its separate receipt. Static source agreement and native database persistence
are not physical controller or original GUI acceptance.

This is not whole `TfrmIOPE` execution. It excludes output-group assignment,
whole-agent inactive-slot padding, unrelated channel power-failure transforms,
input functions, scenes, join/corridor rules, parent-form save rewrites and
physical programming. The phase order prevents group edits while recovery
controls are already bound: their programmatic checkbox notifications can
invoke click handlers, so those other event interleavings are not admitted.

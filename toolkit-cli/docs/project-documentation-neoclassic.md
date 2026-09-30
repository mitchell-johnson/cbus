# NeoProClassic key documentors

`KEYC1`, `KEYC2`, `KEYC4`, `KEYCIR1` and `KEYCIR4` use the original
`TClassicKeyInputDocumentor` even though their unit and agent inherit the
NeoPro model. The portable report admits their original concrete classes from
firmware `1.8.01` through `9`, using the existing strict numeric firmware
parser. Missing or invalid firmware remains partial.

The recovered body contains the inherited timing and eight-key tables. It has
no Neo Scenes appendix because the original factory selects the Classic
documentor. This is independent of the model's `ScenesEnabled` getter.

| Type | Physical keys | Total key objects | Blocks | Remaining key prefix |
| --- | ---: | ---: | ---: | --- |
| KEYC1 | 1 | 8 | 8 | Virtual Key |
| KEYC2 | 2 | 8 | 8 | Virtual Key |
| KEYC4 | 4 | 8 | 8 | Virtual Key |
| KEYCIR1 | 0 | 8 | 8 | IR Key |
| KEYCIR4 | 4 | 8 | 8 | IR Key |

These counts come from the concrete virtual methods, rather than from the
numeric suffix. Physical keys are connected by the inherited NeoPro predicate;
the report does not consume `KeyMask`. None of these classes implements the
bistable-key interface.

## Saved snapshot contract

The body requires explicit programming for all eight keys:

- `SceneKeySelector`: eight flags, with ordinary keys zero and encoded scene
  keys one. A Scene24 key requires `JPCommand` 14; `SRCommand` supplies its ramp
  and `LPCommand` / `LRCommand` encode the trigger byte. Other JP nibbles select
  canonical Scene Modify, whose four raw stages remain unchanged.
- Each Scene24 key requires its own `IndicatorBlockAssignment` index 0 through
  7. Ordinary-key indicator slots are not consumed.
- `Application`: primary and secondary bytes; `SecondApplicationBlocks`: one
  eight-bit block mask.
- `DebounceTime` and `LongPressTime`: an ordinal from 0 through 63 each;
  `RampRate`: two bytes, normalized by the existing original timing rules.
- `GroupAddress`, `BlockAllocation`, `LightLevelStore1`, `LightLevelStore2`,
  `TimerHighByte`, `TimerLowByte`: eight byte values each.
- `JPCommand`, `SRCommand`, `LPCommand`, `LRCommand` and `TimerExpiryCommand`:
  eight nibble values each.

Missing consumed values leave an explicit unrecovered marker. Encoded Scene24
keys are admitted only with an unshared linear primary block: allocation equals
the key's own bit, that block has group 255, its secondary-application bit is
clear, and no other key shares it. Native template assignment can relocate block
data and remove shared references; this guard avoids projecting those effects.
Scene Modify keys use the same canonical guard. Their template remains 25,
displayed as `<Scene Modify>` with Scene 1 / Instant controls. The special
refresh assigns a separate internal ramp template under its lock and never
substitutes it for the key template. No timer default runs on template 25.
In the original, the false
`GetScenesEnabled` and no-op `SetScenesEnabled` do **not** bypass the scene
selector branch in `GetKeyValues`; assuming they do would silently misread
encoded commands.

For ordinary keys the primary `NEOPRO_CLASSIC` and secondary `NEOPRO_S` subsets
resolve through the existing Classic macro matcher. `NEOPRO_S` equals `KEY`.
The additional primary Scene templates all share the idle vector, whose first
global match is Unused, so none can become an ordinary-key first match. The
subset depends on key application state, including virtual keys. The loaded
microfunction stages remain the reported command values. A Timer macro changes
a zero primary-block timer to 300 seconds before the original macro-lock check.

For a mixed-application key, native application lookup prefers its allocated
linear block and otherwise uses the first allocated block. With no allocation
it falls back to the primary application. Stored-level macro conversion and
timer initialization instead use the first allocated block. Report display
lookup preserves application-plus-group identity and the first matching block.

## Scene and join boundaries

The original agent loads `SceneTable` before loading keys, even with scenes
disabled. Every ordinary key's fresh extension is then assigned Scene 1. A
Scene24 key instead uses its indicator index plus one and its decoded ramp. The
Classic body and action consumer do not read the scene table or trigger group,
so this body does not require `SceneTable`, `SceneTablePointer` or
`ControlAppGroupAddress`. Indicator PP is required only for the body's actual
Scene24 references. The native scene collection is padded to eight; displaying
the numeric reference does not require projecting scene commands.

Input group usage is a separate consumer. It reads scene commands and considers
the indexes referenced by all eight keys, including ordinary Scene 1 references
and encoded scene references. Physical key labels are restricted to the
physical count; action usage still scans all eight key objects. The separate
NeoProClassic usage adapter requires its scene projection when that consumer
needs it. An omitted scene table is never evidence of an empty native scene.

Both join capabilities are false. The native loader still stores the raw join
references, but the fresh reference attributes have no change-event binding and
their setters do not mutate keys or blocks. Report and dependency consumers
check the capability before reading a join group. Consequently the report
projection does not require the four Join PP fields; its empty active-join list
does not assert that those saved fields are unused or absent.

## Retained evidence

`research/project_documentor_neoclassic_static.py` checks the pinned Toolkit
EXE/MAP, concrete class and agent factories, documentor selection, virtual
methods, subset tables, key-loading branches, mixed-application lookup, timer
event and join construction/setters. It records the runtime module hash in
`research/experiments/2026-09-30/project-documentor-neoclassic-static.json`.
`research/project_documentor_neoclassic_usage_static.py` separately pins the
usage consumers in `research/fixtures/project-documentor-neoclassic-usage-static.json`.
The companion `project_documentor_neoclassic_scene_static.py` checks the encoded
branch and template/block events. Its [scope receipt](../research/experiments/2026-09-30/project-documentor-neoclassic-scene-scope.md)
records the subset refresh and event prerequisites for Scene Modify.
The later [Scene Modify closure receipt](../research/experiments/2026-09-30/project-documentor-neoclassic-scene-modify-scope.md)
corrects the earlier ordinary-branch inference with the exact special branch,
locks and no-op class callbacks. It admits only the canonical fresh graph.

The new evidence is read-only static inspection. It executes no original CPU
instructions or PP loader. Original generated-page capture, whole-page byte
and visual comparison, retained GUI history, printing, and original encoded-key
loader execution remain unverified. The profile reconstructs a fresh model from an
explicit saved snapshot; it does not reconstruct historical block-reference
ordering or user-installed callbacks.

To reproduce the body receipt with an existing research environment:

```sh
PYTHONPATH=src:research python research/project_documentor_neoclassic_static.py \
  --exe "$CBUS_TOOLKIT_EXE" --map "$CBUS_TOOLKIT_MAP" \
  --output research/experiments/2026-09-30/project-documentor-neoclassic-static.json
```

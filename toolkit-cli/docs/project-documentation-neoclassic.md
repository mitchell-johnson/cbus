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

The body requires explicit ordinary programming for all eight keys:

- `SceneKeySelector`: eight zeros.
- `Application`: primary and secondary bytes; `SecondApplicationBlocks`: one
  eight-bit block mask.
- `DebounceTime` and `LongPressTime`: an ordinal from 0 through 63 each;
  `RampRate`: two bytes, normalized by the existing original timing rules.
- `GroupAddress`, `BlockAllocation`, `LightLevelStore1`, `LightLevelStore2`,
  `TimerHighByte`, `TimerLowByte`: eight byte values each.
- `JPCommand`, `SRCommand`, `LPCommand`, `LRCommand` and `TimerExpiryCommand`:
  eight nibble values each.

Missing consumed values leave an explicit unrecovered marker. Encoded scene
selectors remain outside this profile. In the original, the false
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
disabled. Every ordinary key's fresh extension is then assigned Scene 1. The
Classic body and action consumer do not read the scene table or trigger group,
so this body does not require `SceneTable`, `SceneTablePointer`,
`IndicatorBlockAssignment` or `ControlAppGroupAddress`.

Input group usage is a separate consumer. It reads scene commands and considers
Scene 1 used by the ordinary keys. Physical key labels are restricted to the
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

The new evidence is read-only static inspection. It executes no original CPU
instructions or PP loader. Original generated-page capture, whole-page byte
and visual comparison, retained GUI history, printing, and encoded scene-key
acceptance remain unverified. The profile reconstructs a fresh model from an
explicit saved snapshot; it does not reconstruct historical block-reference
ordering or user-installed callbacks.

To reproduce the body receipt with an existing research environment:

```sh
PYTHONPATH=src:research python research/project_documentor_neoclassic_static.py \
  --exe "$CBUS_TOOLKIT_EXE" --map "$CBUS_TOOLKIT_MAP" \
  --output research/experiments/2026-09-30/project-documentor-neoclassic-static.json
```

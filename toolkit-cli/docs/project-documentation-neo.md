# Neo documentor projection

The offline project report reconstructs the original Classic → Neo → NeoPro
documentor chain for complete, fresh-model PP snapshots. It reads no hardware,
opens no vendor project and does not establish original generated-page parity.

The direct profiles are:

| Unit | Firmware | Physical keys | Additional key labels |
|---|---|---:|---|
| KEYM8 | 1.3.01–1.5.02 Neo; 1.5.03–2.9.99 NeoPro | 8 | None |
| KEYM4 | Same | 4 | IR Key |
| KEYA3 | Same | 3 | Virtual Key |
| KEYB4 | Same | 4 | Virtual Key |
| KEYE1 | Exactly 2.5.00 | 4 | Virtual Key |

All profiles contain eight key objects, eight blocks and eight scene slots.
KEYE1's class exposes four physical positions. Its explicit `KeyMask` controls
connections at positions 2–4; disconnected positions print `Unconnected Key`.
The original loader replaces a mask without bit zero with KEYE1's default 1,
then keeps its low four bits. Other documentors may supply a separately proven
`NeoProfile`, as the DLT body does.

## Output and native behavior

The inherited table includes debounce, long press and two ramp rates, followed
by all eight keys. Ordinary macros reuse the independently recovered classic
factory and application filtering. Extra NEO/NEOPRO scene templates cannot win
ordinary microfunction matching: their idle group first matches Unused.

NeoPro block identity includes both application and group address. A mixed
application key uses its assigned linear block when available, otherwise its
first block. Shutter aliases use the first assigned block's stored levels.
Controls use the first unit-wide block with the same application/group, keeping
duplicate rows. These are three distinct native lookups.

The template change event sets a Timer macro's zero primary-block timer to
300 seconds during loading. Other zero timers remain zero, and an explicit
Idle expiry remains Idle. Invalid timer-expiry ordinals normalize to Off.

Scene keys show their scene number and ramp. The appended scene table includes
only nonempty scene slots, preserving command and trigger-key order. Missing
triggers render `&nbsp;`. Trigger names resolve by level Address, not Value;
names retain the original formatter's literal markup behavior. Group 255 is a
real original Trigger group and may have real action selectors.

The original scene trigger table has an indexing quirk: it takes the selector
from the matching key but the ramp from the key whose index equals the scene
index. The reconstruction preserves this. The individual key row still uses
that key's own ramp.

## Admission boundaries

- Every consumed PP field must be explicit and valid. Missing references needed
  for displayed group/action names remain partial rather than receiving invented
  labels. Timings use the original enum bounds and ramp conversion.
- `SceneTable` and `SceneTablePointer` must have exactly 80 and 8 values. The
  existing device-scene decoder accepts canonical fixed or compact layouts,
  contiguous populated scenes, at most ten commands per scene and forty overall.
  Sparse, duplicate-group, malformed or noncanonical tables remain partial.
- An enabled scene key must use JP14 (Scene). Its block must already be its
  unshared linear block, on the primary application with group 255. This avoids
  the original loader's unmodeled block relocation and swap paths. Scene Modify
  remains partial.
- NeoPro's four join parameters must explicitly equal 255. Join-mode behavior is
  not reconstructed. Old Neo profiles have no secondary application or join
  parameters; their primary application supplies all blocks.
- The adapter models fresh native objects. Ordinary keys start with Scene 1,
  Instant ramp and no trigger level. Prior in-memory block order or previously
  retained scene-extension state cannot be inferred from a PP snapshot.

## Evidence and checks

`research/project_documentor_neo_static.py` reads the pinned Toolkit EXE/MAP and
regenerates `research/experiments/2026-09-30/project-documentor-neo-static.json`.
It records source method hashes, property/loader mappings and explicit checks.
Key anchors include `TNeoInputDocumentor.DocumentHTML` at `0xCA7C38`,
`TNeoProInputDocumentor.DocumentHTML` at `0xCCDDE0`,
`TCoreNeoInputCGateAgent.GetKeyValues` at `0xCCA51C`, and the template change event
at `0xD12ADC`. The scene appendix's ramp-index lookup is at `0xCA7E24`.

Focused verification:

```sh
CBUS_TOOLKIT_EXE=/path/to/CBusToolkit.exe \
CBUS_TOOLKIT_MAP=/path/to/CBusToolkit.map \
PYTHONPATH=toolkit-cli/src python -m pytest -q \
  toolkit-cli/tests/test_project_documentation_neo.py
```

Synthetic tests cover full table strings, physical/virtual keys, KeyMask
normalization, application identity, mixed-block lookup, timer initialization,
scene controls, trigger ordering, group 255, the original ramp-index quirk and
explicit refusals. Source-table and static comparisons remain distinct from
native process execution, original generated HTML, visual and print acceptance.

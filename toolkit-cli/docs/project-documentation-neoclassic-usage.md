# KEYC/CIR report dependencies

The bounded NeoProClassic report model admits KEYC1/2/4 and KEYCIR1/4 with the
source-selected class/agent and ordinary or canonical Scene24/Scene Modify keys.
Each has eight key objects
and eight blocks. Physical counts are 1, 2, 4, 0 and 4 respectively.

The unit's input dependency method is inherited from Neo; it reports matching
blocks in order, key numbers within each block, then scene commands in scene
order. Key labels count physical keys only when both join capabilities are
false. KEYCIR1 therefore reports matching blocks as `Block (Unused)` even when
its IR keys control those blocks. Scene-use classification examines all eight
key scene references, independent of their physical or virtual status. Every
fresh ordinary key references Scene 1. Encoded Scene24 keys instead reference
their indicator index plus one. A scene is used if any key references it.

Scene loading still runs when the class's `GetScenesEnabled` is false. Input
usage requires an explicit scene table when querying the primary application.
An empty table or initial group 255 produces eight empty scenes without reading
pointers. Nonempty tables use the existing canonical 80-byte/eight-pointer scene
decoder. Missing or noncanonical scene data preserves known block descriptions
and marks the input result partial. Secondary application queries do not consume
the primary scene table.

The registered documentor is ClassicKeyInput, so its action report has only the
primary application pass. It scans all eight key objects, preserves repeated
key descriptions and the original stored-1 Address gate around stored-2 Value
matching, and never performs Neo's scene-trigger overwrite or secondary pass.
A known nonprimary query returns empty before unrelated key PP fields are read.
The body and action report do not require SceneTable. Scene24 assignment replaces
the encoded JP/SR/LP/LR with the idle command group, so a Scene24 key produces no
Classic action recall and never enters a separate scene-trigger pass.

Dependency queries do not consume body timing labels or timer durations. Input
usage also does not need stored presets or timer expiry: under the admitted
ordinary-key subsets, only four idle commands resolve to Unused; Scene24 keys
remain active despite normalized idle commands. Action usage
independently requires its stored levels and expiry commands. Missing display
fields therefore cannot turn a known dependency into an unknown result.
Indicator PP is consumed only for actual Scene24 references when the primary
input scene scan has commands. Empty scenes and secondary input queries do not
require it. Missing scene references preserve block descriptions and a partial
result. Ordinary indicator slots remain unconsumed even in mixed snapshots.
Scene Modify keeps its raw stages for Classic actions, references Scene 1 and
remains active even with all-idle stages. Its body, input and actions do not read
the separate internal ramp-template reference or final indicator block number.

Other usage independently consumes primary AreaGroupAddress, optional indicator
brightness group slot 9, application-203 KeyDisableGroup, primary
CorridorMasterGroup and application-202 ControlAppGroupAddress, in native order.
The corridor group is loaded even though corridor activation is unsupported.
Join labels are gated by the unsupported native capabilities. Output usage
inherits the empty base method.

`research/fixtures/project-documentor-neoclassic-usage-static.json` retains 73
checks against the pinned original EXE/MAP: exact virtual slots, method hashes,
loop/gate instructions and loader order. Focused tests reuse the 15 retained
original Classic action instruction cases from the PIR receipt, and cover the
physical/virtual split, scene loading, partial results and independent method
field requirements. These are bounded source projections and retained method
comparisons. No new native CPU probes were launched for this slice. Original
PP-loader execution and full generated-page acceptance remain unassessed.
The companion encoded-key source receipt records 15 additional checks. The later
Scene Modify closure adds 31 exact checks and 153 synthetic source transitions,
preserving template 25 and the raw stages on the canonical graph. Noncanonical
allocation/history and original loader/page execution remain unassessed.

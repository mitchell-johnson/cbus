# SENLLA Scene and application composition source

The [static composition handoff](../research/fixtures/senlla-scene-composition-source.json)
pins 45 methods and the SENLLA virtual route. It records inherited load/save
order, three qualified key-component literals and two Scene-table boundaries.
Independent source review reopened all method pins and traced the nested
callbacks. These deductions do not implement the owning callback engine or
establish original/runtime/hardware acceptance.

CoreKey loads blocks and key mappings first. CoreNeo then loads the Scene
collection and all eight key commands, regardless of the Scene patch gate.
ST7 loads raw bank and occupancy state later, followed by surface overlays and
fresh form initialization. Key templates therefore cannot be reconstructed
from final bank stores as a substitute for the earlier load history.

For an Invoke key on an initially secondary reserved block, an intermediate
application-state callback can replace Scene template24 with ordinary template0
before the outer unlocked handler copies its current template commands. In the
qualified no-collision literal, the final commands are `[13, 0, 0, 0]` and the
saved Scene selector is zero. A secondary Modify key follows a different path:
its raw `[11, 7, 0, 7]` reload becomes ordinary template6, with timer 300 seconds
and expiry command15. A later Scene claim may also remap an already-loaded
ordinary key's indicator through an ordered block swap.

Normal CoreNeo save calls the same Scene-table and pointer serializers used by
`native_sensor_scenes.scene_save_parameters`; those numeric routines have no
key-count dependency. It serializes the Scene table before the eight key values.
The disabled patch skips the table/pointers while the key save still runs.
CoreNeoPro, ST7 and surface overrides follow afterward. SENLL forced-conversion
preparation does not belong to this ordinary SENLLA chain.

The complete owner must replay these callbacks in order, bind actual existing
application/group/level objects or model source-owned project creations, and
compose later bank/scalar normalization. Numeric PP determinism alone does not
establish ownership of newly created metadata. Complete save and Windows
Toolkit parity remain open in issue41.

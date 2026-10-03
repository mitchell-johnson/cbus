# SENLLA Scene and application composition source

The [static composition handoff](../research/fixtures/senlla-scene-composition-source.json)
pins 71 methods and the SENLLA virtual route. It records inherited load/save
order, three qualified key-component literals and two Scene-table boundaries.
Independent source review reopened all method pins and traced the nested
callbacks. These deductions do not implement the owning callback engine or
establish original/runtime/hardware acceptance.

CoreKey loads blocks and key mappings first. CoreNeo then loads the Scene
collection and all eight key commands, regardless of the Scene patch gate.
ST7 loads raw bank and occupancy state later, followed by surface overlays and
fresh form initialization. Key templates therefore cannot be reconstructed
from final bank stores as a substitute for the earlier load history.

The template attribute begins an update on its manager and parent key before
running its dedicated callback. A nested AddBlock returns to a key that is
still updating, so its direct refresh and the updating-key scan are suppressed.
The eventual generic key notification does not replay those direct refreshes.
In the qualified example with an initially secondary, unassociated reserved
block, Invoke therefore retains template24, commands `[14, 4, 10, 5]`, Scene
selector1 and saved Scene index7. Modify retains template25 during raw load;
the fresh function list then selects template16, yielding zero commands and
Scene selector0 while retaining raw indicator6. Its timer and expiry remain
zero. A later Scene claim can still remap another, already-loaded ordinary
key's indicator through an ordered block swap.

These two examples correct the earlier 45-method fixture, whose deductions
missed the template attribute's parent update. The fixture records the old
hash and both independently derived correction receipts. Historical frozen
checks retain their original inputs and counts. These examples cover the
key/application component before later ST7, bank and scalar normalization.

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

The [combined frozen source check](../research/fixtures/senlla-form-input-source-check-20261004.json)
covers nine SENLLA modules at authored commit `8ae5c6fe`: 133 parent
tests, 2,860 separate subtests, zero failures or skips. All 4,062 tracked
inputs remain unchanged. This is source-component evidence; public
whole-unit save and installed-wheel/original/native/physical acceptance
remain open.

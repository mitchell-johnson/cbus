# SENLLA fresh light-level scalar state

`cbus_toolkit.senlla_light_level.SurfaceLightState.from_surface_view` captures
the proven surface raw-load result, including margin percentage calculated
from the original target and the original power-state inputs. It requires a
`SurfaceView`; key, bank, application and metadata callbacks remain owned by
the complete lifecycle.

`fresh_initialize` replays the fresh light-level form's unconditional target
cap: a loaded value above 200 becomes 200. It retains the captured margin
percentage. For example, target 255 with margin 25 loads a percentage of 10;
fresh initialization keeps that percentage and ordinary projection saves
target 200 and margin 20. Recalculating the percentage after the cap would
produce a different result.

Margin display clamps to 1..100 while the locked renderer retains the source
value. Target 1 with margin 255 therefore retains source percentage 25,500 and
saves margin 255, even though the display position is 100. A later controller
apply may submit the same restored source value; this component does not
claim that later notifications are absent.

`parameters` projects only eight surface light-level fields. Target-group
usage copies its group, preset and power-store decision to the margin channel,
and uses target 200 with twice the captured percentage. Margin-group usage
saves its current target as the margin byte. Without either group, the existing
source-recovered extended-precision margin calculation uses the current target
and the captured percentage. Byte-overflow results are refused.

The [fresh scalar source fixture](../research/fixtures/senlla-fresh-light-level-source.json)
contains 58 exact method pins, six target literals and six margin renderer
literals. Focused source checks with the retained surface module pass 30 parent
tests and 288 separate subtests, without skips. No original instructions,
forms, vendor services or hardware execute. Complete 93-parameter save,
installed-wheel acceptance and Windows Toolkit parity remain open in issue41.

The [combined frozen source check](../research/fixtures/senlla-form-input-source-check-20261004.json)
covers nine SENLLA modules at authored commit `8ae5c6fe`: 133 parent
tests, 2,860 separate subtests, zero failures or skips. All 4,062 tracked
inputs remain unchanged. This is source-component evidence; public
whole-unit save and installed-wheel/original/native/physical acceptance
remain open.

# Additional ClassicKeyInput report profiles

The source-pinned snapshot renderer admits KEYIR1, KEYIR4, KEYBC2, KEYBC4,
KEYAUX4, DINAUX4, BCNC4A and BCNC4B when an explicit numeric firmware selects
the original registered class and agent. The factory registers these classes
from `0` through `9`. The same complete logical programming arrays used by
KEY1/2/4 are required; no absent parameter is replaced with a default.

KEYBC2 has two physical keys. Every other type above has four, including
KEYIR1. Their virtual count falls back to the physical count, so the original
report uses bare key numbers even for KEYIR1/4. Every class has four blocks,
the same timing getters and the classic loading routine. None implements
`IBistable`; these report tables have no Bistable column.

KEYAUX4 and DINAUX4 set the AUX macro override when the fresh key collection
is created. Original global matching first identifies the Bell Press vector
`13,15,0,15`; reconciliation changes its template to `Aux On/Off`. The AUX
application subsets replace Bell Press with that template and otherwise have
the same members as KEY. The stored commands remain unchanged. Application
255 still admits only Unused, so that vector renders as Custom there. The
source comparison checks all 65,536 four-nibble command vectors across three
application subsets and nine stored-level contexts: 1,769,472 comparisons.

BCNC4A/B have a distinct agent, but its AfterLoad slot points directly to the
classic loading routine. Their forced microfunction and learn defaults run
in BeforeSave. A read-only project report therefore shows the supplied saved
commands, including Custom configurations, without applying save defaults.
This admission does not broaden preset editing or saving support.

The adapter preserves the shared report's source-established behavior:
first allocated block for shutter aliases, first unit-wide matching group
for stored values, repeated group rows, raw loaded microfunction columns,
and the Timer template's zero-primary-timer assignment to 300 seconds during
fresh loading. Missing or unresolved consumed data produces a partial report
marker before either key table is emitted.

Evidence is in
[`project-documentor-classic-profiles-static.json`](../research/experiments/2026-09-30/project-documentor-classic-profiles-static.json).
Reproduce it with the pinned original files:

```sh
PYTHONPATH=toolkit-cli/src python toolkit-cli/research/project_documentor_classic_profiles_static.py \
  --exe "$CBUS_TOOLKIT_EXE" --map "$CBUS_TOOLKIT_MAP" \
  --output /tmp/project-documentor-classic-profiles-static.json
```

The receipt binds complete EXE/MAP hashes, registrations, agent loading slots,
key/block counts, interface ancestry, group dependency slots, indicator
brightness capabilities, AUX reconciliation and BCNC save-only normalization.
It reads original instruction and registration evidence without executing the
original program. Focused tests are in
`tests/test_project_documentation_classic_profiles.py`.

KEYC1/2/4 and KEYCIR1/4 use the separate
[NeoProClassic projection](project-documentation-neoclassic.md), with eight key
objects. KEYCIR1's physical count is zero, which does not mean its report has
zero rows. That adapter admits ordinary keys and separately recovers bounded
scene dependencies. Encoded scene keys remain partial. Retained GUI
object history, original generated-page byte/visual comparison and printing
remain unverified for all newly admitted profiles.

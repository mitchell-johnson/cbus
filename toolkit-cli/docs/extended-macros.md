# Neo, Reflection, Saturn and 30M key presets

`extended_macros.py` implements the 18 standard wired presets for four explicit
Neo-core profiles. The mapping comes from Toolkit 1.18's help event tables,
its executable's Neo save path, and the original unit specifications. Native
acceptance verifies 72 preset applications and database save/reload with C-Gate
3.4.0 build 2001.

| Specification | Unit type | Product family | Physical keys | Tested catalog | Tested firmware |
| --- | --- | --- | ---: | --- | --- |
| KEYE.xml | KEYE1 | 30M mech | 1 | 5031NMML | 2.5.00 |
| KEYM4.xml | KEYM4 | Neo | 4 | 5054NL | 2.5.00 |
| KEYA3.xml | KEYA3 | Reflection | 3 | R5063NL | 2.5.00 |
| KEYB4.xml | KEYB4 | Saturn | 4 | 5084NL | 2.5.00 |

These are separate vendor unit types sharing `I_NEOPRO.xml` and
`I_NEOCORE.xml`. The KEYE family alone does not identify Neo, Reflection and
Saturn. DLT/eDLT/NCC units, other key counts, older `_A.xml` specifications,
virtual scene keys and custom micro-functions are outside this implementation.

## Python API

```python
from cbus_toolkit.extended_macros import ExtendedKeys
from cbus_toolkit.unitspec import UnitSpecStore

keys = ExtendedKeys(UnitSpecStore(spec_dir).load("KEYM4.xml"))
plan = keys.plan(session.values(), key=3, preset="timer", group=17,
                 timer_seconds=300, recall1=64, recall2=128)
print(plan.as_dict())
result = keys.apply(session, plan)
assert result["verified"]
session.save_to_source()  # Explicit persistence, separate from apply.
```

`configure(session, **options)` combines planning and application. Plans are
immutable snapshots of the relevant parameters. Application validates the
actual native unit type and every relevant field's layout, rejects stale
snapshots, sends full arrays, and checks readback. On failure it attempts to
restore every attempted field and reports rollback errors separately. It never
opens a network, transfers to a physical device or saves implicitly.

Options are `key`, `preset`, `group`, `block`, `application`, `timer_seconds`,
`expiry`, `recall1`, `recall2`, `indicator_block`, and `allow_shared_block`.

- Keys and blocks are one-based. Eight blocks are available. A missing or
  multiple-block assignment requires an explicit block when editing its
  settings. Edits to shared blocks require `allow_shared_block=True`; plans
  report all affected native key-array entries, including virtual entries.
- `application=None` preserves the block's selection. `primary` and `secondary`
  change the corresponding bit in `SecondApplicationBlocks`. Group assignment
  validates the selected existing application as Lighting Type 48–95. This
  option does not change either global application address.
- Groups range from 0 to 254; 255 is the unassigned sentinel. The first eight
  group entries belong to the blocks. The ninth group entry is preserved.
- Timers use 0–65535 integer seconds split into high and low bytes. Explicit
  zero disables the timer. Selecting a timer preset with a disabled existing
  timer requires an explicit duration. Expiry choices are idle, off, down,
  ramp_off, recall1, recall2 and ramp_recall1.
- Recall values are raw byte levels. Indicator assignment is independently
  controlled by `indicator_block=1..8`; omitting it preserves its assignment.
- Applying an ordinary preset clears the selected `SceneKeySelector` bit.
  The scene table and other keys' mode bits are preserved. Stored scenes are
  not deleted when that key becomes an ordinary input key.

## Event and memory mapping

These profiles use the classic four-bit `JPCommand`, `SRCommand`, `LPCommand`
and `LRCommand` fields for short press, short release, long press and long
release. They do not use the newer `KeyShortPress` or other widget command
fields. The 18 event vectors are the [source-defined classic vectors](macros.md#source-defined-vectors):
on, off, toggle, dimmer, dimmer_memory, dimmer_up, dimmer_down, on_up, off_down,
timer, bellpress, soft_up, soft_down, preset1, preset2, trigger1, trigger2 and
unused. A preset is supported only through this proven four-event mapping.

| Parameter | Logical PP address | Shape |
| --- | --- | --- |
| JP / SR | 0x68 | 8 entries; upper/lower nibble; stride 2 |
| LP / LR | 0x69 | 8 entries; upper/lower nibble; stride 2 |
| BlockAllocation | 0x36 | 8 byte masks |
| SecondApplicationBlocks | 0x45 | One byte mask |
| TimerExpiryCommand | 0x48 | 8 low-nibble entries |
| GroupAddress | 0x50 | 9 bytes; first 8 are blocks |
| SceneKeySelector | 0x60 | Bit 7 of 8 entries |
| IndicatorBlockAssignment | 0x60 | Bits 0–2 of 8 entries |
| LightLevelStore1 / 2 | 0x78 / 0x80 | 8 bytes each |
| TimerHighByte / LowByte | 0x88 / 0x90 | 8 bytes each |

## Toolkit evidence

The original help identifies KEYM4 in topic 5022, KEYA3 in 4886, KEYB4 in 4862,
and KEYE1 in 9965/9966. Topics 4863 and 4891 link these families to standard
wired macro functions; 4878 and 4891 describe the four key events. Topics
4844, 4853 and 4879 describe block groups, primary/secondary application,
recall values, timers and independent LED assignment. The help tables in
958–976 supply the preset event combinations, including the dimmer memory
variant. The catalog's Reflection number is R5063NL; help displays 5063NL.

Binary checks are pinned to the original Toolkit 1.18 executable and map file.
The image base is 0x00600000, and MAP section-1 offsets add 0x00601000 to obtain
virtual addresses:

- `TCoreNeoInputCGateAgent.SetKeyValues`, MAP 006CA854, VA 0x00CCB854,
  handles scene invocation separately. Its ordinary-key branch at 0x00CCBB86
  writes zero to member 0x180, then serializes stages 0, 1, 2 and 3 through
  `TInputKey.GetMicroFunctionAsHexString` into the four command attributes.
- `TCoreNeoInputCGateAgent.InternalCreate`, MAP 006C8D04, binds member 0x180
  to the literal `SceneKeySelector` at VA 0x00CCA08C.
- `TInputKey.GetMicroFunctionAsHexString`, MAP 007104D0, calls
  `GetMicroFunctionAsInteger` at VA 0x00D11590. That obtains the selected
  stage from the common macro and calls `TKeyMicroFunction.GetFunctionType`.
  It uses the common nibble function IDs, not the newer device encoding.
- `TCBusNeoInputUnit.MacroFunctionSubsetName`, MAP 00707734, returns `NEO`.
- `SaveSecondApplicationBlocks`, MAP 006EC6AC, adds `1 << block_index` for
  secondary blocks and stores the resulting low byte. The mask instruction
  sequence at VA 0x00CED72A is checked against the original executable.
- The classic macro documentation records the shared micro-function factory
  constants and the timer high/low-byte helpers. Those constants alone were
  insufficient: the Neo-specific save path above establishes which encoding
  and fields these families actually use.

## Verification and remaining scope

The 13-test suite passes with vendor evidence and native acceptance enabled:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=toolkit-cli/research/vendor/unitspec-plain \
CBUS_TOOLKIT_HELP_DIR=toolkit-cli/research/vendor/toolkit-help \
CBUS_TOOLKIT_EXE=toolkit-cli/research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EXTENDED_MACROS_REPORT=toolkit-cli/research/runtime/extended-macros-acceptance.json \
toolkit-cli/.venv/bin/python -m unittest discover -s toolkit-cli/tests \
  -p test_extended_macros.py -v
```

Native tests create a unique project with a closed network. They reset each
unit's native defaults, start a key in scene mode, apply all 18 presets, compare
stage values and packed raw bytes, and confirm the scene table is unchanged.
Additional raw-byte assertions cover group, secondary mask, expiry, timer,
recall and indicator fields. The final state survives an explicit database
save and fresh programming-session load for all four profiles. Deterministic
tests cover all eight blocks, shared and virtual assignments, stale plans,
rollback, layout rejection and bit preservation.

This establishes the source-defined configuration semantics for the listed
profiles and tested firmware. It does not establish physical button behavior,
every firmware, complete GUI before/after parity, automatic GUI indicator
reassignment, DLT/eDLT widgets, NCC programming, custom macros, persistent
scene triggers or device firmware updates. Ramp rates, debounce/long-press
timings, LED styles, corridor linking and join mode remain their existing
settings and can affect physical behavior. Full physical acceptance is still
required. See [extended-macros-acceptance-summary.json](extended-macros-acceptance-summary.json)
for counts and source hashes.

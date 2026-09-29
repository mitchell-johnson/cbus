# Neo-core key presets

`extended_macros.py` implements the 18 standard wired presets for 31 explicit
Neo-core profiles. The mapping comes from Toolkit 1.18's micro-function
groups and help event tables, its executable's Neo save path, and the original
unit specifications. Native
acceptance verifies 558 preset applications and project close/reload with
C-Gate 3.4.0 build 2001. Every profile was tested at firmware 2.5.00.

| Specification | Unit type | Product family | Toolkit class | Keys | Tested catalog |
| --- | --- | --- | --- | ---: | --- |
| KEYE.xml | KEYE1 | C-Bus 30M mech | TKEYEx | 1 | 5031NMML |
| KEYM2.xml | KEYM2 | Neo | TKEYM2 | 2 | 5052NL |
| KEYM4.xml | KEYM4 | Neo | TKEYM4 | 4 | 5054NL |
| KEYM8.xml | KEYM8 | Neo | TKEYM8 | 8 | 5058NL |
| KEYA1.xml | KEYA1 | Reflection | TKEYA1 | 1 | R5061NL |
| KEYA3.xml | KEYA3 | Reflection | TKEYA3 | 3 | R5063NL |
| KEYA6.xml | KEYA6 | Reflection | TKEYA6 | 6 | R5066NL |
| KEYA8.xml | KEYA8 | Reflection | TKEYA8 | 8 | R5068NL |
| KEYAV2.xml | KEYAV2 | Reflection vertical | TKEYAV2 | 2 | R5062VNL |
| KEYAV4.xml | KEYAV4 | Reflection vertical | TKEYAV4 | 4 | R5064VNL |
| KEYB2.xml | KEYB2 | Saturn | TKEYB2 | 2 | 5082NL |
| KEYB4.xml | KEYB4 | Saturn | TKEYB4 | 4 | 5084NL |
| KEYB6.xml | KEYB6 | Saturn | TKEYB6 | 6 | 5086NL |
| KEYH1.xml | KEYH1 | Saturn ZEN | TKEYH1 | 1 | ER5041NL |
| KEYH2.xml | KEYH2 | Saturn ZEN | TKEYH2 | 2 | ER5042NL |
| KEYH3.xml | KEYH3 | Saturn ZEN | TKEYH3 | 3 | ER5043NL |
| KEYH4.xml | KEYH4 | Saturn ZEN | TKEYH4 | 4 | ER5044NL |
| KEYC1.xml | KEYC1 | Classic Neo | TKEYC1 | 1 | 5031NL |
| KEYC2.xml | KEYC2 | Classic Neo | TKEYC2 | 2 | 5032NL |
| KEYC4.xml | KEYC4 | Classic Neo | TKEYC4 | 4 | 5034NL |
| KEYCIR4.xml | KEYCIR4 | Classic Neo infrared | TKEYCIR4 | 4 | 5034NIRL |
| KEYDV1.xml | KEYDV1 | Decorator | TKEYDV1 | 1 | SLC5051NLM |
| KEYDV2.xml | KEYDV2 | Decorator | TKEYDV2 | 2 | SLC5052NLM |
| KEYDV3.xml | KEYDV3 | Decorator | TKEYDV3 | 3 | SLC5053NLM |
| KEYDV4.xml | KEYDV4 | Decorator | TKEYDV4 | 4 | SLC5054NLM |
| KEYP2.xml | KEYP2 | Modena | TKEYP2 | 2 | LHC882 |
| KEYP4.xml | KEYP4 | Modena | TKEYP4 | 4 | LHC884 |
| KEYP6.xml | KEYP6 | Modena | TKEYP6 | 6 | LHC886 |
| KEYV1.xml | KEYV1 | Avanti | TKEYV1 | 1 | 5091NL |
| KEYV2.xml | KEYV2 | Avanti | TKEYV2 | 2 | 5092NL |
| KEYV3.xml | KEYV3 | Avanti | TKEYV3 | 3 | 5093NL |

These are separate vendor unit types sharing `I_NEOPRO.xml` and
`I_NEOCORE.xml` (KEYH1–KEYH3 through `I_KEYHPRO.xml` and `I_KEYH3PRO.xml`).
Every parameter has the same layout as KEYM4, except KEYE1's KeyMask. The key
count is Toolkit's `MaximumKeyCount` for the registered class. KEYE1 is the
exception. Its `TKEYEx` class serves KEYE1–KEYE4 through a key mask, and KEYE1
keeps its accepted single key.

The following specifications are refused explicitly:

- KEYM6.xml has the KEYM4 layout, but Toolkit 1.18 registers no KEYM6 unit
  class.
- KEYCIR1.xml's `TKEYCIR1.MaximumKeyCount` returns zero.
- KEYV1SP.xml is a bus coupler. Eight parameters have a different layout, and
  its Toolkit class saves through `TCBusCouplerVieoInputCGateAgent`.
- Every first-generation `_A.xml` specification uses `I_NEO.xml`, 14 differing
  parameters and the `TCBusNeoInputCGateAgent` save path.

DLT/eDLT/NCC units, other firmware, virtual scene keys and custom
micro-functions are outside this implementation.

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
Bell Press and Soft Up/Down use Toolkit's micro-function groups rather than
their help event tables; see [the classic comparison](macros.md#source-defined-vectors).

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
958–976 describe the preset event combinations, including the dimmer memory
variant; where three of them differ, the executable's groups decide. The catalog's Reflection number is R5063NL; help displays 5063NL.

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

### Family equivalence

`research/key_preset_families.py` writes the sanitized receipt
[key-preset-family-equivalence.json](../research/fixtures/key-preset-family-equivalence.json)
without executing vendor code. For each candidate specification, it records the
SHA-256 of each file and include, a digest of every parameter's layout and of
the 15 preset fields, and the names of parameters that differ from KEYM4 in
layout or default only. KEYV1–KEYV3 differ only in the IndicatorFunction
default. It also follows these executable facts:

- The `TUnitTypeFactory.RegisterUnitType` call site gives each unit type's
  Delphi class and firmware range. Every admitted class descends from
  `TCBusNeoProInputUnit`, and 2.5.00 lies inside every range.
- At `TFlashAgentFactory.RegisterAgent`, every admitted class except KEYE1's
  `TKEYEx` registers the same `TCBusNeoProInputCGateAgent` as KEYM4, KEYA3 and
  KEYB4. `TKEYEx` registers its `TCBusKEYExCGateAgent` subclass. That agent
  chain inherits the `TCoreNeoInputCGateAgent.SetKeyValues` save path above.
- The virtual `MacroFunctionSubsetName` resolves to `TCoreNeoProInputUnit`
  (`NEOPRO`). The Classic Neo classes resolve to
  `TCBusNeoProClassicInputUnit` (`NEOPRO_CLASSIC`). Both subsets offer all 18
  preset templates, but Trigger 1 and Trigger 2 appear only for Trigger
  Control (202) blocks. `extended_macros.py` resolves the key's block and its
  primary/secondary application (after any `application` option) and refuses
  both trigger presets unless that application is 202.
- The C-Gate catalogue selects each admitted specification, not its `_A`
  predecessor, at firmware 2.5.00.

## Verification and remaining scope

Run the suite with vendor evidence and native acceptance on an owned loopback
C-Gate 3.4.0 build 2001 (`research/local_cgate.py`), or set
`CBUS_CGATE_TEST_HOST` for a disposable server:

```sh
cd toolkit-cli
CBUS_NATIVE_SERVICE_BACKEND=local \
CBUS_CGATE_JAVA=/path/to/java11/bin/java \
CBUS_LOCAL_CGATE_VENDOR=research/vendor/cgate/app \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_HELP_DIR=research/vendor/toolkit-help \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_UNIT_CATALOG=research/vendor/cgate/app/unitspec/cbusunits.xml \
CBUS_EXTENDED_MACROS_REPORT=research/runtime/extended-macros-acceptance.json \
PYTHONPATH=src:tests .venv/bin/python -m pytest \
  tests/test_extended_macros.py tests/test_key_preset_families.py -v
```

Set `CBUS_NEO_PROFILES=KEYM2.xml,KEYDV4.xml` to limit a diagnostic run.

The native test creates a unique project with a closed network whose CNI
address is an owned idle loopback listener. It creates a database unit for
every profile from its catalogue number. It resets native defaults, starts the
highest key in scene mode, applies all 18 presets, and compares stage values
and packed raw bytes. After every preset, it compares all parameters outside
the 15 preset fields, including the scene table. Additional raw-byte assertions
cover group, secondary mask, expiry, timer, recall and indicator fields. Each
unit is saved, the project is closed and reloaded, and a fresh programming
session must return identical values. Refusal tests reject KEYM6, KEYCIR1,
KEYV1SP and `_A` specifications, and a KEYM4 plan on a KEYM2 session, before
any write. Deterministic tests cover all eight blocks, shared and virtual
assignments, stale plans, rollback, layout rejection and bit preservation.

This establishes the source-defined configuration semantics for the listed
profiles and tested firmware. It does not establish physical button behavior,
every firmware, complete GUI before/after parity, automatic GUI indicator
reassignment, DLT/eDLT widgets, NCC programming, custom macros, persistent
scene triggers or device firmware updates. Ramp rates, debounce/long-press
timings, LED styles, corridor linking and join mode remain their existing
settings and can affect physical behavior. Full physical acceptance is still
required. See [extended-macros-acceptance-summary.json](extended-macros-acceptance-summary.json)
for counts and source hashes.

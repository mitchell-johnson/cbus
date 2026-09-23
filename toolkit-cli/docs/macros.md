# Classic key macro presets

`macros.py` configures the physical keys of **KEY1, KEY2 and KEY4** through native C-Gate programming sessions. It supports 18 source-defined presets, group/block assignments, 16-bit timers and two recall levels. It checks the native unit type and parameter layout, preserves other keys and unrelated parameters, detects stale plans and verifies readback. Applying a plan edits the PP session; saving remains an explicit operation.

The current acceptance covers the original Toolkit help tables and executable registration constants, all 18 presets on native KEY4 firmware 1.2.67, native KEY1/KEY2 configuration, and database save/reload. It does not establish physical button behavior, every firmware revision, eDLT/NCC widgets, sensors, wireless inputs or all Toolkit macros.

## CLI

```sh
cbus-toolkit keys presets

cbus-toolkit keys --spec-dir research/vendor/unitspec-plain \
  plan KEY4.xml parameters.json --key 2 --preset timer \
  --group 17 --timer-seconds 300
```

The online `cgate unit ... key-macro` action accepts the same preset and key options, plus `--spec-dir` and `--spec`. Use its existing programming-session source, dry-run and explicit save options. `cbus-toolkit cgate unit --help` and `cbus-toolkit cgate unit key-macro --help` show the current argument placement.

## Python

```python
from cbus_toolkit.macros import ClassicKeys
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore

keys = ClassicKeys(UnitSpecStore("research/vendor/unitspec-plain").load("KEY4.xml"))

with Programmer(client).load("//MYPROJ/254", "/db//MYPROJ/254/p/10") as session:
    plan = keys.plan(session.values(), key=2, preset="timer", group=17,
                     timer_seconds=300)
    print(plan.as_dict())
    result = keys.apply(session, plan)
    assert result["verified"]
    session.save_to_source()  # Separate, explicit database save.
```

`keys.configure(session, **options)` combines planning and application. Keys and blocks are one-based; the physical key count is 1, 2 or 4 even though the native arrays have four entries. Full arrays are written to avoid native indexed-SET offset inconsistencies. Untouched entries retain their current values.

Options are `key`, `preset`, `group=None`, `block=None`, `timer_seconds=None`, `expiry="off"`, `recall1=None`, `recall2=None`, and `allow_shared_block=False`. Group assignment supports Lighting Type primary applications 48–95 and groups 0–254; 255 is the unassigned group sentinel. The four supported blocks map to the first four group entries. Other entries and application selection are preserved.

When a block option is needed, an existing single assignment selects that block. Multiple, missing or unsupported assignments require an explicit block 1–4. Editing a block shared with another key requires `allow_shared_block=True` or selecting a different block. The plan reports the affected key numbers, including other native key-array entries.

Timer intervals are integer seconds, 0–65535. The high and low bytes are separate parameters. **An explicit zero disables the timer.** Selecting the timer preset with an already disabled timer requires an explicit interval; an omitted interval preserves an existing enabled timer. Expiry selection applies when an interval is supplied. Recall levels are raw 0–255 values.

## Source-defined vectors

The event order is **short press, short release, long press, long release**, corresponding to `JPCommand`, `SRCommand`, `LPCommand` and `LRCommand`. Classic keys have four stages; a double-press stage is not inferred.

| Preset | JP | SR | LP | LR | Help topic |
| --- | ---: | ---: | ---: | ---: | --- |
| on | 13 | 0 | 0 | 0 | [958](../research/vendor/toolkit-help/958.htm) |
| off | 15 | 0 | 0 | 0 | [959](../research/vendor/toolkit-help/959.htm) |
| toggle | 11 | 0 | 0 | 0 | [960](../research/vendor/toolkit-help/960.htm) |
| dimmer | 0 | 11 | 2 | 14 | [961](../research/vendor/toolkit-help/961.htm) |
| dimmer_memory | 0 | 3 | 2 | 14 | [961](../research/vendor/toolkit-help/961.htm) |
| dimmer_up | 0 | 13 | 5 | 14 | [966](../research/vendor/toolkit-help/966.htm) |
| dimmer_down | 0 | 15 | 4 | 14 | [967](../research/vendor/toolkit-help/967.htm) |
| on_up | 0 | 3 | 5 | 14 | [962](../research/vendor/toolkit-help/962.htm) |
| off_down | 0 | 3 | 4 | 14 | [963](../research/vendor/toolkit-help/963.htm) |
| timer | 11 | 7 | 0 | 7 | [964](../research/vendor/toolkit-help/964.htm) |
| bellpress | 13 | 15 | 13 | 15 | [965](../research/vendor/toolkit-help/965.htm) |
| soft_up | 14 | 10 | 5 | 14 | [968](../research/vendor/toolkit-help/968.htm) |
| soft_down | 14 | 9 | 4 | 14 | [969](../research/vendor/toolkit-help/969.htm) |
| preset1 | 0 | 12 | 9 | 0 | [970](../research/vendor/toolkit-help/970.htm) |
| preset2 | 0 | 6 | 9 | 0 | [971](../research/vendor/toolkit-help/971.htm) |
| trigger1 | 12 | 0 | 0 | 0 | [972](../research/vendor/toolkit-help/972.htm) |
| trigger2 | 6 | 0 | 0 | 0 | [973](../research/vendor/toolkit-help/973.htm) |
| unused | 0 | 0 | 0 | 0 | [976](../research/vendor/toolkit-help/976.htm) |

The names alone were not used to infer their numbers. The original executable's `CIS_TKeyMicroFunction.InitialiseKeyMicroFunctionFactory` registers the classic values below. Its `RegisterKeyMicroFunction` implementation sends the EDX argument to `TKeyMicroFunction.SetCBusValue`; a separate argument holds the newer encoding. This distinction matters because newer values do not fit the classic nibble fields.

| Classic code | Function |
| ---: | --- |
| 0 | Idle |
| 1 | Store 1 |
| 2 | Downcycle |
| 3 | Memory Toggle 2 |
| 4 | Down Key |
| 5 | Up Key |
| 6 | Recall 2 |
| 7 | Retrigger Timer |
| 8 | Start |
| 9 | Ramp Off |
| 10 | Ramp Recall 1 |
| 11 | Toggle |
| 12 | Recall 1 |
| 13 | On Key |
| 14 | End Ramp |
| 15 | Off Key |

## Binary and schema evidence

The PE image base is `0x00600000`; section 1 starts at RVA `0x1000`. MAP section-relative offsets therefore add `0x00601000` to obtain a virtual address for this build.

- `InitialiseKeyMicroFunctionFactory`: MAP `0001:0068CB30`, VA `0x00C8DB30`.
- `RegisterKeyMicroFunction`: MAP `0001:0068EEAC`, VA `0x00C8FEAC`.
- Inline UTF-16 registration names identify Idle, Downcycle, Down Key, Up Key, Toggle, On Key, Off Key and End Ramp. Resource IDs identify Memory Toggle 2 (`64607`), Retrigger Timer (`64581`), Recall 1 (`64594`), Recall 2 (`64595`), Ramp Off (`64598`), Ramp Recall 1 (`64596`), Store 1 (`64577`) and Start (`64580`).
- `TInputBlockCollection.GetAllTimerHighByteAsString`: MAP `0001:0070F2D4`; it calls `CIS_Maths.HighByte` (`0001:001EFE64`). The low-byte counterpart at `0001:0070F39C` calls `CIS_Maths.LowByte` (`0001:001EFE50`). These helpers select the upper/lower bytes of a 16-bit value. [Help 1878](../research/vendor/toolkit-help/1878.htm) defines the maximum interval as 65535 seconds; [help 8138](../research/vendor/toolkit-help/8138.htm) documents zero-duration expiry behavior and the permitted expiry functions.
- `KEY1.xml`, `KEY2.xml` and `KEY4.xml` inherit `I_KEY.xml`. JP/SR share bytes starting at `0x32`, LP/LR at `0x33`; each key uses stride 2. JP/LP occupy the upper nibble. Block allocation starts at `0x3A`, timer high bytes at `0x44`, low bytes at `0x48`, expiry nibbles at `0x4C`, and group addresses at `0x50`.

Inspected source hashes:

| Artifact | SHA-256 |
| --- | --- |
| CBusToolkit.exe | `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| CBusToolkit.map | `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb` |

## Verification and limits

Run deterministic tests without vendor files:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p test_macros.py -v
```

To include exact source and native acceptance on a disposable C-Gate instance:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_HELP_DIR=research/vendor/toolkit-help \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
PYTHONPATH=src python3 -m unittest discover -s tests -p test_macros.py -v
```

Native tests create a unique `Kxxxxxxx` project with a closed network, compare all stage vectors and packed bytes, then save/reload a database unit. No physical network is opened. Failed local application attempts restore attempted parameters and verify the original snapshot. A transport failure can also prevent rollback; `MacroApplyError.rollback_errors` records that uncertainty rather than claiming success.

This module does not implement arbitrary custom micro-function editing, sensor/wireless/scene macros, secondary-application assignment, join mode, multi-block configuration, LED reassignment, or newer input-unit variants. Existing indicators, ramp rates, recall levels and timers are preserved unless their corresponding supported option is supplied. Those retained settings can affect the resulting physical behavior and need device-level acceptance separately.

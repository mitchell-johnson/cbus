# Classic key macro presets

`macros.py` configures the keys of classic key, infrared, auxiliary and bus-coupler input units through native C-Gate programming sessions. It supports 18 source-defined presets, group/block assignments, 16-bit timers and two recall levels. It checks the native unit type and parameter layout, preserves other keys and unrelated parameters, detects stale plans and verifies readback. Applying a plan edits the PP session; saving remains an explicit operation.

| Specification | Unit type | Toolkit class | Keys | Tested catalog / firmware | Parameters never written |
| --- | --- | --- | ---: | --- | --- |
| KEY1.xml | KEY1 | TKey1 | 1 | 5031N / 1.2.67 | — |
| KEY2.xml | KEY2 | TKey2 | 2 | 5032N / 1.2.67 | — |
| KEY4.xml | KEY4 | TKey4 | 4 | 5034N / 1.2.67 | — |
| KEYIR1.xml | KEYIR1 | TKEYIR1 | 4 | 5031NIR / 1.2.67 | InfraRedBank |
| KEYIR4.xml | KEYIR4 | TKEYIR4 | 4 | 5034NIR / 1.2.67 | InfraRedBank |
| KEYAUX4.xml | KEYAUX4 | TKEYAUX4 | 4 | 5104AUX / 1.2.67 | IndicatorBrightness (absent) |
| DINAUX4.xml | DINAUX4 | TDINAUX4 | 4 | L5504AUX / 1.2.67 | GAVBroadcastFlag, IndicatorBrightness (absent) |
| KEYBC2.xml | KEYBC2 | TKEYBC2 | 2 | 5102BCLEDL / 1.2.67 | GAVBroadcastFlag, IndicatorBrightness (absent) |
| KEYBC4.xml | KEYBC4 | TKEYBC4 | 4 | 5104BCL / 1.2.67 | GAVBroadcastFlag, IndicatorBrightness (absent) |

The key count is Toolkit's `MaximumKeyCount` for the registered class, so the 1-key infrared unit exposes four inputs. The last column lists the parameters whose layout differs from KEY4. A preset plan cannot contain them, application rejects a plan that does, and native acceptance proves their values survive every preset, save and reload. `GUARDED_PARAMETERS` exposes the same list.

KEYAUX4 and DINAUX4 refuse `bellpress`. Their Toolkit class returns the `AUX` macro-function subset, which omits the Bell Press template and offers Aux On/Off instead. BCNC4A and BCNC4B are refused. Their `TBCNC4CGateAgent.BeforeSaveProgrammingInformation` calls `TBCNC4.ApplyMicroFunctionDefaults`, which overwrites all 16 stage values before every Toolkit save.

The current acceptance covers the original Toolkit help tables and executable registration constants, all 18 presets on native KEY4 firmware 1.2.67, every applicable preset on each other admitted type, native KEY1/KEY2 configuration, and database save/reload. It does not establish physical button, infrared or auxiliary-input behavior, every firmware revision, eDLT/NCC widgets, sensors, wireless inputs or all Toolkit macros.

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

`keys.configure(session, **options)` combines planning and application. Keys and blocks are one-based; the key count is 1, 2 or 4 (see the table) even though the native arrays have four entries. Full arrays are written to avoid native indexed-SET offset inconsistencies. Untouched entries retain their current values.

Options are `key`, `preset`, `group=None`, `block=None`, `timer_seconds=None`, `expiry="off"`, `recall1=None`, `recall2=None`, and `allow_shared_block=False`. Group assignment supports Lighting Type primary applications 48–95 and groups 0–254; 255 is the unassigned group sentinel. The four supported blocks map to the first four group entries. Other entries and application selection are preserved.

When a block option is needed, an existing single assignment selects that block. Multiple, missing or unsupported assignments require an explicit block 1–4. Editing a block shared with another key requires `allow_shared_block=True` or selecting a different block. The plan reports the affected key numbers, including other native key-array entries.

Timer intervals are integer seconds, 0–65535. The high and low bytes are separate parameters. **An explicit zero disables the timer.** Selecting the timer preset with an already disabled timer requires an explicit interval; an omitted interval preserves an existing enabled timer. Expiry selection applies when an interval is supplied. Recall levels are raw 0–255 values.

## Custom micro-functions

`ClassicKeys.plan_micro_functions(values, key=..., stages=...)` edits one key's JP, SR, LP and LR cells, as Toolkit's micro-function grid does (`TfrmKeyMicroFunctions`, hosted by `TddKey4` for every admitted classic type). `stages` maps `jp`/`sr`/`lp`/`lr` (or the parameter names) to a micro-function name from the table below or its code. `configure_micro_functions(session, ...)` plans and applies with the same type, schema, stale-snapshot, readback and rollback checks as presets. Only the named stages change; block, timer, recall and application settings are untouched.

```sh
cbus-toolkit keys micro-functions
cbus-toolkit keys --spec-dir "$CBUS_UNITSPEC_DIR" custom-plan KEY4.xml values.json --key 2 --jp on --lr 15
cbus-toolkit cgate unit --lock-address //PROJ/254 --source /db//PROJ/254/p/20 \
  key-micro-functions --spec KEY4.xml --key 2 --jp on --lr off
```

Value domain and behavior recovered from the executable (VAs are for the pinned build):

- The grid always has four rows, `GetRowCount` (0x00F62644), for Short Press, Short Release, Long Press and Long Release. The row index is the stage.
- `IsAllowedMicroFunction` (0x00F63DAC) admits a micro-function only when `GetCBusValue <= 15`. Stage, family, subset and application are not tested, so every cell offers codes 0–15 and nothing else. Ramp On, the POT timers and scene functions are excluded. `MICRO_FUNCTION_LABELS` keeps the combo order and text.
- `TInputKey.SetMicroFunction` (0x00D117B4) changes only the edited stage and then rematches the template with exact group vectors. The plan reports `matched_preset` when the result equals a preset, and `custom` otherwise. No timer or block dependency is checked for Retrigger Timer or Start.
- Classic keys show `MaximumKeyCount` columns, with no join or virtual columns, so keys are limited to the counts in the table above.
- `TInputKey.GetMicroFunctionAsHexString` (0x00D114D0) saves each stage's FunctionType. For codes 0–15 it equals the classic nibble.

KEYAUX4 and DINAUX4 accept any 0–15 vector. Toolkit relabels a Bell Press vector on those keys as Aux On/Off without changing the bytes.

## Power-up broadcast

`input_power_up.py` covers two "Broadcast Values on Power Up" editors:

- **KEYBC2, KEYBC4 and DINAUX4**: `KeyPowerUpBroadcast(spec).plan(values, broadcast=True|False)` writes `GAVBroadcastFlag` 0 or $FF. This matches `TCBusKeyInputCGateAgent`'s save. `GroupAddressBroadcastPropertyEnabled` enables the checkbox only for these types (and the refused BCNC), so other classic types have no power-up setting.
- **BCN2B, BCN4B and KEYV1SP bus couplers**: `CouplerPowerUp(spec).plan(values, enable=[...], disable=[...])` edits `GroupAssertOnPowerup`, where bit 0 is block 1. `TcdBCProLightLevelRestore` enables a block only when a bistable key references it (`TCoreBusCouplerInputUnit.IsKeyBlockBistable`, 0x00CE69B8). The key's `BistableSwitchBlock` bit and its `BlockAllocation` mask decide that. Enabling any other block is refused. Toolkit unticks non-bistable blocks, and its agent rebuilds the whole byte (0x0121F221), so the plan clears stale bits and reports them in `cleared_non_bistable`. It does not change `BistableSwitchBlock`; Toolkit auto-ticks a key's blocks when that key becomes bistable, which this editor leaves to an explicit `enable`.

```sh
cbus-toolkit keys --spec-dir "$CBUS_UNITSPEC_DIR" power-up-plan BCN4B.xml values.json --enable-block 1
cbus-toolkit cgate unit ... power-up --spec KEYBC4.xml --broadcast
```

IOPE occupancy controllers use another rule (bistable auxiliary inputs and non-zero block groups) and are refused. KEY1/2/4, KEYIR and KEYAUX4 have no power-up broadcast setting.

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
| bellpress | 13 | 15 | 0 | 15 | [965](../research/vendor/toolkit-help/965.htm) |
| soft_up | 0 | 10 | 5 | 14 | [968](../research/vendor/toolkit-help/968.htm) |
| soft_down | 0 | 9 | 4 | 14 | [969](../research/vendor/toolkit-help/969.htm) |
| preset1 | 0 | 12 | 9 | 0 | [970](../research/vendor/toolkit-help/970.htm) |
| preset2 | 0 | 6 | 9 | 0 | [971](../research/vendor/toolkit-help/971.htm) |
| trigger1 | 12 | 0 | 0 | 0 | [972](../research/vendor/toolkit-help/972.htm) |
| trigger2 | 6 | 0 | 0 | 0 | [973](../research/vendor/toolkit-help/973.htm) |
| unused | 0 | 0 | 0 | 0 | [976](../research/vendor/toolkit-help/976.htm) |

The vectors are the micro-function groups that Toolkit assigns when the template is selected. `TKeyMacroFunction.SetFunctionType` calls `RefreshFromFunctionType`, which calls `AssignTemplate_Microfunctions` with `TKeyMacroFunctionTemplate.GetMicroFunctionGroupDefault`. That returns the template's first registered group (template type `0x30` excepted). Dimmer's second group is the Memory variant. `InitialiseKeyMicroFunctionGroupFactory` registers each group's four stages, and `InitialiseKeyMacroFunctionFactory` binds templates to groups.

Three help event tables disagree with those groups. Toolkit writes the group, so the presets follow the executable:

| Preset | Help topic JP/SR/LP/LR | Toolkit group | Group JP/SR/LP/LR |
| --- | --- | ---: | --- |
| bellpress | 13/15/13/15 (965) | 41 | 13/15/0/15 |
| soft_up | 14/10/5/14 (968) | 44 | 0/10/5/14 |
| soft_down | 14/9/4/14 (969) | 45 | 0/9/4/14 |

Toolkit maps loaded stage values back to a template with exact group matches (`TKeyMacroFunctionFactory.GetTemplateAndGroup`). A help-table vector therefore appears as a custom function in Toolkit, not as Bell Press or Soft Up/Down. `HELP_TABLE_EVENTS` retains the help rows, and the vendor help test checks them. Earlier releases of this module wrote the help vectors; reapply the preset to units configured with them.

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

### Family equivalence

`research/key_preset_families.py` produces the sanitized receipt [key-preset-family-equivalence.json](../research/fixtures/key-preset-family-equivalence.json). It never executes vendor code. For each candidate, it records the SHA-256 of each specification file and include, a digest of every parameter's layout and of the preset fields, and the names of parameters whose layout or only default differs from KEY4. It also follows these executable facts:

- The `TUnitTypeFactory.RegisterUnitType` call site gives the Delphi class and firmware range for each unit type. The VMT parent chain places every admitted class under `TCBusKeyInputUnit`.
- `TFlashAgentFactory.RegisterAgent` gives each class's C-Gate agent. KEY1/KEY2/KEY4, KEYIR1/KEYIR4, KEYAUX4, DINAUX4 and KEYBC2/KEYBC4 all register `TCBusKeyInputCGateAgent`, so they share the save path through `TKeyInputCGateAgent.SetKeyValues`. BCNC4A uses the `TBCNC4CGateAgent` subclass described above.
- The virtual `MacroFunctionSubsetName` (VMT slot 0x1C4) and `MaximumKeyCount` (slot 0x190) implementations give the subset and key count. `InitialiseKeyMacroFunctionSubsetFactory` gives the template types that each subset offers.
- `TKeyMacroFunction.ReconcileTemplateAndGroup` shows the AUX override replacing template types 7 (Bell Press) and 27 with 28 (Aux On/Off).

Regenerate the receipt and compare it with the committed copy:

```sh
python research/key_preset_families.py --unitspec-dir "$CBUS_UNITSPEC_DIR" \
  --exe research/vendor/toolkit/app/CBusToolkit.exe \
  --map research/vendor/toolkit/app/CBusToolkit.map \
  --catalog research/vendor/cgate/app/unitspec/cbusunits.xml \
  --output research/fixtures/key-preset-family-equivalence.json
```

In every subset, Toolkit offers Trigger 1 and Trigger 2 only on Trigger Control (202) blocks. `TKeyMacroFunctionSubsetFactory.GetKeyMacroFunctionSubset` looks up the subset by the key's application and falls back to the application-0 list, which omits both templates. If the application changes, `RefreshMacroFunctionsFromApplication` resets a template that is no longer offered to Unused. `macros.py` therefore refuses `trigger1` and `trigger2` unless the primary application is 202. On such a key, `--group` sets the trigger group; other presets still require a Lighting application for group edits. The receipt keeps the per-application template sets and the group vectors (`preset_micro_function_groups`).

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

To include exact source and native acceptance, use an owned loopback C-Gate 3.4.0 build 2001 (`research/local_cgate.py`), or set `CBUS_CGATE_TEST_HOST` for a disposable server:

```sh
CBUS_NATIVE_SERVICE_BACKEND=local \
CBUS_CGATE_JAVA=/path/to/java11/bin/java \
CBUS_LOCAL_CGATE_VENDOR=research/vendor/cgate/app \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_HELP_DIR=research/vendor/toolkit-help \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_UNIT_CATALOG=research/vendor/cgate/app/unitspec/cbusunits.xml \
PYTHONPATH=src:tests python3 -m pytest tests/test_macros.py tests/test_key_preset_families.py -v
```

Native tests create a unique project with a closed network whose CNI address is an owned idle loopback listener. They compare all stage vectors and packed bytes, then save/reload a database unit. The family test creates KEYIR1, KEYIR4, KEYAUX4, DINAUX4, KEYBC2 and KEYBC4 database units from their catalogue numbers. It sets each differing parameter that exists on the type to a non-default value and applies every preset to the highest key: 106 applications and two AUX Bell Press refusals without writes. Each trigger preset is first refused on the Lighting application without writes, then applied after the primary application is set to 202. After each preset it compares the stage bytes and every parameter outside the preset workflow. It then saves each unit, closes and reloads the project, and requires identical PP values. Another native test rejects a KEY4 plan on a KEYIR4 session before writing. [classic-key-family-acceptance-summary.json](classic-key-family-acceptance-summary.json) records the counts and source hashes. No physical network is opened. Failed local application attempts restore attempted parameters and verify the original snapshot. A transport failure can also prevent rollback; `MacroApplyError.rollback_errors` records that uncertainty rather than claiming success.

Native acceptance for custom micro-functions and power-up broadcast (`tests/test_input_options.py`) covers the following:

- All 16 codes on every stage of KEY4 and KEYAUX4, with packed bytes and unrelated-parameter preservation checked.
- Single-stage edits.
- The couplers BCN2B, BCN4B and KEYV1SP, including bistable refusal, stale-bit clearing and raw `$1D`.
- `GAVBroadcastFlag` on KEYBC2, KEYBC4 and DINAUX4.
- Save and project close/reload for each unit.
- The CLI dry-run and persist paths.

Physical key, broadcast and power-cycle behavior is not established.

This module does not implement sensor/wireless/scene macros, secondary-application assignment, join mode, multi-block configuration, LED reassignment, infrared bank settings, IOPE power-up options, or newer input-unit variants. Existing indicators, ramp rates, recall levels and timers are preserved unless their corresponding supported option is supplied. Those retained settings can affect the resulting physical behavior and need device-level acceptance separately.

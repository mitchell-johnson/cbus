# Classic programming alignment

`OfflineConversion` transfers the shared programming configuration between `KEY1.xml`, `KEY2.xml`, and `KEY4.xml`. It supports all nine directed pairs, including the same type, and verifies C-Gate's parameter values before and after changing an offline programming session. Saving the session is an explicit separate operation.

This is the programming alignment stage of Toolkit conversion. It does not yet implement the complete frontend replacement workflow. Neo, DLT, PIR and other sensor families are rejected. The source and destination must use the exact supported classic layouts, with one lighting application (48–95) and disabled secondary application (255).

```python
from cbus_toolkit.offline_conversion import OfflineConversion

converter = OfflineConversion(store.load("KEY4.xml"), store.load("KEY1.xml"))
plan = converter.plan(source_session.values(), target_session.values())
print(plan.as_dict())                 # review every change and retained field
result = converter.apply(target_session, plan)
assert result["verified"]
target_session.save_to_source()       # explicit database save, when wanted
```

`configure(source_session, target_session)` verifies both session identities/schemas and combines planning with application. Both sessions must be new or loaded from an explicit `/db//PROJECT/...` source. Physical programming sessions are rejected. Plans are immutable, and application recomputes the supported changes to reject forged field writes. A changed destination snapshot aborts before any `SET`. Failed writes trigger restoration of every attempted parameter, including a command with an uncertain outcome; `ConversionApplyError.rollback_errors` reports failures to restore or verify the original snapshot.

The plan copies these 26 programming attributes: application, unit name, LearnAnyApp/LearnMode, area group, report interval, group assignments, debounce/long-press timing, indicator brightness/assignment/function, ramp rates, the four press/release command arrays, block allocation, timer high/low/expiry arrays, EEPROM level-store enable, light index, light levels, and the two recall-level stores. All four stored key slots survive a change in physical key count. Plans list newly exposed keys and source keys that become physically inactive; their stored configuration is still present.

The target retains UnitAddress, Project and NetworkAddress. This makes alignment into an independently addressed destination coherent; replacing the original source unit at its original address requires a separate database operation. Checksum state/alarm, EEPROMLevelRecall, factory PatchEnable/CUSTYPE and LearnedFlag also retain target values, with a reason for every exclusion. Unknown source fields are reported and are not transferred. Extra native parameters absent from the supplied specification cause schema verification to fail.

LearnedFlag is a deliberate outstanding gap: Toolkit's frontend checks current and original learned state before deciding whether that parameter is mutable. A pair of PP snapshots does not contain that UI history. The implementation does not invent the history or claim this transition is complete.

## Source evidence

The original Toolkit 1.18 help topic `1843.htm` explicitly permits conversions among the one-, two- and four-key standard units. The recovered `KEY1.xml`, `KEY2.xml` and `KEY4.xml` specifications share the classic `I_KEY.xml` layouts. Vendor source files are supplied by the user and are not bundled with this package.

The exact executable is SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`. MAP `.text` addresses become PE virtual addresses by adding `0x00601000`.

| Toolkit routine | MAP offset | Evidence |
| --- | --- | --- |
| `TCBusUnitConversion.Convert` | `006ADAF0` | Creates a replacement with target type/firmware; copies source tag, description and unit name; aligns programming; removes/readdresses the old unit afterward. |
| `TCBusUnitCGateAgent.AlignUnitNoSave` | `006BF4A4` | Copies matching named agent attributes, excluding OID; applies a registered parameter-name mapping if needed; invokes the conversion tweaker and the target's conversion hook. Empty source attributes become non-mutable. |
| `TCBusUnitCGateAgent.InternalCreate` | `006B424C` | Registers common application and unit-name attributes. Identity attributes have different flags. |
| `TCBusInputUnitCGateAgent.InternalCreate` | `006C543C` | Registers area group and status-report interval. |
| `TCBusLearnUnitCGateAgent.InternalCreate` | `006C4AA0` | Registers LearnAnyApp, LearnMode and LearnedFlag. |
| `TCoreKeyInputCGateAgent.InternalCreate` | `006C5D18` | Registers the shared key, group, indicator, timing, EEPROM-level and recall-level attributes. |
| `TCBusLearnUnitCGateAgent.BeforeUnitConversionSave` | `006C4F70` | Enables learning attributes according to firmware support; handles LearnedFlag using current/original model state. |
| `TCoreKeyInputUnit.LearnModePropertiesEnabled` | `0069D014` | Uses firmware threshold `1.2.63`, matching the minimum supported classic specifications. |
| `TCoreKeyInputCGateAgent.BeforeUnitConversionSave` | `006C8180` | Adds separate cross-application and classic↔Neo group-layout handling. Those branches do not justify blind copying into other families. |

The 26 copied names are checked against their actual `PUSH` references to Unicode strings in the original executable by the opt-in source test. The native test changes every copied attribute, exercises every directed classic pair, checks independent command-byte vectors, saves each destination and loads a new session to verify every copied attribute and retained destination address. This proves the implemented programming stage against C-Gate; the tests do not execute Toolkit's Delphi GUI.

## Further conversion work

Exact binary investigation identified additional transformations but they are not enabled by this module:

- `TTweakerInputUnit.TweakParameters` (`00CF034C`) suppresses 13 specific IR, nightlight, colour, timer-duration and backlight attributes.
- `TTweakerKeyToNeo.TweakParameters` (`00CF06C8`) additionally suppresses control/scene fields and maps IndicatorFunction `1→2`, `3→1`, leaving other values unchanged.
- `TTweakerNeoToKey.TweakParameters` (`00CF0974`) invokes the common input tweaker. Group-array conversion lives in the separate core-key hook, so this routine alone is insufficient to implement Neo→classic.
- DLT and sensor families have separate tweakers and `BeforeUnitConversionSave` hooks. Their compatibility matrices, group relocation, application handling and conditional defaults require independent tests before support can be advertised.

The typed native `CONVERTUNIT` command has its own compatibility matrix and modes, documented separately. Its availability is not evidence of complete Toolkit frontend conversion support.

## Verification

From the package directory:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p test_offline_conversion.py -v
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
PYTHONPATH=src python3 -m unittest discover -s tests -p test_offline_conversion.py -v
```

The second command enables native and exact-binary checks. All 14 tests pass. Native acceptance creates a uniquely named disposable project and a closed loopback network; no physical network is opened.

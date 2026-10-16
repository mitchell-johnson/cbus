# Thermostat temperature model boundaries

The [quick-zone and plant workflow](thermostat-quick-zone-controls.md) loads all
15 recovered temperature fields into one shared integer model. Each explicitly
issued save encodes the final live fields once. This keeps source PP bytes,
model values and saved PP bytes distinct within the owning settings transaction.
Deterministic plan revalidation constructs separate owners from the immutable
raw snapshot; it does not reload an existing live store or perform another
server save.
The [release report](feature-batch-2026-10-04-thermostat-temperature-owner.md)
records the focused acceptance and its limits. This implements the bounded
transaction work in [issue 119](https://github.com/mitchell-johnson/cbus/issues/119);
the wider thermostat work remains in
[issue 42](https://github.com/mitchell-johnson/cbus/issues/42).

## Using the workflow

Use the existing settings preview/apply command with an admitted thermostat
unit, decoded specification, complete closed project and exclusive editing
ownership. Include `--temperature-preference celsius` and at least one supported
quick-zone or plant operation. The process preference is an immutable owner
fact, independent of the unit's `TemperatureUnits` PP setting.

```sh
cbus-toolkit thermostat settings preview //PROJECT/NETWORK/p/UNIT \
  --spec-dir /path/to/decoded/specs --host HOST --port PORT \
  --exclusive-project --temperature-preference celsius \
  --output-operation '{"op":"quick-zone-view"}'
```

A view operation does not invoke a temperature control. Loading and the final
form save may still produce a changed PP plan. Inspect the complete preview and
use the existing [settings apply contract](thermostat-settings.md) for backup,
one PP save, separate target project save and successful reopen. An uncertain
save is never retried automatically.

Read `output_projection.quick_zone_controls.temperature_model`:

| Field | Meaning |
| --- | --- |
| `preference` | Explicit Toolkit process preference sealed with the owner. |
| `raw` | Original post-overlay PP bytes captured before decoding. |
| `loaded` | The 15 model integers produced by the owning load. |
| `live` | Current shared model integers after the explicit history. |
| `encoded` | Final bytes from the current owner-issued save, or null before one is issued. |

These views are diagnostic data. Importing their JSON cannot issue an owner,
simulate callbacks or authorize a save. Load conversions reported in
`model_overrides` do not mean the user edited a control.

## Field-specific encoding

The codec uses the existing source-pinned `TEMPERATURE_SAVE_RULES`, including
the independent arithmetic captures and field call-site/cast evidence.

| Fields | Load/store rule |
| --- | --- |
| Minimum/MaximumSetTemperature | Signed source byte and simple unit-temperature conversions; low-byte store. |
| GuardUpperTemperature, GuardMaximumUpperTemperature | Signed guard conversion; save conversion capped at 127 before low-byte store. |
| Other four Guard temperature fields | Signed guard conversion; low-byte store without that extra upper cap. |
| SetbackLevel | Signed offset conversion with the recovered shift; low-byte store. |
| EvapStart/StopProportionalTemperature | Signed offset conversions; low-byte store. |
| TemperatureOffset | Signed quarter-degree offset conversion; low-byte store. |
| TemperatureSendDifferential | Unsigned quarter-degree offset conversion; unsigned store. |
| EvapComfortStartTemp | Unsigned whole-degree conversion and store. |
| EvapComfortStepSize | Unsigned half-degree offset conversion and store. |

The three unsigned stores refuse converted results outside 0..255. They do not
wrap 256 into a valid PP byte. All15 consumed raw fields must be exact integers
0..255; live codec inputs must be exact signed 32-bit integers.

An uncapped guard with source 126 or 127 loads as 52 and saves as 128 in the
admitted Celsius profile. Issuing another save of that unchanged live model
still encodes 128. A separate new load of saved 128 produces a different live
value and saves 129. No hidden load/save runs to seek a fixed point.

Raw `--set` values retain the existing survival rule: each requested temperature
byte must equal its final encoded byte. The preliminary full-owner settings
phase parses raw edits; temperature serialization is deferred until the exact
fresh owner issues its save. Ordinary settings, output-only and damper-only
histories retain their legacy raw round-trip behavior.

## Remaining boundaries

Both Basic PC_TSB/PC_TSB5 and Programmable PC_TSA/PC_TSA5 use this boundary.
The full owner still requires Celsius source minimum 15/maximum 32/GuardEnable 0,
settled admitted timing values, valid enums and a consumed explicit plant-change
queue. The pure codec supports both preference arithmetic profiles; broader
Fahrenheit owner initialization remains unproved.

Temperature slider and time control histories, wider initialization, activation,
reentry, implicit Windows notification scheduling, original GUI execution and
physical thermostat acceptance remain open. This transaction operates on the
selected C-Gate database through cgate-mock or cmqttd; it does not program a
physical thermostat or prove native Schneider server behavior.

## Focused validation

After selecting existing maintained binaries, run the bounded source cohort:

```sh
cd toolkit-cli
CBUS_CGATE_MOCK_BIN=/absolute/path/to/cgate-mock \
CBUS_CMQTTD_BIN=/absolute/path/to/cmqttd \
  make check-thermostat-temperature-owner
```

The target requires both binaries and runs the new codec, owner and backend modules together with the preserved temperature/settings/quick-zone/remote and CI-registration cohort. It starts owned loopback peers only. The release report records separate source and fresh installed-wheel epochs; original software and physical acceptance require their own provision.

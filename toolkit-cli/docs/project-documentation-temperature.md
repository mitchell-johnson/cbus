# Temperature sensor documentors

The offline documentor projects the original temperature report bodies from the
saved PP fields that each selected branch consumes. It admits the native factory
classes for SENTEMP (firmware 1.00 through 1.2.68), SENTEMPB / SENTEMPPro (0 through
9), and SENTEMP4 / TPC_RDTS (0 through 9). An absent or invalid firmware, incomplete
consumed PP field, or missing displayed group/selector produces a partial marker.
It does not infer native programming-load success, synthesize missing metadata,
or edit temperature programming.

The project renderer chooses an explicit **Celsius with period decimal** profile.
The helper also supports an explicit Fahrenheit profile. Neither observes the
running Toolkit unit preference or Windows locale. Group and level links use the
existing report formatting, including raw tag names and the escaped unused-group
name. A used trigger group with selector address 255 still requires that level.

SENTEMP reports Controlled, Enable and Economy groups, heating/cooling mode,
target, margin and the economy offset when its group is used. Its target is
`Ceil((TemperatureHigh + TemperatureLow) / 2)`, not nearest-even rounding. Its
margin is the signed high-minus-low difference. Fahrenheit targets use absolute
conversion; margins and offsets subtract 32 after conversion, then use the
original nearest-even integer rounding.

SENTEMPB chooses its mode from the primary application: 25 is temperature
broadcast, 172 HVAC broadcast, 228 measurement, and all other applications select
the control report. The control report retains native high/low/economy clamps.
Broadcast reports retain interval/threshold sentinels, normalization and clamps,
trigger-group/action links, mode-specific group or Device ID, and ordered zones.
Interval values are six ten-second units per minute. The PP threshold is first
halved/truncated and clamped as in the loader, then divided by two for display.
Fahrenheit thresholds are deltas.

SENTEMP4 reports Device ID and four channels. Channel names undergo Delphi's
ASCII-space trim and fall back to `Channel N` only when empty. HVAC mode with an
unused communication group is rendered as Measurement, matching the original.
Disabled interval/threshold PP values still report the loaded defaults of 60
seconds and 0.50°C because this body does not inspect the enabled flags. Threshold
PP units are eighths of a degree. The native Fahrenheit branch treats the
threshold as an absolute temperature and adds 32; this behavior is preserved.
The original body ends at `</tr>` without closing its table; that malformed final
line is also preserved.

SENTEMP input usage names its Control Group. SENTEMPB names its Controlled Group
only in control mode. Other usage preserves Area, Enable and Economy order in
control mode, and the Temperature or Communication group in the corresponding
broadcast mode. The native output dependency method is empty. Trigger action
usage and SENTEMP4 dependencies remain in the existing usage module.

Evidence:

- `research/project_documentor_temperature_static.py` pins 39 checks and 20
  method spans to the original EXE/MAP hashes, with the report retained at
  `research/experiments/2026-09-30/project-documentor-temperature-static.json`.
- `research/project_documentor_temperature_original.py` retains 18 original
  body executions, nine synthetic models in both unit profiles. The bodies,
  zone/interval formatters, integer rounding and Fahrenheit conversion execute;
  object getters, common HTML and Delphi string/Format leaves are synthetic.
- A separate 576-case comparison executes original `FloatToText`,
  `FloatToDecimal` and Fahrenheit arithmetic for every admitted eighth-degree
  threshold and every Pro half-degree threshold in both unit profiles. It pins
  decimal ties such as 0.125°C → 0.13°C, independently of the body Format stub.
- All 511 possible byte high+low sums execute original `Math.Ceil`, covering
  every admitted SENTEMP target average. These comparisons are retained in
  `research/fixtures/project-documentor-temperature-original.json`.

The focused test file is `tests/test_project_documentation_temperature.py`.
Fresh vendor checks require `CBUS_TOOLKIT_EXE` / `CBUS_TOOLKIT_MAP`; original
instruction execution additionally requires `CBUS_RUN_DOCUMENTOR_ORIGINAL=1`.
Default tests never request executable emulator memory.

Original whole-page generation, PP-loader execution, previous mutable model
state, other locales, printing, physical temperature sensing and device behavior
remain outside this acceptance. No hardware or original GUI ran for this work.

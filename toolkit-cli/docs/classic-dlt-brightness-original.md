# Original classic DLT brightness and nightlight PP evidence

`research/classic_dlt_brightness_original.py` executes bounded original Toolkit
1.18.0.2754 x86 agent fragments and model getters/setters. The executable, MAP,
I_NEOCORE and I_DLT specifications are checked against pinned hashes. The retained
receipt is `research/fixtures/classic-dlt-brightness-original.json`.

The inherited CoreNeo load/save paths copy TimerDuration (byte `0x33`, low nibble)
and IndicatorPressedLevel (high nibble) directly into the model's integer
KeyPressBrightnessDuration and KeyPressBrightnessLevel attributes. Both PP fields
admit 0–15, with default 15. These paths perform no numeric conversion or clipping.
The DLT virtual table resolves IsNeoClassic and IsNeoMultisensor to false, so the
ordinary inherited paths apply.

DLT load gates both EnablePageFallback and EnableIndicatorPressedLevel with
`duration > 0`. It sets model NightlightEnabled true and NightlightForced to the
inverse of PP EnableNightlight. EnableNightlightControl, user-key nightlight,
toggle-key nightlight and FirstKeyThrowAway copy directly. DLT save always marks
EnableNightlight programmable and writes false (byte `0x34`, bit 0). It writes
the current other model flags unconditionally. The original GUI's initialization,
duration selector and checkbox dependencies are separate from these agent rules.

The replay covers every byte `0x33` value and every byte `0x34` pattern at durations
0, 1, 2 and 15: 1,280 load/save cases. With no intervening GUI event, byte `0x33`
is unchanged; byte `0x34` becomes `raw & 0xFE` for positive duration or
`raw & 0xF2` for zero duration. DisableTimerFlash (bit 1) is outside the replay
fragments and preserved in the reconstructed observation. In particular, the
agent alone does not clear nightlight or FirstKeyThrowAway when pressed mode is
disabled; that clearing belongs to the original GUI dependency handlers.

Synthetic hooks replace attribute storage, Variant helpers and unit lookups.
The family methods, property accessors and four agent fragments execute original
instructions. No GUI, native C-Gate server, project persistence or household
hardware is exercised by this receipt. Native persistence and GUI event receipts
must be reported separately.

Replay with the configured private paths:

```sh
CBUS_TOOLKIT_EXE=/path/to/CBusToolkit.exe \
CBUS_TOOLKIT_MAP=/path/to/CBusToolkit.map \
CBUS_UNITSPEC_DIR=/path/to/decoded/specs \
PYTHONPATH=src:. python -m unittest discover -s tests \
  -p test_classic_dlt_brightness_original.py -v
```

Unicorn JIT requires a compatible execution environment. The retained receipt can
be checked without private vendor inputs; the opted-in replay must not be confused
with an offline receipt check.

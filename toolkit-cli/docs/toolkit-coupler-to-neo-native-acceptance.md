# Coupler-to-Neo conversion: owned native acceptance

The native check on 2026-09-30 passed all five remaining `TTweakerKeyToNeo`
coupler directions for a source at **1.2.67** and a fresh target at
**2.2.00**. It checks the recovered constructor and hook profile described in
the [source proof](../research/fixtures/toolkit-key-to-coupler-conversion-source-proof.json).

| Source | Target | Source catalogue | Target catalogue |
| --- | --- | --- | --- |
| KEYBC2 | BCN2B | 5102BCLEDL | 5102BCLEDL |
| KEYBC2 | BCN4B | 5102BCLEDL | 5104BCL |
| KEYBC4 | BCN2B | 5104BCL | 5102BCLEDL |
| KEYBC4 | BCN4B | 5104BCL | 5104BCL |
| DINAUX4 | BCI4A | L5504AUX | L5504AUX |

The [receipt](../research/fixtures/coupler-tweaker-native.json) records five
successful conversions, eight source/target units verified after project
save, close and load, and 805 native commands. No PP SET failed. The new
[targeted test](../tests/test_coupler_tweaker_native.py) passed (`1 passed in
2.16s`). Its source hashes bind the main conversion module, both key/coupler
helpers, native helper and test; private specification/catalogue inputs are
identified only by hashes.

The independently written literals in the
[native helper](../research/coupler_tweaker_native.py) pin these differences
from ordinary classic-key to Neo conversion:

- Source `GroupAddress` has eight elements; the target has nine. A vector
  containing 0, 127, 254, 255 and distinct later positions verifies the
  original first-four/four-255/source-index-4 transformation, exact plan
  formatting, and native raw PP formatting.
- Source `IndicatorFunction=0 1 2 3` becomes the literal plan string
  `0 2 2 1 `, including its trailing space. Native target elements 4–7
  retain `3 3 3 3`, independently observed in fresh control units.
- `LightLevel` copies 16 source elements into a 28-element target and retains
  the target's last 12 defaults. Other command, timer, block and indicator
  arrays copy their four-element prefixes into eight-element targets.
- Source specifications omit `IndicatorBrightness`. The final CouplerPro
  hook leaves target brightness at `0xff`; the plan never writes it.
- A source-only `GAVBroadcastFlag=0x5a` remains unchanged on the source and
  does not appear on the target. `GroupAssertOnPowerup`,
  `BistableSwitchBlock` and `RetardationIndex` retain native defaults.
- Source `LearnedFlag=0` leaves the fresh target's native default `1`, while
  source `LearnMode=1` and `LearnAnyApp=1` copy. Suppressed scene, infrared,
  corridor and related fields retain defaults.
- `BCI4A` explicitly uses `BCN4B.xml` with specification identity `BCN4B`.
  Its database identity remains `BCI4A` after conversion and reload.

The check also verifies unchanged source PP/metadata, stable repeated
read-only planning, native `NOOP`, pair and target-firmware refusals before
I/O, and source firmware refusal before replacement creation. Raw PP and
existing scalar values survive reload; the native service materializes only
the observed `DeviceName=NEWUNIT` and empty `GroupNumber` scalar defaults.

The selected catalogue defaults are not general firmware acceptance. Source
KEYBC2/KEYBC4 specifications span 1.2.63–9; L5504AUX's DINAUX4 catalogue
revision ends at 1.9.99. BCN2B/BCN4B default revisions span 2.2.00–2.3.99;
BCI4A's default revision spans 2.2.00–2.2.99. This receipt accepts only the
exact 1.2.67 → 2.2.00 profile tested here.

Run the targeted check with explicitly selected private inputs:

```sh
CBUS_CGATE_JAVA=... CBUS_LOCAL_CGATE_VENDOR=... CBUS_UNITSPEC_DIR=... \
  PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_coupler_tweaker_native.py -q
```

Regenerate the receipt using the same variables with
`research/coupler_tweaker_native.py --output PATH`. Missing native inputs
cause the test to skip; that is not acceptance.

The helper owns a temporary C-Gate 3.4.0.2001 process, ephemeral loopback
listeners and a synthetic project. Listener ownership, process exit and
complete cleanup are verified. It rejects `CONVERTUNIT` and network-open
commands. No original Toolkit GUI execution or physical C-Bus programming
is claimed.

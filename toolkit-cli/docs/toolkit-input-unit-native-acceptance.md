# InputUnit conversion: owned native acceptance

The native check on 2026-09-30 passed all ten non-sensor `TTweakerInputUnit`
directions at **source firmware 1.2.67 → fresh target firmware 1.2.67**.
The source constructor and hook rules are recorded separately in the
[source proof](../research/fixtures/toolkit-input-unit-conversion-source-proof.json).
The registered `SENPILL → SENPILL` sensor direction remains refused.

| Directions | Count |
| --- | ---: |
| KEY1, KEY2, KEY4 to each other, excluding self-conversion | 6 |
| KEYBC2 ↔ KEYBC4 | 2 |
| BCNC4A ↔ BCNC4B | 2 |

All seven selected unit profiles have 36 native PP parameters, eight group
addresses, four indicator/block/command elements, 16 light levels and two
application elements. `BCNC4B` uses the explicit `BCNC4A.xml` specification
alias in both source and target roles; its database identity remains BCNC4B.
Its catalogue number is `5032NLPC`, while BCNC4A uses `5032NLPCP`. All selected
catalogue default revisions are exactly 1.2.67. Adjacent revisions using the
same specifications are not accepted by this bounded profile.

The [native receipt](../research/fixtures/input-tweaker-native.json) records
10 successful conversions, 17 source/target units verified after project
save, close and load, and 1,683 native commands. No PP SET failed. The new
[targeted test](../tests/test_input_tweaker_native.py) passed (`1 passed in
3.09s`). The receipt hashes the main conversion module, InputUnit helper,
shared key helper, native helper and test, together with the selected
private specification/catalogue files and native runtime executables.

The [native helper](../research/input_tweaker_native.py) uses independent
literal expectations, including group addresses 0/127/254/255, all four
indicator-function values, nondefault block/command/timer/light values and
explicit fields that distinguish the original writable rules:

- `GroupAddress` retains all eight original positions. `IndicatorFunction`
  retains `0 1 2 3`. Their aligned native strings are unchanged; neither field
  receives a conversion rewrite.
- KEY1/KEY2/KEY4 targets copy brightness `0xad`. Coupler targets do not write
  brightness and have no native brightness parameter.
- Source `LearnedFlag=0` leaves the target's native default `1`; source
  `LearnMode=1` and `LearnAnyApp=1` copy. This follows the fresh model hook,
  rather than deriving mutable flags from native PP defaults.
- `GAVBroadcastFlag` is an agent attribute whose initial mutable flag is
  false. Source `0x5a` therefore leaves a coupler target at `0xff`.
- `PatchEnable` is a native PP parameter absent from the classic agent's
  attribute inventory. Source `0x55 0xaa` leaves key targets at
  `0xff 0xff` and coupler targets at `0x9d 0x40`. Absence from the tweaker's
  suppressed-name list does not make an absent agent attribute writable.

Every source's PP and metadata remain unchanged. Repeated read-only plans
and native `NOOP` preserve the database. Unsupported pair examples,
including SENPILL self-conversion, fail before I/O; unsupported target
firmware fails before I/O, and unsupported source firmware fails before
replacement creation. Raw PP and existing scalar fields survive reload,
which materializes only the observed `DeviceName=NEWUNIT` and empty
`GroupNumber` scalar defaults.

Run the targeted check with explicitly selected private inputs:

```sh
CBUS_CGATE_JAVA=... CBUS_LOCAL_CGATE_VENDOR=... CBUS_UNITSPEC_DIR=... \
  PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_input_tweaker_native.py -q
```

Regenerate the receipt with the same variables using
`research/input_tweaker_native.py --output PATH`. Missing inputs cause a
skip, which is not native acceptance.

This check uses an ordinary owned Java/C-Gate 3.4.0.2001 process, ephemeral
loopback listeners and a synthetic project. It rejects `CONVERTUNIT` and
network-open commands. Listener ownership, process exit and complete
cleanup are verified. No CPU emulation probes, original Toolkit GUI
execution or physical C-Bus programming are claimed.

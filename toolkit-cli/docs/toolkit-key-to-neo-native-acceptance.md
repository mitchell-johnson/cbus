# Classic-key to Neo conversion: owned native acceptance

The native check on 2026-09-30 passed all 93 registered `TTweakerKeyToNeo`
directions from `KEY1`, `KEY2`, `KEY4`, `KEYIR1` or `KEYIR4` at firmware
**1.2.67** to their admitted Neo targets at firmware **2.5.00**. The check
creates a fresh replacement database unit for each case. Other firmware and
model lifecycles remain outside this profile.

The [receipt](../research/fixtures/keytweaker-native.json) records 93 successful
conversions, 98 source/target units verified after project save, close and
load, and 10,363 native C-Gate commands. No conversion had a failed PP SET.
It binds the exact implementation, helper and test source hashes, selected
private specification/catalogue hashes, and C-Gate/JDK executable hashes.

| Source types | Target types | Directions |
| --- | --- | ---: |
| KEY1, KEY2, KEY4, KEYIR1, KEYIR4 | KEYB2/4/6, KEYH1/2/3/4, KEYM2/4/8, KEYA1/3/6/8, KEYAV2/4 | 80 |
| KEY1, KEY2, KEY4 | KEYC1/2/4 | 9 |
| KEYIR1, KEYIR4 | KEYCIR1/4 | 4 |

The [helper](../research/keytweaker_native.py) defines its pair inventory and
expected transformation strings independently of production mapping code.
Its nondefault source group vector is `0 127 254 255 42 99 231 17`; every
plan must produce `0x00 0x7F 0xFE 0xFF 0xFF 0xFF 0xFF 0xFF 0x2A`, and the
stored raw PP must have native lowercase, unpadded hex formatting. Source
indicator values `0 1 2 3` must produce the original plan string `0 2 2 1 `,
including its trailing space. Native target elements 4–7 retain their fresh
defaults, independently read from 21 control units.

The acceptance additionally checks:

- Nondefault command, block, indicator-assignment, light-store and timer
  prefixes copy while unused target array tails retain native defaults.
- Brightness `0xad` copies despite the constructor's initially immutable flag.
  Source `LearnedFlag=0` leaves the native fresh target default `1`; source
  `LearnMode=1` and `LearnAnyApp=1` copy. The difference between fresh model
  state and PP defaults is explained in the
  [learning source review](toolkit-key-conversion-learning-source-review.md).
- Tweaker-suppressed fields, the NeoPro hook's fields, and serial retain fresh
  target defaults. Source `PatchEnable=85 170` specifically distinguishes
  suppression from an accidental copy.
- Every source's PP and metadata remain unchanged. Repeated read-only plans
  and native `NOOP` leave the database unchanged.
- Raw PP and existing scalar fields survive project save/close/load. The
  native reload adds only the observed `DeviceName=NEWUNIT` and empty
  `GroupNumber` scalar defaults.
- Unsupported pair/profile examples fail before I/O; a source at firmware
  1.2.66 fails before replacement creation.

Run the targeted native test with explicitly selected private inputs:

```sh
CBUS_CGATE_JAVA=... CBUS_LOCAL_CGATE_VENDOR=... CBUS_UNITSPEC_DIR=... \
  PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_keytweaker_native.py -q
```

Regenerate the receipt with the same variables using
`research/keytweaker_native.py --output PATH`. The test skips when native
inputs are absent; a skip is not native acceptance.

The helper owns its ephemeral loopback service and temporary project. The
receipt confirms listener ownership, process exit and directory cleanup.
It rejects `CONVERTUNIT` and network-open commands. This is Toolkit-style
client conversion and native database persistence, without original Toolkit
GUI execution or physical C-Bus programming. The five coupler/DINAUX
KeyToNeo registrations, NeoToKey, InputUnit and other firmware/model
profiles are separate work and are not accepted by this receipt.

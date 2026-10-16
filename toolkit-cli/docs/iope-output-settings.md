# IOPE Turn On and Restrike settings

`cbus_toolkit.iope_output_settings.IopeOutputSettings` provides a bounded
Toolkit 1.18 output workflow for IOPE1R1, IOPE2R2 and IOPE2C4. It plans and
stages PP changes with verified readback. It performs no save or physical I/O.

An explicit `(unit_type, firmware, catalog_number)` identity is required for
planning. The admitted firmware interval is **1.0.00 through 1.2.99**, matching
the existing IOPE specification/catalogue intersection. Catalogue may be
unknown (`None`); a supplied value must match the selected type. Native tests
at particular revisions establish only those observed revisions, not every
revision in the interval.

| Type | Catalogue | Output channels | Relay channels | Dimmer channels |
| --- | --- | --- | --- | --- |
| IOPE1R1 | 5752PP/1R | 1 | 1 | none |
| IOPE2R2 | 5752PP/2R | 2 | 1, 2 | none |
| IOPE2C4 | 5752PP/2R/2D | 4 | 1, 2 | 3, 4 |

## Controls and dependencies

| Control | API input | Exact stored field |
| --- | --- | --- |
| Relay turn-on threshold / dimmer minimum | `channels[n].min_percent`, 0..100 | `MinDimmingLevel[n-1]`, four bytes at 0x78 |
| Dimmer maximum | `channels[n].max_percent`, 0..100 | **Only channels 3/4**: `MaxDimmingLevel[n-3]`, two bytes at 0x7C |
| Relay restrike checkbox | `channels[n].restrike`, Boolean | `RestrikeChannel[n-1]`, bit 6 of each of four bytes at 0x70 |
| Shared restrike delay | `restrike_delay`, ordinal 1..254 | `RestrikeDelay`, byte 0x6F; displayed time is ordinal × 10 seconds |

The public commands `cbus-toolkit iope-workflow output restrike-delay-time
ORDINAL` and `cbus-toolkit iope-workflow output restrike-delay-choices` report
numeric `minutes` and `seconds` from the source-pinned `FormatTimeShort`
arithmetic without reading a specification, snapshot or network. The latter
lists all 254 selectable ordinals. Stored ordinals 0 and 255 remain inspectable
but unlisted. The helpers live in `cbus_toolkit.iope_output_display`; existing
output inspection and the standalone native workflow retain their original
contracts. Localized GUI unit strings have not been recovered. This extension
has offline source-based tests, not original GUI or native-service acceptance.

Levels use the original Toolkit percentage conversion: 50% stores **127**,
not 128. Raw level editing is intentionally absent from this workflow.
The dimmer handlers compare displayed integer percentages. Raising minimum
to or above maximum raises maximum to minimum + 1 percent, capped at 100.
Lowering maximum to or below minimum lowers minimum to maximum − 1 percent,
floored at zero. Each dependent change is recorded in `derived`. An uncrossed
neighbor retains its exact raw byte, even if a percent round trip would change
it. At the endpoints, both levels can consequently be zero or 255.

For a channel containing both percentage controls, minimum executes first,
then maximum; the second selection may therefore override the first through
its dependent change. Channels execute in ascending order. Relay restrike
selections execute before the common delay edit. The delay is editable only
when at least one **existing relay** is enabled. Stored restrike bits for
absent channels or dimmers neither enable that control nor get cleared.
The relay maximum and dimmer restrike controls are refused.

Every plan snapshots the four complete parameters. Only changed parameters
are staged; unselected and inactive array elements are preserved. Masked
`RestrikeChannel` updates preserve logic association bits, logic function,
and the other bits in bytes 0x70..0x73. The application step verifies the
session identity and native schema, reconstructs the plan from canonical
controls, rejects changed/omitted dependent writes and stale PP values,
then verifies all four parameters. A staging failure restores attempted
parameters and performs no save. The caller owns a separate, explicit save
and its persistence evidence.

## Python entry point

```python
from cbus_toolkit.iope_output_settings import IopeOutputSettings

editor = IopeOutputSettings(spec)
plan = editor.plan(
    current_values,
    identity=("IOPE2C4", "1.2.00", "5752PP/2R/2D"),
    channels={1: {"min_percent": 50, "restrike": True},
              3: {"min_percent": 60}},
    restrike_delay=60,
)
# Inspect plan.as_dict() before the caller chooses to stage it.
result = editor.apply(pp_session, plan)
assert result["saved"] is False
```

`plan_from_dict` accepts the exact unsaved plan document. Replaying it cannot
bypass control eligibility, the profile, inactive-slot preservation or paired
slider writes. `show` reports the stored raw and displayed values, separate
restrike editability, and the raw delay's listed-range status.

## Original source evidence

The following original files were independently hashed during this slice.
The original vendor files and their disassembly remain private.

| Source | SHA-256 |
| --- | --- |
| CBusToolkit.exe | `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| CBusToolkit.map | `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb` |
| I_IOPE.xml | `955f26d0422bb3c02860545f9e7402da6fcbc9674f518a2434bb462df8795d13` |
| IOPE1R1.xml | `341c701fc8a57a7c4b1c8c6df322c6ec0283eb711c5b36934400a1dec7217a7f` |
| IOPE2R2.xml | `05bf0e4749b61fe487c3ca3f9ece33b1693ffbb74f9e59bedf101fe9a6d2e803` |
| IOPE2C4.xml | `87d87b091182ecfde31b66246df3b67a46adc5fefe946fd14afe99cf0547c245` |

The fresh task-6 resource extraction supplies these original resource hashes:

| Form resource | SHA-256 |
| --- | --- |
| TFRMOUTPUTTURNONLEVEL | `bb779abbdbc41768eaee2fc763157440aded9e120cd369a14893f978738e264d` |
| TFRMOUTPUTRESTRIKECHANNEL | `8cc6019e8480b04bd0ba6da40a7b02742a42ddd01108a9dac03b919070a35bf3` |
| TFRMOUTPUTRESTRIKEDELAY | `7f8f84db688fbb3904f1c07c4330ea9ee73ee593f350b8cbf1c0519ffe4eb154` |

The original MAP resolves these **virtual addresses** (not MAP segment
offsets). Method SHA-256 covers bytes from its symbol to the next distinct
MAP symbol; method tails can include embedded strings/alignment.

| Original method | Address | SHA-256 | Established rule |
| --- | --- | --- | --- |
| `TIOPECGateAgent.LoadOutputs` | 0x12D8150 | `12808b9e00b7518cda3e9ff9b1267d8eaf47860d532b889686d04a88f09f0324` | channel index > 1 loads maximum at index − 2; minimum/restrike use channel index |
| `TIOPECGateAgent.SaveOutputs` | 0x12DCCB8 | `98c33037dcfa050bedf68b7bde8b11b1de7badf93a1e9e2a94133d4597deb6a5` | minimum/restrike values saved in channel order; only indices > 1 append maxima; shared delay stores its ordinal |
| `TIOPE2C4.IsRelayChannel` | 0xD5A284 | `ee90d3cf0a3a477b182820c0c3c6a97125cb7dd5981ab607589e268eceb726ad` | zero-based indices ≤ 1 are relays |
| `TfrmOutputTurnOnLevel.SetCBusUnit` | 0x1192EE8 | `c34e003119c8e0e88004d84b2e73f545143e0c65ef4ca7d4557acff7fb04b051` | relay hides/unbinds maximum; dimmer binds maximum; initialization flag separates load from later user edits |
| `TfrmOutputTurnOnLevel.trkMinPropertiesChange` | 0x11935AC | `8c92de8ffa73de043141d2885b21d50c787585e4bcc5cec1a9d0ed862622123e` | 0x119370E..0x11937C0 implements minimum→maximum cascade |
| `TfrmOutputTurnOnLevel.trkMaxPropertiesChange` | 0x11932A8 | `c449e6106769977d2251b60a7636f4a27ce43656fbddedd0ce30102cf8f3bee7` | 0x11933AF..0x11934CC implements maximum→minimum cascade; uncrossed branch skips the neighbor write |
| `TfrmOutputRestrikeDelay.HandleRestrikeChannelClick` | 0x1194954 | `3311a3284e027c020a45e91c81f8b6377ce9346267de69950b8ac34d142a4265` | delay enablement scans relay checkbox values; dimmer rows hidden |
| `TfrmOutputRestrikeDelay.SetCBusUnit` | 0x1194AD8 | `217545348027bb1b07f4c1210d7d69ffb2df6c3f9f660cc9b78d5df6b66456b1` | only relay rows are bound, shared delay binds `RestrikeDelay` |
| `TfrmOutputRestrikeDelay.FormatTimeShort` | 0x1194D84 | `cfa51d63865eb7f90c70d4eaa913d5da0c7c4facf075df9b133dd976af831a2d` | display is ordinal × 10 seconds (minutes/remainder above 5) |

The Turn On DFM binds `MinDimmingLevel`/`MaxDimmingLevel` with
`UseRawValues=False` and slider maximum 100. The Restrike DFM binds Boolean
`Restrike`, while its delay has `UseRawValues=True`, minimum 1 and maximum
254. The shared level converters are backed by the existing independent
original-instruction vectors in
`research/fixtures/din-output-level-original-vectors.json`.

## Validation and remaining boundary

`tests/test_iope_output_settings.py` covers the three profiles, exact channel
mapping, both dependent directions and endpoints, noncanonical neighbor
preservation, hidden-bit eligibility, the delay boundaries, masked byte
preservation, stale plans, tampered plans, and uncertain-write rollback.
Run only this focused slice with:

```sh
PYTHONPATH=src:tests python -m unittest -v test_iope_output_settings
```

This is a per-control workflow, not complete `TfrmIOPE` execution. It preserves
unselected fields instead of reproducing the unrelated whole-dialog rewrites
of output recovery, inactive slots, logic groups, input blocks, scenes,
corridor/join state, `LightStateMachine`, and potentiometer expiry commands.
Output Logic associations/functions/recovery, output-group assignment,
output power-failure recovery, and all other IOPE controls remain outside
this module. No original WinForms/VCL interaction, physical controller,
lamp timing, network write, or power-cycle behavior is established here.
Native database persistence acceptance is a separate receipt.

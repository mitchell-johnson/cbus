# DIN relay and dimmer output settings

`cbus_toolkit.din_output_settings` edits the Logic, Turn On (relays) or
Min/Max (dimmers), Recovery and Restrike Delay tabs of the Toolkit 1.18
`TfrmCBusDimmer` dialog for these DIN output units at firmware 2.7.00:

| Unit type | Spec | Channels | Kind | Interlock combo | PP channel indices |
| --- | --- | --- | --- | --- | --- |
| RELDN4 | RELDN4.xml | 4 | relay | 0, 2..4 | 0..3 |
| RELDN8 | RELDN8.xml | 8 | relay | hidden | 1, 2, 3, 4, 7, 8, 9, 10 |
| RELDN8B | RELDN8.xml | 8 | relay | 0, 2..8 | 0..7 |
| RELDN12 | RELDN12.xml | 12 | relay | 0, 2..8 | 0..11 |
| DIMDN4, DIMDN4F | DIMDN4.xml | 4 | dimmer | hidden | 0..3 |
| DIMDN8, DIMDN8F | DIMDN8.xml | 8 | dimmer | hidden | 0..7 |

Every type has four logic groups, held at `GroupAddress[12..15]` and
`LightLevel[12..15]`. RELDN8 is registered with Toolkit's
`TMarshallingBoxCGateAgent`, so dialog channel *c* is PP array index
`(1, 2, 3, 4, 7, 8, 9, 10)[c-1]`; RELDN8B uses the ordinary DIN agent.

Refused before any write:

- RELDN8SP: nine channels and the marshalling agent's special group
  handling. Its dialog semantics are not admitted.
- RELAY4 and DIMMER4: these use the older `TfrmCBus1Relay*` forms with the
  `LogicGA0–5` / `LogicFunctionAndPowerUpDelay` layout.
- Any firmware other than 2.7.00 and any other unit type.

Programmable logic-engine code (for example PICED) is external software. It is
not part of the DIN Logic tab, and this editor does not handle it
(`LOGIC_ENGINE_BOUNDARY = "external"`).

## Controls and parameters

| Tab | Control | Parameter | Domain and rule |
| --- | --- | --- | --- |
| Logic | Channel logic group check boxes 1–4 | `LogicGA13..16Associations[ch]` | 0/1 |
| Logic | And/Or (relay), Min/Max (dimmer) | `LogicFunction[ch]` | 0 = And/Min, 1 = Or/Max. Editable only while the channel has an association. The stored value is never cleared. |
| Logic | Logic group selector | `GroupAddress[12+g]` | 0..255, where 255 means unassigned. Editable only while a channel associates the group. |
| Logic | Logic Auto Level Store | `LogicLevelStoreEnable[g]` | 0/1. Setting it does not force 255. |
| Logic | Logic group level | `LightLevel[12+g]` | Percent via PercentToLevel, or a raw byte. Disabled while level store is set. |
| Turn On / Min/Max | Min slider | `MinDimmingLevel[ch]` | Percent or raw byte |
| Min/Max | Max slider (dimmers only) | `MaxDimmingLevel[ch]` | Percent or raw byte. Relays hide and unbind this slider. |
| Turn On | Interlock channels | `InterLockingChannel` | Count 0 or 2..min(N,8), stored as the combo index (count − 1) |
| Recovery | Auto Level Store | `LevelStoreEnable[ch]` | Enabling it sets `LightLevel[ch]` to 255 |
| Recovery | Level slider | `LightLevel[ch]` | Percent or raw byte. Refused while level store is set. |
| Recovery | Delay slider (dimmers only) | `PowerUpDelay[ch]` | Raw 5..255. Displayed as *v* s below 60, otherwise 60 + (*v* − 60) × 10 s. Relays hide it. |
| Restrike Delay | Channel check box (relays only) | `RestrikeChannel[ch]` | 0/1 |
| Restrike Delay | Delay slider (relays only) | `RestrikeDelay` | Raw 1..254 (× 10 s). Enabled only when a channel restrikes. |

Rules reproduced from the original:

- **Percent conversion.** Percentages use the original
  `CIS_CBus.PercentToLevel` (`p*255 div 100`) and display through
  `LevelToPercent` (`(l+2)*100 div 255`). All 101 percentages round-trip. 155 of
  the 256 raw levels cannot be selected with a slider. Use `*_level` options to
  write any byte.
- **Min/Max coupling (dimmers).** If a new minimum reaches the maximum, the
  maximum moves to min+1 %. If a new maximum reaches the minimum, the minimum
  moves to max−1 %. Raw levels bypass the sliders and must satisfy min ≤ max.
- **Channels sharing a group.** A recovery percentage copies to other
  channels on the same used group whose level store is off. Logic groups on
  that group take Toolkit's x87 `Round(percent × 2.55)`. That is round-half-even
  of `percent×255/100`: 10 % gives 26, not 25.
- **Refused shared-group edits.** The following are refused because their
  re-entrant Toolkit cascades are not pinned:
  - a raw recovery level on a shared group;
  - a level-store change on a shared group;
  - a logic-group recovery or level-store edit on a group shared with channels
    or other logic groups.
- **Save validation.** A plan is refused when a channel is associated with a
  logic group that has no group address (`UnusedGroupInLogic`).

The editor changes only the parameters named in a plan. It does not reproduce
these whole-dialog save effects:

- LightLevel = 255 for every level-store channel;
- 255/0 padding of non-channel indices;
- RELDN8 zeroing of PP indices 0, 5, 6 and 11;
- relay `InterLockingChannel & 7`;
- the Synchronise Sliders and Stagger buttons.

`show` reports stored values that a Toolkit save would rewrite.

## Commands

Offline, from a PP export (`cgate unit ... export`) or a bare mapping with
`--unit-type`:

```sh
cbus-toolkit din-settings show dimmer.json
cbus-toolkit din-settings plan dimmer.json --channel 3 --min-percent 20 --max-percent 90 \
  --level-store off --recovery-percent 30 --recovery-delay 100 > plan.json
```

Against a native C-Gate PP session. The editor plans, applies, reads back and
verifies. `--dry-run` skips the save:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run din-settings --channel 3 --min-percent 20 --max-percent 90
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 din-settings --plan plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/21 din-settings --show
```

Other options:

- Logic tab: `--logic-groups 1,4|none`, `--logic-function and|or|min|max`, and
  `--logic-group G` with `--logic-group-address`, `--logic-level-store` and
  `--logic-recovery-percent|--logic-recovery-level`.
- Relays: `--restrike on|off`, `--restrike-delay` and `--interlock`.

A saved plan is stale-checked against all 15 owned parameters before any write.
If a PP write fails or its reply is uncertain, the result is reported with
`attempted_parameters`, nothing is saved, and nothing is retried. Use
`CBUS_UNITSPEC_DIR` for the decoded specifications.

## Evidence

| Evidence | What it pins |
| --- | --- |
| `research/fixtures/din-output-settings-source-review.json` | Sanitized static receipt: per-type class, agent, channel map and flags; control-to-parameter bindings with original addresses; transforms; unreproduced save effects; unresolved points. It records input hashes for the executable, map, form resources, help topics and specs. |
| `research/din_output_levels_original.py`, `research/fixtures/din-output-level-original-vectors.json` | Unicorn execution of the original PercentToLevel, LevelToPercent and Round(percent×2.55) instructions: 458 frozen rows |
| `research/fixtures/din-output-settings-native-acceptance.json` | Owned C-Gate 3.4.0.2001 acceptance on loopback. See below. |
| `tests/test_din_output_settings.py`, `tests/test_cli_din_output_settings.py` | Offline, optional-original and native tests |

The native acceptance covers all eight admitted types with no CNI or physical
access:

- 66 verified edits and 118 raw PP byte assertions.
- Invalid and boundary edits for each tab.
- A shared logic byte (`0x32+i`) read-modify-write that preserves its
  neighbour bits.
- Preservation of all 16 unrelated parameters.
- Save, project save and reload.
- Refusals for RELDN8SP 2.7.00, RELDN8 2.6.00 and DIMDN8 2.7.01, each leaving
  its values unchanged.

The native CLI test separately checks:

- that the dry-run preview equals the offline plan;
- saved-plan apply and a stale-plan refusal;
- the RELDN12 restrike and interlock settings;
- that RELDN8SP is refused;
- persistence across a project close and load.

Open items:

- Physical output behaviour: logic evaluation, interlocking, restrike timing
  and recovery after power loss.
- Original Toolkit GUI execution of these tabs.
- The `rgLogic` value order (inferred from column order).
- Live re-enabling of the restrike delay slider.
- The re-entrant shared-group cascades refused above.
- Other firmware revisions, RELDN8SP, RELAY4/DIMMER4 and the other
  `TfrmCBusDimmer` users (RELDC4, RELDB1, RELSM8, RELDF1, DIMDS8, DIMPR*,
  DIMDU*, ANODN4).

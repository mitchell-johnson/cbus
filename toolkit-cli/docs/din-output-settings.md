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

By default the editor changes only the parameters named in a plan. Add
`--toolkit-save` to include the recovered DIN agent-save projection after the
requested edits. The flag can be used alone to plan the save of unchanged
settings. It does not reproduce a complete initialized Toolkit form or its
implicit callbacks.

For the seven ordinary DIN profiles, the save writes 255 to each level-store
channel, pads `GroupAddress[N..11]` with 255 and `LightLevel[N..11]` with zero,
and masks relay `InterLockingChannel` with 7. The logic recovery values at
indices 12..15 retain their own values, even when logic level store is enabled.

RELDN8 uses a different ordered marshalling save. Its active channel indices
are 1,2,3,4,7,8,9,10. The marshalling step overwrites the basic save's recovery
levels with the loaded channel model, so untouched recovery bytes can survive
when level store is enabled. An explicit supported level-store control edit
still takes its earlier control effect. Slots 0,5,6 are cleared in the
marshalled arrays (255 for group addresses). Slot 11 is zero in `LightLevel`
and 255 in `GroupAddress`; other 12-element channel arrays retain their
original slot 11 because the final short assignment only replaces the prefix.
`MaxDimmingLevel` saves in dialog order: its four stored values become original
indices 1,2,3 followed by zero. A later explicit save can therefore change it
again. The CLI performs one projection and never repeats it to seek a stable
result. The historical source-review summary's blanket slot-11 zeroing and
level-store wording is superseded for this opt-in path.

The normalized plan uses a separate version-2 format, retaining its original
snapshot and pre-save edits so application can reproduce the ordered
projection. A malformed or altered normalization result is refused. Existing
version-1 targeted plans remain usable. All owned parameter values are checked
for staleness before staging either format.

The ordered Synchronise and Stagger controls below cover Turn On/Min-Max and
recovery delay. Recovery-level synchronization/staggering, re-entrant
shared-group control histories, group-object creation and complete GUI
initialization remain open.
`show` reports the stored values and recovery-level rewrite hints; it is
not a preview of every ordered RELDN8 save effect. Use `plan --toolkit-save` for that
preview.

## Ordered slider controls

Use `--controls FILE` with a JSON array to retain the order of slider edits,
Synchronise checkboxes and Stagger buttons. Both offline `din-settings plan`
and database `cgate unit ... din-settings` accept the file. Direct edit flags
cannot be combined with a control history. Add `--toolkit-save` when the same
plan should include one final agent-save projection.

| Operation | Fields | Available profiles |
| --- | --- | --- |
| `synchronise` | `tab`: `turn-on` or `recovery`; `enabled`: Boolean | Every admitted profile |
| `minimum` | `channel`, `percent` | Every admitted profile |
| `maximum` | `channel`, `percent` | Dimmers |
| `recovery-delay` | `channel`, `raw` from 5 to 255 | Dimmers |
| `stagger-minimum` | `step_percent` | Dimmers |
| `stagger-maximum` | `step_percent` | Dimmers |
| `stagger-turn-on` | `step_percent` | Relays |
| `stagger-recovery-delay` | `step_seconds`: 5, 10, 20 or 30 | Dimmers |

Channels are numbered from one in dialog order, including RELDN8's remapping.
Percentages range from 0 to 100. A percentage stagger step ranges from one
to the integer part of 100 divided by the channel count. Both Synchronise
checkboxes start off for each explicit history.
The relay Recovery checkbox can be retained in the history, but its level and
level-store callbacks are not admitted here; it does not enable a relay delay.
Delay operations require every active stored `PowerUpDelay` to be at least
five. The implicit loading callbacks for smaller stored delays remain unproved.

For example, this history enables synchronized Min/Max sliders, moves channel
one's minimum to 30 percent and then staggers the recovery delays:

```json
[
  {"op": "synchronise", "tab": "turn-on", "enabled": true},
  {"op": "minimum", "channel": 1, "percent": 30},
  {"op": "stagger-recovery-delay", "step_seconds": 20}
]
```

```sh
cbus-toolkit din-settings plan dimmer.json --controls controls.json --toolkit-save > plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run din-settings --plan plan.json
```

The history preserves control behavior that differs from raw parameter edits.
Assigning a slider its existing displayed position emits no change: a stored
raw level of 26 displays as 10 percent and survives an assignment of 10.
Synchronized Min/Max edits preserve the order of coupled callbacks. Stagger
sets channels in order while suppressing synchronization notifications; local
Min/Max coupling still applies. Relay Turn On staggering writes the minimum
threshold. Minimum/Turn On steps ascend from one step; maximum steps ascend
to 100 percent. The largest Turn On step choice also forces the last channel
to 100 percent, including cases where the channel count does not divide 100.
Delay staggering uses the original conversion above 60 seconds;
eight channels at a 20-second step produce raw values
`20,40,60,62,64,66,68,70`.

The history plan contains `operations`, `initial_controls`, `final_controls`,
`control_history` and its nested `settings_plan`. Applying an imported plan
replays the history and checks the complete result before PP staging. Inspect
the final changes and optional save normalization before applying. This is an
explicit control history; implicit initial form notifications and recovery
level/group callbacks are outside its admitted scope.

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

To include agent-save normalization in an offline plan or a database edit:

```sh
cbus-toolkit din-settings plan dimmer.json --toolkit-save > save-plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run din-settings --toolkit-save
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  din-settings --plan save-plan.json
```

The dry run stages and verifies the plan but does not save it. Database PP save
and explicit project save remain separate, and neither establishes physical
programming or power-cycle persistence.

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
| `research/fixtures/din-output-controls-source-review.json`, `research/din_output_controls_static.py` | Static method, form and VMT bindings for ordered slider controls, guard/coupling order and the exact extended delay constant. The reproducer reads pinned bytes without executing them. |
| `research/fixtures/din-output-save-source-review.json` | Source-pinned ordinary and marshalling save order for the opt-in projection; short-array effects and the historical summary correction. No new original instruction execution. |
| `research/fixtures/din-output-settings-source-review.json` | Sanitized static receipt: per-type class, agent, channel map and flags; control-to-parameter bindings with original addresses; transforms; unreproduced save effects; unresolved points. It records input hashes for the executable, map, form resources, help topics and specs. |
| `research/din_output_levels_original.py`, `research/fixtures/din-output-level-original-vectors.json` | Unicorn execution of the original PercentToLevel, LevelToPercent and Round(percent×2.55) instructions: 458 frozen rows |
| `research/fixtures/din-output-settings-native-acceptance.json` | Owned C-Gate 3.4.0.2001 acceptance on loopback. See below. |
| `tests/test_din_output_settings.py`, `tests/test_cli_din_output_settings.py` | Offline, optional-original and native tests |
| `tests/test_cli_din_save.py`, `tests/test_cgate_din_save_interop.py` | New public offline CLI and owned Rust database save/reload, preservation, plan-refusal and lost-reply cases |
| `tests/test_din_output_controls.py`, `tests/test_cli_din_controls.py`, `tests/test_cgate_din_controls_interop.py` | Literal ordered control histories, replay/schema guards, public CLI and both owned database backends |

The historical native acceptance covers the targeted edit path for all eight
admitted types with no CNI or physical access. It predates `--toolkit-save`:

- 66 verified edits and 118 raw PP byte assertions.
- Invalid and boundary edits for each tab.
- A shared logic byte (`0x32+i`) read-modify-write that preserves its
  neighbour bits.
- Preservation of all 16 unrelated parameters.
- Save, project save and reload.
- Refusals for RELDN8SP 2.7.00, RELDN8 2.6.00 and DIMDN8 2.7.01, each leaving
  its values unchanged.

The historical native CLI test separately checks:

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

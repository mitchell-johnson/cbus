# Wireless gateway remotes, WRM globals and the learn boundary

Three modules cover the wireless work that can be done without a radio:

- `cbus_toolkit.wireless_gateway` edits the Remote Switch mapping of the
  *C-Bus Wireless to wired gateway (2.x)* dialog (help topic 13876).
- `cbus_toolkit.wireless_unit_globals` edits the Learn Mode group of the Neo
  retrofit (WRM) wireless units. It also offers spec-level house-code and
  key-mask edits.
- `cbus_toolkit.wireless_commissioning` reproduces the commands C-Gate composes
  for `NET LEARN` and the wireless unit actions. It performs no I/O.

None of these pairs a device, learns a house code or transfers anything over
the radio. The rules come from a sanitized static review of Toolkit 1.18.0.2754
and C-Gate 3.4.0.2001 (see [Evidence](#evidence)). Nothing was executed in the
original Toolkit.

## Gateway Remote Switch mapping

Admitted: **WGATE5F firmware 2.2.90..2.4.99** with `WGATE5X_2.xml`. Toolkit
registers only this identity with `TCBusWirelessGatewayAdvancedUnit`. That
class's `TCBusWirelessGatewayAdvancedCGateAgent` loads and saves the Mode
control and the Remotes tab.

Refused before any write:

- **WGATE5N at any firmware.** Toolkit uses `TCBusWirelessGatewayUnit`, which has
  no Remote Switch mode or Remotes tab. This applies even though C-Gate
  exposes the same 68 parameters from `WGATE5X_2.xml`.
- **WGATE5F below 2.2.90.** These units use `WGATE5X.xml`, which has 30
  parameters and no remote table.
- **Any other unit type or firmware.**

### Controls and parameters

| Control | Parameter | Rule |
| --- | --- | --- |
| Mode (Network Gateway / Remote Switch) | `MapWirelessRemotes` | Item index 0/1. The Remotes tab is visible only in Remote Switch mode, so remote edits need that mode. Toolkit fills in a network default when Application 1 is 255; that switch is refused (see below). |
| Remote Control *N* (1..8) | `RemoteIdentityN` | 32-bit serial stored little-endian. `FF FF FF FF` means no remote. `--serial none` clears the remote. |
| Key Function | `KeySceneMaskN[slot]` | Group Dimmer = 0. Scene Set / Scene Toggle = 1. |
| Application switch | `ApplicationSecondayN[slot]` | Group keys only: 1 = secondary application. The switch is disabled while `Application[1]` = 255. Scene keys write 0. |
| Key Assignment (group) | `GroupAddressN[slot]` | Group 0..254, or 255 (none). |
| Key Assignment (scene) | `GroupAddressN[slot]` | `(scene − 1) << 4` plus 1 (Scene Set) or 6 (Scene Toggle). The scene must be configured and have a trigger group. |

**Keys and slots.** Each remote has 16 PP slots. The dialog shows 10 keys
(two groups of five).

- While a remote is selected, dialog key *k* uses slot
  `WTXU_KEY_MAP[k−1]` = `(5, 4, 3, 2, 1, 13, 12, 11, 10, 9)`, counting slots
  from 1. This is the WTXU remote map; the six other slots are hidden.
- Without a remote, Toolkit uses the identity map and disables every key, so
  `--remote-key` needs an assigned remote.
- `--remote-slot S=…` writes a raw slot 1..16 and is reported as
  `raw_slot_edits`.

**Scenes.** Scene *n* is configured if `SceneVectorOffset` has at least *n*
entries that are not 255 and satisfy `(v & 0x7F) < 100`. Scene keys also need
`SceneTriggerGroup[n−1]` ≠ 255. The editor does not decode scene vectors, so
Toolkit's check that a scene vector is non-empty is not reproduced.

The editor changes only the parameters named in a plan. It does not reproduce
these whole-dialog save effects, and `show` reports stored values that a
Toolkit save would rewrite:

- all 8 identities and 128 slots rewritten on every save;
- scene-key `ApplicationSeconday` forced to 0;
- scene commands other than 1 saved as 6 (Toolkit loads them as Scene
  Toggle);
- slots loaded without a remote saved through the WTXU map;
- scene tables rewritten by `SaveScenes`;
- Connection-tab parameters rewritten by the base agent;
- the Remote Switch cascade that assigns the network's default Lighting or
  Heating application to an unassigned Application 1 and gives every
  group-less key group 255;
- creation of project remote-control units, groups and scenes.

Connection-tab parameters (`Application`, `ApplicationConnectEnabled`,
`SynchroniseToWired`, `ForwardingMode`, `ForwardingRoute`,
`StatusMonitorApplication`) are not edited. `ForwardingRoute` depends on the
project's bridge topology; its save rule is recorded in the source review.

## WRM unit globals

Admitted: WRM2D1, WRM2R1, WRM4D1, WRM4D2, WRM4R1, WRM4R2, WRM8D1, WRM8D2,
WRM8R1 and WRM8R2 at firmware 2.0.0..2.4.99, each with `<type>_2.xml`.
Toolkit uses the `TWRM<type>` (`TCBusWirelessInputUnit`) classes for these
units.

Refused before any write:

- the EZ variants (`TnmWRDX`);
- firmware below 2.0.0 (other classes and 1.x specifications);
- WRB, WRP and other wireless families.

| Control | Parameter(s) | Rule |
| --- | --- | --- |
| Allow Learn Mode + Current/Any Application Learn (`--learn-mode off/current/any`) | `LearnAllowed`, `LearnMasterMode` | off = 0/0, current = 1/0, any = 1/1. The radio buttons are disabled while learn is off. |
| Allow Network Learn | `LearnNetworkAllowed` | Copies the check box. |
| Reset (learn history) | `LearnedFlag` | Clears the flag. Enabled only while the unit has learned; otherwise refused. |
| House Code (read-only in Toolkit) | `HouseCode` | Displayed as eight hex digits `b3 b2 b1 b0`. `--house-code` parses the same order. Not a Toolkit control. |
| Key masks (no Toolkit control) | `KeyEnableMask1..4`, `KeyMaskAllowed`, `KeyMaskSave` | 16-bit masks and bytes. A Toolkit save writes 0xFFFF / 0 / 0 (`SaveKeyMask`). |

Plans list house-code and key-mask edits under `beyond_dialog`. These are
spec-level edits, not reproduced Toolkit controls. The Key Set Control tab
writes `KeyOffset*`, not the masks, and is not edited here.

## C-Gate learn and unit-action boundary

`wireless_commissioning` rebuilds the command bodies C-Gate composes (`aW.e`,
before PCI framing):

| C-Gate command | Command body (unit 0x14) | Reply |
| --- | --- | --- |
| `NET LEARN <net> <app> <grade> <group>` | `\05 <app> 00 03 <grade> <group> <check>`, where `check` = −(grade+group) mod 256. For example, `\05380003010AF5`. | None |
| `DO <unit> MAISync` | IDENTIFY 0xFE: `\46140021FE` | 8 bytes |
| `DO <unit> ResetOpStats` | CAL 0x08: `\46140008` | None |
| `DO <unit> RecallOpStats` | four 12-byte reads, `\4614002A000C` … `\4614002A240C` | 48 bytes → 12 LE counters |
| Status properties | IDENTIFY 0x50..0x53 | Text |

`NET LEARN` accepts only grades 1, 2 and 0x80..0x83 (init relay, init dim,
cancel, exit relay, exit dim, exit area).

All of these need a live network. The effects and replies exist only in the
physical wireless units and in their learn range. The Rust cmqttd does not
implement them.

## Commands

Offline, from a PP export or a bare mapping with `--unit-type` and
`--firmware`:

```sh
cbus-toolkit wireless gateway show gateway.json
cbus-toolkit wireless gateway plan gateway.json --mode remote-switch
cbus-toolkit wireless gateway plan gateway.json --remote 2 --serial 0x10203 \
  --remote-key 1=group:7:secondary --remote-key 2=scene-toggle:1 --remote-slot 16=group:none > plan.json
cbus-toolkit wireless globals plan wrm.json --learn-mode current --network-learn off --house-code 00c0ffee
cbus-toolkit wireless boundary --unit 20 --learn 56 1 10
```

Assignments use `group:G[:primary|secondary]`, `group:none`, `scene-set:N` or
`scene-toggle:N`.

Against a native C-Gate database unit. Physical destinations are refused. The
editor plans, applies, reads back and verifies; `--dry-run` skips the save,
and `--plan` stale-checks every owned and dependency parameter first:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 wireless-gateway --show
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 --dry-run wireless-gateway \
  --remote 1 --serial 66051 --remote-key 3=group:12:secondary
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 wireless-gateway --plan plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/31 wireless-globals --learn-mode off
```

If a PP write fails or its reply is uncertain, the result reports
`attempted_parameters` and nothing is saved or retried. Use
`CBUS_UNITSPEC_DIR` for the decoded specifications.

## Evidence

| Evidence | What it pins |
| --- | --- |
| `research/fixtures/wireless-source-review.json` | Sanitized static receipt covering: profile registrations; attribute offsets; control-to-parameter rules with original addresses; the WTXU key map; scene encoding; dependencies; save order; unreproduced save effects; the ForwardingRoute rule; the WRM learn/house-code/key-mask rules; unresolved points. It records hashes of the executable, map, catalogue, form resources, help topics and specs. |
| `research/fixtures/wireless-cgate-boundary.json` | C-Gate class hashes, command templates, examples and why each action needs a live network. No command was executed. |
| `research/fixtures/wireless-gateway-native-acceptance.json` | Owned C-Gate 3.4.0.2001 on loopback. WGATE5F at 2.2.90 and 2.4.00: 10 verified edits and 36 raw PP byte assertions, invalid and boundary edits, preservation of unrelated parameters, save, project close and reload with identical values and raw image. Refusals for WGATE5N 2.4.00 and WGATE5F 2.2.89 leave values unchanged. |
| `research/fixtures/wireless-unit-globals-native-acceptance.json` | All ten WRM types (2.0.0, 2.4.00 and 2.4.99): 60 verified edits and 120 raw byte assertions, save/close/reload. Refusals for WRM2D1EZ, WRM2D1 1.11.0 and WRB2D1. |
| `tests/test_wireless_gateway.py`, `tests/test_wireless_unit_globals.py`, `tests/test_wireless_commissioning.py`, `tests/test_cli_wireless.py` | Offline, native and CLI tests. The native CLI test covers dry-run preview, saved-plan apply, stale refusal and the database-only guard. |

Open:

- Physical learn/join outcomes, radio pairing, house-code transfer and gateway
  forwarding.
- Original Toolkit GUI execution of these tabs.
- Project remote-control unit/group/scene creation, the Remote Switch
  Application 1 cascade and Scenes tab editing.
- The non-empty scene-vector check.
- Remote classes other than WTXU.
- The Network Gateway Connection tab.
- WRB/WRP/WRD, EZ and 1.x wireless units.
- Decorator wireless dialogs.
- cmqttd wireless support.

# Old Bytecraft body and action static recovery

This source-only slice continues the accepted old DIMPR12 output dependency
receipt. It uses the same pinned Toolkit EXE/MAP hashes and the retained
Bytecraft assessment. It neither executes original instructions nor admits
DIMPR12L1 firmware 1.9.03 and later. Existing project group and selector objects
must establish exact identity and names; the static report does not justify
synthesizing project labels. Original PP loading, page capture, GUI history,
whole-page bytes and visual acceptance remain untested.

The new reproduction script is
`research/project_documentor_bytecraft_body_static.py`; its receipt is
`research/fixtures/project-documentor-bytecraft-body-static.json`. The receipt
stores bounded method hashes, sizes, decisive checks and public report text.
It does not store original instruction bytes, host paths or UI coordinates.

## Consumer order and control bindings

`DocumentHTML` calls the base unit documentor directly before its Bytecraft
class guard. Both summary control groups resolve through the original agent's
Enable Control application helper, hence application 203. The helper looks up
the requested address with add=true, falling back to address255 only when the
first returned object is null. Address255 remains a real unused group object.
Channel output groups and the inherited Area group bind in the primary
application, with add=true in the original loader. A read-only adapter can
require these objects already exist, including unused groups.

The exact body prefix consists of these separate writer lines, where group
display uses the shared original group formatter:

```text
C-Bus Lock Enable Group: {disable group}<br />
DMX Enable Group: {DMX switch group}<br />
Control Failure Scene: Enabled<br />
Control Failure Scene Ramp Rate: {scene0 on ramp}<br />
<br />
<table border="1">
```

When RestoreMode is false, the enabled line and ramp line are replaced by one
`Control Failure Scene: Disabled<br />` line. The two control-group summaries
remain unconditional, even when their group is unused.

The channel header starts with the original **prefix** `</tr>`:

```text
</tr><tr><th>Channel</th><th>Groups</th><th>Logic Function</th><th>Curve</th><th>Min</th><th>Max</th>
```

Append `<th>C-Bus Lock</th>` iff the disable group is used, then always
`<th>Max RMS Voltage</th>`. Append
`<th>DMX</th><th>Take|Update</th><th>C-Bus Fade</th><th>DMX Fade</th>` iff
the DMX switch group is used. Append `<th>Restore Level</th>` iff RestoreMode.
The header has no closing-row suffix: the original three-string concatenation
prepends `</tr>` before the accumulated header. Every channel row preserves
the same prefix behavior.

## Channel rows

Iterate all twelve channel objects in order. Skip a channel iff its output
group is unused **and** its DMX patch is zero. This filter is independent of
the DMX switch group's usage. A patch can keep a channel row present while
the DMX columns remain hidden.

Start each row with
`</tr><tr><td>{channel index+1}</td><td>{output group}</td><td>&nbsp;</td>`.
Old TDIMPR12 has no logic collection, so its Logic Function cell is always
`&nbsp;`; the L1 logic branches are not admitted.

For a used output group, append curve description, minimum percentage,
maximum percentage, optional C-Bus Lock `Yes`/`No`, and maximum RMS voltage.
Maximum voltage255 renders `LINE`; the original voltage setter also maps0
to255. For an unused output group, append an optional lock `&nbsp;` cell
**before** four further `&nbsp;` cells. Preserve that order even though the
header names curve/min/max before lock.

If DMX columns are present, patch0 appends one cell containing
`&#60;Unused&#62;` followed by three `&nbsp;` cells. A nonzero patch appends its
decimal value, `Update` iff the switch action flag is true (otherwise `Take`),
the CbusDMXSwitchOverFadeTime description, then DMXCbusSwitchOverFadeTime.
If RestoreMode is true, append scene0's on level percentage iff that channel
is included in scene0's on set; otherwise append `&nbsp;`. The restore cell
does not separately test the output group. Channel rows have no closing-row
suffix. Finish the channel table with its own `</table>` writer line.

## Scene appendix

The exact next writer lines are:

```text
Scenes: <br />
<table border="1"
<tr><th>Scene</th><th>Scene Type</th><th>Trigger</th><th>Scene On</th><th>Scene Off</th></tr>
```

The table opening deliberately lacks its closing angle bracket. Iterate scene
indexes1 through32, skipping unused scenes. Emit separate
`<tr><td>{index}</td>` and `<td>Advanced</td>` or `<td>Basic</td>` lines. Advanced
trigger display is `<td>{recall group display}</td>`; Basic is
`<td>{exact recall selector level display}</td>`. Link group is not displayed.

When any channel is included in the scene's on set, open the on cell with
`<td><table border="1">`, then
`<tr><th>Group</th><th>Level</th><th>Ramp Rate</th></tr>`. Iterate channels in
order and emit entries only when inclusion is true and that output group is
used. Entry grammar is
`<tr><td>{group}</td><td>{percent}%</td><td>{on ramp}</td></tr>`;
these nested rows use a normal closing suffix. Emit `</table>` and `</td>`
as separate lines. If no on inclusion exists, emit `<td>&nbsp;</td>`.

The off cell uses the same grammar, off inclusion, off levels and off ramp,
but it opens the subtable only when the scene is Advanced **and** has any off
inclusion. Otherwise emit `<td>&nbsp;</td>`. Always finish the outer scene
with a separate `</tr>`, then after all scenes emit `</table>` with no trailing
break. Inclusion in an unused output channel still makes the scene/on/off
set used; it can therefore produce a header-only nested table. Repeated output
groups retain repeated rows. Scene unused tests only absence of all on and
off inclusion, without testing levels, mode, trigger or output group usage.

## Actions and dependency identity

ActionSelectorUse calls base first, checks the Bytecraft class, and scans all
scene indexes0 through32 in order. It skips unused scenes. Advanced mode
compares the scene recall group object with the queried level's group object,
ignoring selector identity. Basic mode compares the exact recall level object.
Append `<li />Advanced Trigger Scene {index}` or
`<li />Trigger Scene {index}` for every qualifying scene, including scene0.
There is no first-match break or deduplication.

Input dependencies call inherited common input first, then scan channel-major
and scene-minor with all scene indexes0 through32. The queried object must be
the exact output channel group. A qualifying used scene includes that channel
in either on or off, irrespective of Basic/Advanced mode. Its recall group
nonnull and used yields `Scene {index+1}|`; otherwise it yields
`Scene {index+1} (Unused)|`. Off inclusion contributes even for Basic scenes
whose body hides the off subtable.

Other dependencies route through the actual TDIMPR12 slot to Bytecraft Other,
which first calls TGOC Other. TGOC calls common Other, then appends
`Area Group|` on exact primary Area object identity. Bytecraft next appends
`C-Bus Disable Group|`, then `DMX Switch|` on exact Enable group identity.
These identity checks do not suppress unused group255.

## Packed fields and descriptions

| PP field | Exact consumer mapping |
| --- | --- |
| Application / GroupAddress | Primary application and twelve output group addresses. |
| AreaGroupAddress | One group address in the primary application; inherited Other only. |
| CBusDisableGroupAddress / DMXCBusSwitchAddress | Group addresses in Enable Control203. |
| DMXPatchInfo | Twenty-four bytes; channel patch = even-byte high plus odd-byte low. |
| ChannelMinLevel / ChannelMaxLevel | Twelve direct values each. |
| MaxChannelVoltage | Twelve direct values; zero setter normalization produces255. |
| ChannelDimmerCurve | Six packed bytes; even channel uses low nibble, odd uses high. |
| DMXCbusSwitchOverFadeTime | Six packed bytes, same nibble order; DMX Fade column. |
| CbusDMXSwitchOverFadeTime | Six packed bytes, same nibble order; C-Bus Fade column. |
| CBusDisable | Sixteen single-character0/1 tokens; effective bit c = raw token(c+8)%16. |
| DMXCbusSwitchOverActionAndRestoreMode | Same half rotation; channel c uses effective bit c; RestoreMode uses effective bit15, raw token7. |
| PresetRec00..32 | Complete scene decoder owned by the companion loader slice; scene0 supplies restore data. |

The bit helper asserts trimmed text length31, then concatenates
`Copy(raw,17,15) + ' ' + Copy(raw,1,15)` and compares the selected character
with `'1'`. Canonical sixteen single-character values reproduce that behavior;
arbitrary whitespace/malformed strings remain outside this adapter admission.

Curve ordinals0..5 have exact descriptions `Lite 1`, `Lite 2`, `Lite 3`,
`Non Dim`, `Lin RMS`, `1:1`. Enumerated assignment raises `Invalid value`
outside the type's range; it does not clamp invalid curve nibbles. Fade/ramp
ordinals0..15 have descriptions `Instantaneous`, `4 s`, `8 s`, `12 s`, `20 s`,
`30 s`, `40 s`, `1 min`, `1.5 min`, `2 min`, `3 min`, `5 min`, `7 min`,
`10 min`, `15 min`, `17 min`. Do not use ordinary key ramp labels for Bytecraft.
Admitted byte levels convert to percent by `((level+2)*100)//255`.

Direct patch/min/max setters pass integer Variants to integer attributes,
without direct clamping. The byte pair forms a word0..65535. Any narrower
patch limit imposed by a read-only adapter is an explicit admission boundary,
not an original setter clamp. Fresh integer attributes have equal default
range endpoints, which bypass the generic range check; arbitrary callbacks,
later range mutations or retained GUI history are not claimed.

The shared group formatter escapes angle brackets numerically only for unused
groups and displays their actual name. Used group and level names are inserted
raw by their original display methods. Level anchors use the selector object's
Address, not its Value. Existing objects/names remain necessary; the receipt
does not prove an auto-created name policy.

## Correction and reproduction

The retained assessment's Boolean hazard omitted the original `SETG DL`
instructions following both on/off mask operations. Channels8..11 therefore
retain inclusion. Mode similarly uses `DEC`/`SETE`, so Advanced means record0
equals1. Keep the old assessment immutable and use this new evidence as the
correction; the companion loader receipt pins the complete packed scene rules.

```sh
PYTHONDONTWRITEBYTECODE=1 python research/project_documentor_bytecraft_body_static.py \
  --executable "$CBUS_TOOLKIT_EXE" --map-file "$CBUS_TOOLKIT_MAP" \
  --output research/fixtures/project-documentor-bytecraft-body-static.json
```

This command reads and statically verifies the supplied pinned original files.
It does not execute original instructions, install software, build binaries,
access hardware or perform a full repository test suite.

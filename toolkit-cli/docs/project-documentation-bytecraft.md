# Old DIMPR12 project report

The body admits the original TDIMPR12 / TDIMPR12CGateAgent firmware profile
0 through 1.9.02. It requires complete explicit PresetRec00–32 and consumed PP
fields. DIMPR12L1 and DIMPR12A use separate classes and remain excluded. This is
a fresh saved-snapshot consumer projection, not original full-loader execution.

Channel groups bind in the primary application. Both C-Bus Lock and DMX Enable
summary groups bind in Enable Control application 203. Named groups and Basic
scene selector objects must already exist in the supplied project, including
actual unused group objects. Basic selector links use Address and preserve the
original tag, independently of Level Value. Missing metadata leaves a partial
marker instead of inventing original auto-created names.

The table scans twelve channels in order and skips a channel only when its
output group is unused and its DMX patch is zero. A nonzero patch retains an
unused output channel even when the DMX columns are hidden. Old TDIMPR12 has no
logic collection, so its Logic cell is `&nbsp;`. Lock, DMX and restore columns
follow their independent native gates. Scene zero supplies restore ramp and
included on levels. Scenes 1 through 32 form the appendix; Basic scenes suppress
the Off table even if off inclusion makes the scene used. Inclusion in unused
output channels can produce a header-only nested scene table.

Consumed body fields use these exact mappings:

| PP | Projection |
| --- | --- |
| Application / GroupAddress | First application and twelve channel group identities |
| CBusDisableGroupAddress / DMXCBusSwitchAddress | Application-203 groups |
| DMXPatchInfo | Twelve high-byte/low-byte words, 0 through 65535; no native setter clamp |
| ChannelDimmerCurve | Twelve low-even/high-odd nibbles from six bytes; used-channel ordinals 0–5 |
| ChannelMinLevel / ChannelMaxLevel | Twelve bytes, displayed as `(level + 2) * 100 // 255` percent |
| MaxChannelVoltage | Twelve bytes; both 0 and 255 display LINE |
| CBusDisable | Sixteen canonical text bits, halves rotated; channel bit c reads input bit `(c + 8) % 16` |
| DMXCbusSwitchOverActionAndRestoreMode | Same text-bit rotation; channel Update/Take and bit 15 restore (input bit 7) |
| CbusDMXSwitchOverFadeTime / DMXCbusSwitchOverFadeTime | Six packed bytes each; C-Bus and DMX fade descriptions respectively |

Text-bit PP requires sixteen single-character 0/1 values separated by one space.
It is not a pair of packed bytes. Curves, lock bits, levels and voltages are
unconsumed when no used output group is displayed. Fades are unconsumed when
DMX is disabled or every patch is zero. Consumer omission does not prove that
the original whole loader accepted missing or malformed unconsumed fields.

The body preserves original markup quirks: `</tr>` prefixes the channel header
and each channel row; the scene table starts with `<table border="1"` missing
its closing angle bracket. It uses Bytecraft's own curve/fade descriptions,
including Instantaneous and 17 min, and the original escaped unused text. These
are pinned source rules, without whole-page visual or byte acceptance.

The loader receipt has 67 exact static checks and reproduces thirteen prior
assessment spans. The body receipt has 122 exact checks across 34 methods.
Focused software tests cover field/metadata gates, bit rotation, words/nibbles,
scene-zero restore, named-selector identity, empty nested tables and ordered
actions/dependencies. Original PP execution, defaults outside explicit records,
retained history, locale/order preferences and generated-page capture remain
unassessed.

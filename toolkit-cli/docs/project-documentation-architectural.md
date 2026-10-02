# Architectural dimmer project reports

`cbus-toolkit project document` and the read-only C-Gate database report can
document saved architectural dimmer programming. The admitted Toolkit factories
are `DIMAR3`, `DIMAR6`, `DIMAR12` and `C12DIMAR`, within their source-registered
firmware interval `0` through `9`. They have 3, 6, 12 and 12 output channels and
four logic groups. Factory and firmware admission uses the existing exact
registry; a similar-looking type or an unproved firmware does not inherit this
support.

The implementation recovers the complete per-unit `DocumentHTML` body for an
admitted fresh snapshot. It covers output and associated logic groups, logic
operation, all eleven dimming curves, fan kickstart, minimum and maximum
levels, fixed-cache RMS voltage, turn-on threshold and the four C-Bus masks;
DMX patching, masks, enable fade, disable operation and duration; all ordinary
scene rows; Panic/Dry Contact 1–3, Load Shed, C-Bus Loss and Halogen Clean
special rows. It also implements the original input, output and other group
descriptions and action selector use. This is source reconstruction with
literal tests, rather than an original generated-page comparison.

## Saved data and consumption

The adapter consumes explicit saved programming strings and existing project
objects. It does not populate missing values from a private unit specification,
guess a catalogue default or create missing native groups and Levels. A missing
consumed field or unresolved display link produces a bounded partial report.
The unit-specific body is computed before it is appended, so a failed body does
not leave half a channel or scene table in the output. Base unit metadata can
still appear with an explicit unrecovered marker.

Primary application comes from the inherited `Application` programming field.
Output channels use the beginning of `GroupAddress`; the four logic groups use
entries 13–16 even on three- and six-channel units. `ChannelOutputGroups` is a
separate constructor attribute and does not supply these report groups.
`LogicGA13Associations` through `LogicGA16Associations` and `LogicFunction`
retain native nonzero Boolean behavior. Native C-Bus masks are inverted after
Boolean normalization; DMX masks are direct.

DMX patches are little-endian words from `DMXChannelMapping`. With an unused
DMX enable group, `DMXChannelMaskCurrent` can force a patch to zero. With a used
enable group, the extended DMX columns appear even for a zero patch. A zero
patch renders `&lt;DMX Disabled&gt;`. Take C-Bus uses the raw off-fade duration;
Update C-Bus uses the source-pinned ramp description. Input group use preserves
one `DMX Disable Update C-Bus Level` description per matching channel, including
duplicates, when the global mode and allocated mask-Level guards admit it.

Native Boolean arrays admit explicit stored bytes and normalize every nonzero
byte to true. Byte programming consumes only the explicit `0..255` domain.
Integer line voltage, fan kickstart, DMX fades and special scene durations admit an explicit
`0..65535` word domain here; this is an adapter boundary, not a claimed vendor
specification range. Unknown consumed ramp ordinals refuse. Unconsumed channel
names, logging counters, editable curve points and other settings do not become
new mandatory fields merely because the original agent loads them.

## Voltage and scenes

Maximum RMS voltage uses the unit constructor's fixed 42-point cache A.
Editable `DimmingCurveAX/AY/BX/BY` are independent objects and do not change this
report conversion. The projection interpolates from the implicit zero origin,
uses round-to-even for normalized voltage, then truncates the product of that
result and nominal line voltage divided by 255. Exact table points and all
interpolation tests are retained. A converted voltage equal to line voltage is
rendered as `LINE(value)`.

Ordinary scenes occupy **128 sparse saved slots**, not 32. The loader consumes
`SceneUsed`, `SceneHasName`, `SceneNormal` and `SceneUsesRampRate`, then only the
used `SceneNNNData` and required `SceneNNNName` fields. Names use the original
trim rule and a maximum of 38 UTF-16 code units. A prefix that splits a surrogate
refuses: the original output encoder's replacement behavior has not been
established. An unnamed scene starts as `New Scene`.

Each used scene has a trigger group and selector Address, followed by one
four-byte record per channel. Its two fade bytes form a little-endian word;
the unused flag is bit 3, and the lower three flag bits retain inhibit state.
Targets scale from 254 to 255 before percentage rendering. Prepared ordinary
SceneGroups preserve channel order and deduplicate group identity: the first
channel for a group supplies its target, fade and inhibit values. Group 255
can remain an ordinary SceneGroup and render as the original unused group.

Crossfade uses the first channel's packed fade word. The top two bits select
seconds, ten seconds, minutes or zero; the remaining bits supply the count.
Normal scenes display a ramp name when `SceneUsesRampRate` is true, or the
unchanged packed integer when it is false. Group-use and selector-use numbering
uses the compressed scene collection order, so used saved slots 1, 33 and 128
are described as scenes 1, 2 and 3.

The five special raw level arrays omit entries equal to 255. Other entries use
the same target scaling and appear as channel rows, with C-Bus Loss fade and
Halogen fade/duration where consumed. The fresh native loader prepares ordinary
SceneGroups **before** loading special SceneChannels. It never prepares the
special SceneGroups afterward. The report therefore shows special channel rows
while a fresh input-dependency projection does not infer special group-use
labels from those rows.

There is a second observable distinction: the unit's Halogen selector and the
Halogen special scene's selector are separate references. The fresh loader
assigns the former, and the HTML body reads it. Action-selector use reads the
latter, which remains unassigned. A fresh snapshot can therefore render a
Halogen row without a Halogen action-use label. Previous GUI edits can create
different object history; that history is not invented from saved PP here.

All selectors use `(application, group, Level.Address)` identity, including an
explicitly existing selector Address 255. `Level.Value` never substitutes for
Address. The invented vector gives Address 9 Value 88 and Address 10 Value 9 to
exercise that distinction. Error trigger and clear descriptions preserve both
matches and their order. The private standalone unused error Level is distinct
from a network selector and is not projected as one.

## Exact output and evidence

Original line boundaries, raw scene-name insertion, duplicate channel/logic
links and the original malformed Logic table cell are preserved. DMX, special
scenes and ordinary scenes each retain their original accumulated table line;
channel rows retain separate lines. Empty sections still contain their original
headers and tables. These quirks are part of the compatibility result.

The independently written literal fixture is
[`project-documentor-architectural-literal.json`](../research/fixtures/project-documentor-architectural-literal.json).
It contains complete invented PP, native group and Level data, four full body
line arrays and literal group/action results. Its rich three-channel case
covers duplicate output groups, all logic associations, both DMX disable modes,
sparse scenes through slot 128, raw and ramp fades, crossfade, special scenes
and mismatched selector Address/Value. The other three cases establish complete
six- and twelve-channel bodies and empty ordinary/special scenes.

[`project_documentor_architectural_static.py`](../research/project_documentor_architectural_static.py)
parses the hash-pinned Toolkit EXE/MAP read-only. Its generated
[`project-documentor-architectural-static.json`](../research/fixtures/project-documentor-architectural-static.json)
binds the factories, VMT contracts, constructor/loader order, report boundaries,
conversions, identity, consumed methods and current three producer files.
Private compiler coordinates are omitted explicitly, while full method-span
hashes remain bound. No original instruction bytes, private specifications or
site data are committed.

[`test_project_documentation_architectural.py`](../tests/test_project_documentation_architectural.py)
checks exact literal bodies, immutable inputs, all packed fade units, RMS table
points and interpolation, scene compression and deduplication, lifecycle
omissions, missing consumed fields, unsupported firmware, unknown ordinals,
and absent native links. Public CLI/backend integration evidence is tracked
separately; an offline producer test is not that integration run.

Original generated-page acceptance, earlier GUI/process history, native
auto-allocation and editing, device programming and physical behavior remain
outside this snapshot report. Existing acceptance/protected scopes #72–75
remain open. `original_executed` remains false for this static recovery.

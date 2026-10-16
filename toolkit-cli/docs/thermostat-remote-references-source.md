# Thermostat remote-reference source review

The [static receipt](../research/fixtures/thermostat-remote-references-source-review.json)
pins the native Delphi thermostat's ordered reference lookup, creation,
validation and PP save projection. The
[reproducer](../research/thermostat_remote_references_static.py) reads the
original EXE/MAP and optionally the two decoded base specifications. It never
executes original instructions, an emulator, a GUI, C-Gate or hardware. The
receipt publishes source hashes, method bounds and branch checks; private
inputs and instruction listings are not committed.

This is a bounded extension of the existing settings convention: explicit raw
edits precede one projected load/save. It does not reproduce the controls or
event history of an already open form. Existing fan, scalar and optional
temperature projections still execute once.

## Order and references

Programmable AfterLoad `0x12994d0` calls base AfterLoad `0x128e06c` at
`0x12994f5`. Base setback references therefore precede programmable schedule
references. Programmable BeforeSave similarly calls base BeforeSave at
`0x1299bbc`.

| Condition | Application | Ordered group accesses |
| --- | --- | --- |
| Setback source 0 | None consumed by these getters | Clear On, then Off references |
| Setback source 1 | Bound scalar `ApplicationNumber` | On, Off; create missing groups |
| Setback source 2 | Enable Control, address 203 | On, Off; create missing groups |
| Programmable schedule enabled | Enable Control, address 203 | On, Off, Override; create missing groups |
| Programmable schedule disabled | Enable Control, address 203 | Address 255 three times; do not create a missing group |

The base binds `ApplicationNumber` to the unit's application object at
`0x128e518`/`0x128e527`, before setback resolution. This is neither a fixed
application 56 nor the first byte of the generic `Application` array. All
three thermostat classes use the inherited application getter at VMT slot
`+0xb0`. The decoded specification's descriptive text reverses the numeric
source 1/2 labels; the executable branches above establish actual behavior.

Programmable load normalizes Evap values above 1 to 0 and NonEvap values above
1 to 1. It derives schedule enable from the Boolean OR of those normalized
flags at `0x12998c5`–`0x12998f9`. It does not consume raw
`RemoteScheduleEnable` to decide whether to resolve enabled groups.

Each Enable getter invokes `FindOrCreateApplicationByAddress` (`0xf2b0a0`),
which unconditionally calls `CheckAndCreate` with creation enabled, then
performs a read-only lookup. There is no remembered `bAdd` prompt decision on
this path. ApplicationManager field `+0x88` is a reentrancy guard.

`ApplicationByAddress` (`0xf264fc`) and `GroupByAddress` (`0xf28b68`) reuse the
first existing address object unchanged. New objects immediately participate
in later accesses. A missing application is created, addressed, named and
saved before its group is resolved. A missing group is created, addressed,
named and saved before the next role is resolved. Existing names, identities
and levels are retained. A missing group cannot be created when the manager
already contains 256 groups; existing matches remain available. Ambiguous
duplicate database addresses are refused by the owned workflow rather than
assuming native manager order equals XML order.

Names come from the original catalogue and resource strings:

| New object | Name |
| --- | --- |
| Application 203 | `Enable Control` |
| Lighting application 48–95 group N | `Group N` |
| Application 203 group N, N != 255 | `Enable Network Variable N` |
| Group 255 | `<Unused>` |

Catalogue group names default to `Group`; its only singular-name overrides
are applications 172, 192, 202 and 203. Group formatting is `%s %d`.
`TCBusGroupCGateAgent.CreateGroup` (`0x1210f3c`) passes the literal object kind
`Group` to `CGateAdd`, including for application 203. A backend's serialization
as `Group` or `NetVar` is a separate database contract; the creation command
alone does not establish its XML spelling.

## Address 255 is a native group

The native thermostat does not use managed eDLT
`CBusLogicModel.CBusApplication.ReadXmlData`. Native
`TCBUSApplication.InternalCreate` constructs its group manager;
`ProcessAndLoadFromXMLString` (`0xf2604c`) uses the native `PreProcessXML`
overload at `0xf25964`, which adapts child collection wrappers before generic
XML loading. It does not run eDLT's virtual-unused-group reconstruction.

An absent 255 in the consumed native group collection follows
`GroupByAddress(255, true)` and receives a real `<Unused>` object and
`StorageSave`. A disabled lookup uses `create=false` and can return nil.
The separate `CheckAllHaveUnusedGroup` (`0xf2644c`) also creates real missing
255 groups through this helper. Its use by network standard configuration
does not justify synthesizing a virtual 255 during thermostat reference
projection. Stored 255 metadata must therefore be preserved, not discarded.

## Accepted remote settings

`SameGroups` (`0x1131ad0`) rejects a pair only when both references identify
the same nonnil object and its address is not 255. This is object identity,
not bare address equality: application 56/group 12 differs from application
203/group 12.

The base validates setback On/Off with this helper. Its separate not-unused
validator (`0x1131da8`) accepts source 0; for an enabled source it rejects
only when **both** roles are nil or 255. One unused setback role is allowed.
Thus 12/255 can create one named group and one unused group and pass the
scoped remote checks; 12/12 and 255/255 cannot.

Programmable validation checks three distinct schedule identities, requires
all three enabled schedule roles to be non-255 (`0x11333b4`), then checks all
five remote roles together (`0x1133434`). A non-255 group cannot be shared by
setback and schedule in the same application. Enabled schedule 12/13/14 is
a positive save vector. Schedule 12/12/255 remains a useful resolver/reuse
vector, but it is a save refusal.

Missing Level creation is an optional parent prompt. Only dialog result 1
invokes the respective creation helper; the declined branch retains the
validation result (`0x113255b` and `0x113360d`). The bounded reference workflow
chooses **decline** and preserves all existing levels. It does not implicitly
run the separate schedule-level workflow.

Positive setback save copies the resolved addresses; disabled save writes
30/31. Enabled programmable save writes enable 1 and the resolved
On/Off/Override addresses; disabled save writes 0 and 32/33/34. Setback sources
3–255 are refused because original load clears their references while
positive-source save dereferences them. No hidden second save seeks a fixed
point.

## Family and firmware inputs

The original alias class chains pin PC_TSA/PC_TSA5 to programmable and
PC_TSB/PC_TSB5 to basic. The decoded **base** specifications have types
`THERMOSTATA` and `THERMOSTATB`; `THERMOSTAT` names the common include and is
used for basic template overlays. It must not replace the latter base type.
The receipt hashes the common include along with both base files.

Both pinned base files declare firmware range 0 through 9. The owned workflow
checks actual unit firmware against the caller's selected decoded specification
instead of inventing a new fixed firmware admission. Consumed fields must
have the required integer/count-one/eight-bit shape and ranges. The basic
specification also contains schedule PP fields, but the basic class has no
programmable load/save branch; those fields remain untouched.

## Transaction boundary

The native apply owner binds the complete project graph, actual unit identity,
closed network inventory and raw PP snapshot. Planned additions are part of
mutation detection even when every PP byte already matches. Graph-only work
uses zero PP saves and one target project save; a PP delta uses one PP save
and one target project save. The backup's source project save is separately
counted. Only an empty PP delta **and** no graph additions permits a no-op.

These counts, backup/freshness checks and explicit reload verification are
the owned CLI's transaction policy. Original `StorageSave` calls establish
object persistence order, not an atomic native C-Gate transaction. Optional
levels, unrelated HVAC/plant AfterLoad graph effects, initialized GUI
callbacks, accepted source-change control histories and physical programming
remain outside this profile. No uncertain save is replayed automatically.

To reproduce the static receipt with explicitly supplied private originals:

```sh
python research/thermostat_remote_references_static.py \
  --exe /private/original/CBusToolkit.exe \
  --map /private/original/CBusToolkit.map \
  --spec-dir /private/decoded/unitspec
```

Omitting `--spec-dir` checks only the executable/map contract and reports no
decoded-specification facts. No paths from these arguments enter the receipt.

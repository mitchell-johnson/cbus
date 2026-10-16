# Thermostat application control: source investigation

This investigation targets Toolkit 1.18.0.2754 and the four thermostat aliases
`PC_TSA`, `PC_TSA5`, `PC_TSB` and `PC_TSB5`. Application selection and reference
migration are **not yet exposed by the CLI**. The findings below are static
source evidence for that work, not executed original-form acceptance.

The existing ordinary output loader now permits unrelated Unicode group names
when a generated-name lookup has one match. Its recovered `LowerCase`
comparison folds ASCII letters only; it does not require a Windows sorting locale. An
ambiguous lookup still needs the original manager order. See
[the settings workflow](thermostat-settings.md).

## Evidence and scope

The executable and map are pinned by SHA-256:

- EXE: `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`
- MAP: `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`

The [migration verifier](../research/thermostat_application_change_static.py)
checks decisive branches and complete method hashes; its
[receipt](../research/fixtures/thermostat-application-change-source-review.json)
contains no vendor bytes or private paths. Separate
[event](../research/fixtures/thermostat-application-events-source-review.json),
[selector](../research/fixtures/thermostat-application-selector-source-review.json)
and [manager](../research/fixtures/thermostat-application-order-source-review.json)
receipts cover the framework dependencies. Static disassembly
does not run or emulate original instructions, launch vendor software or use
a physical C-Bus network.

The [validation checkpoint](../research/fixtures/thermostat-application-source-checkpoint-20261004.json)
records 44 focused test passes and 249 subtest passes for the existing workflow,
with four optional source inspections skipped. A separate run passed both new
source tests and eight subtests, reproducing all four source receipts. Full
suites were not run. `coverage --require-complete` still exits 1.

## Application state and selection

Initial agent loading reads the raw `ApplicationNumber`, resolves that
application with creation enabled, and assigns `ApplicationObject`. The
selector's filter is separate: its existing choices are application addresses
0 through 128. That filter is not the older CLI output profile's 48–95/203
restriction, and it does not justify rejecting an initial current application
such as the specification default 115. The current output CLI still admits
48–95/203; broader initial application loading is evidence for the future
migration model, not an implemented runtime expansion.

The ordinary parent loads programming before installing its application
callbacks. The application assignment during that load leaves the internal
notification flag at zero. A changed selector choice invokes the application
subscriber once. With the flag zero, `ApplicationChanged` migrates the
references and sets the flag to one. The next changed choice clears the flag
without migrating. Selecting the same object does not invoke the setter and
does not change the flag. This alternating behavior must not be replaced with
an assumed pair of callbacks.

The parent posts a deferred tab refresh. That refresh does not perform a
second application assignment or rebind the Plant/Zone application links.
Consequently A→B→C can finish with current application C but lists bound to B.
An individual reference can still point to a group in A. These three identities
must remain distinct in a retained model.

The unit's separate `+0xdf` flag suppresses migration during SaveProgramming
and SaveTemplate. It is not a caller-supplied readiness flag. The template-load
guard at `+0x1e0` is separate again.

## Migration and allocation

`RefreshThermostatGroups` checks missing destination numeric addresses, calls
the parent's decision callback when needed, rebinds Zone then Plant lists,
and holds a project save lock while processing these references in order:

1. Source 1 setback On and Off.
2. Cooling activation, stages 1–3, then low/medium/high fans.
3. Heating activation, stages 1–3, then low/medium/high fans.
4. Dampers 1–4.

The thermostat parent's missing-group decision is unconditionally true.
There is no operator accept/decline prompt to add to a CLI contract. Schedule
references remain in application 203. There is no independent relay migration
loop, although the earlier missing-address check includes all five relays.

`UpdateGroup` receives a **reference attribute**, then resolves its old Group.
The generated role label is selected by attribute identity, not by the old
Group's identity. Two attributes sharing a Group still have separate roles.
The source follows these branches:

- A nil or unused old reference resolves a real destination Group 255 with
  creation enabled.
- Otherwise it searches for the old tag. Only if that search finds a match
  does it inspect the old Group's `HasDefaultTagName`. A non-default old name
  reuses the first matching destination object.
- Otherwise it searches for the generated prefix, one space, and the role
  label. A setback attribute has an empty role label, so its search includes
  that trailing space.
- If neither search succeeds, it allocates the first free numeric address
  in 1–254. Address 0 is not an allocation candidate.
- An output or damper then runs its role's default getter with the migration
  flag enabled. A role without a default label can retain the generic new
  Group. Those default getters can classify the newly allocated Group's name
  again before renaming it. This differs from ordinary loading's missing-role behavior.
- A setback instead resolves the old numeric address after the provisional
  allocation. The provisional Group remains even if another Group is then
  created or selected for the actual reference.

Every migrated role immediately updates relays whose current Group identity
equals its old non-unused Group. Later roles inspect those already changed
relay identities. A standalone relay is untouched by this loop. Old groups,
levels and unrelated metadata are not deleted or copied.

When 1–254 are full, the allocator returns nil. Some original caller paths
then dereference it. Source 1's setback path instead continues to resolve the
old numeric address and can succeed without a provisional group. An owned
transaction must reject only the branches that require the missing object,
during preflight; it must not invent a replacement or reproduce a partial
write before an original fault.

## Name equality, classification and ordering

Migration name equality uses `SysUtils.UpperCase` on both strings, then exact UTF-16
equality. Only ASCII lowercase letters change. The first matching manager
item wins. A unique match makes manager order irrelevant even when unrelated
names contain arbitrary Unicode characters.

In the pinned English resources, `HasDefaultTagName` requires the exact
`Group ` prefix and a nonempty suffix, testing at most 100 following UTF-16 units. The JCL predicate
accepts each unit when the Windows `C1_DIGIT` bit is set, or it equals `+`, `-`
or the current `SysUtils.DecimalSeparator`. It is neither Python `isdigit`
nor a decimal-address regular expression. The character table is populated
through `GetStringTypeExW` over all 65536 UTF-16 units. An exact consumed table
or locale value must not be inferred from the CLI host.

Collection sorting uses a different comparison. Its default preference is
tag-name sorting through Windows comparison; an address preference is also
supported. XML order alone does not establish a live manager's order. A full
tag sort is unstable for equal names, so even the number of prior sorts can
matter to a duplicate lookup.

New groups are inserted while Address and TagName are still empty. Empty
Address resolves to 255. The requested address and name are set afterward and
schedule a 1 ms full sort. They do not immediately reinsert the object at its
final numeric position. Normal successful DBAdd, DBSet and ProjectSave waits
do not pump the GUI message loop, so a migration must retain those pending
sort effects through its synchronous callback.

## Selector and dialog state

Changing a group's list link marks the list dirty without assigning a new
group reference. Existing displayed items can remain until a source event
repopulates them. No paint or deferred tab-refresh caller directly runs
`PopulateList`.

Group Add/Edit first uses the selected object's actual application, falling
back to the list application only when no object is selected. This matters
for an old-app relay retained after migration. Both dialog completion paths
then repopulate the list and call `DoIndexChange`. When the selected object is
absent, that callback can use a cached displayed index as an unfiltered
manager index, selecting a destination object or nil.
Restoring the old caption can also enter framework text-to-index matching;
its behavior under the population update locks remains unresolved. An absent
object must not be treated as proof of a final index of -1.

The cache is initially zero. Focus entry records the displayed index before
repopulating; an admitted keypress can update it too. An embedded mouse click
can enter through the focus path, while a direct action wrapper or popup-menu
path differs. A future ordered history needs source events and retained
display/list state, not an arbitrary caller-provided index or a blanket
assumption that dialog completion preserves the old object.

For example, with four distinct existing application objects:

| Event | Current application | Bound lists | Notification flag | Migration |
| --- | --- | --- | --- | --- |
| Ordinary initial load | A | A | 0 | Initial agent load only |
| Select A again | A | A | 0 | None |
| Select B | B | B | 1 | Run in source order |
| Select C | C | B | 0 | None |
| Select D | D | D | 1 | Run against retained references |

## Implementation obligations

The application workflow still needs one owning model that composes source
events, migration and existing Select/Add/Edit operations without reloading
references between them. Its final save must serialize the retained model's
numeric references once. Reloading it under the final application before
that save could replace identities and create unplanned groups.

Consumed duplicate-name order and unresolved Windows character-table facts
remain evidence dependencies. They must not be replaced with a global ASCII
inventory restriction, guessed XML sorting, an invented Boolean state or
hidden host-locale behavior. Full preflight, intermediate graph operations,
strict preservation and the existing uncertain-save no-replay rule remain
required. Native-server, original GUI and hardware acceptance are separate
from these static findings.

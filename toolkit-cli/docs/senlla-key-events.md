# SENLLA key/application/Scene event owner

`senlla_key_events.py` is an internal synchronous callback owner for the
SENLLA/5754PE firmware 2.4.00–2.4.99 source profile. It models ordered eight-key
allocations, application changes, block collisions, Scene claims and swaps,
macro/template callbacks, indicator ownership, broadcast effects and bank
feedback. It uses the retained lifecycle substrate instead of applying a flat
list of final changes.

The entry point is CoreKey `GetKeyBlocks`, after the earlier application,
Area, block, stored-level, timer and expiry getters/setters. The owning Unit
remains updating at entry. The constructor receives source-established
objects and an existing bank graph; it does not replay the callbacks that
created those objects. Every key application is primary at this entry: the
earlier primary application callback binds all eight initially state0 keys,
before raw block loading while their reference lists remain empty. Fresh
construction instead starts those key references nil and must replay that
binding. A complete owner must retain the same actual objects
and counters from construction through these earlier phases before admitting
a public unit-save workflow. This module has no CLI, configure/apply action,
complete 93-parameter save, native runtime or hardware acceptance claim.

The [numeric source receipt](../research/fixtures/senlla-key-events-source.json)
pins the executable, map, spec identity and exact method spans. It retains
literal cases and explicit unresolved owner requirements. No vendor XML or
native instructions are included.

## Internal API

`KeyEventContext` contains the actual primary/secondary application identities,
ordered application/group inventories, currently bound protected groups,
Join state and actual trigger-level objects. Primary Lighting is 48–95;
secondary admits Lighting, the actual application 255 object, or actual nil.
Application 255 remains bound after its later secondary-bit normalization.
Its unused group is an app-owned object, distinct from another application's
unused group and from nil.

`BlockValues` holds eight source-loaded blocks: Secondary, actual Group,
current LightLevel, two stored levels, Timer, cached Timer, expiry and expiry
override. A loaded expiry zero is a real nonnil microfunction object. Actual
nil expiry is a separate existing-state input; no raw nibble reaches nil.
The raw loader normalizes unsupported expiry nibbles to function15 before
this entry. Fresh timer minimum0 and live state1 are the retained bounds.

`SENLLAKeyEvents(context, blocks, bank_graph)` supports these owning phases:

1. `load_allocations(masks)` replays keys and mask bits ascending, including
   the final primary-group refresh for every zero-mask key. Block secondary
   refresh visits all eight currently nonupdating keys, including keys with
   no reference to that block. Each eligible row brackets the source block
   with Begin/EndUpdate; equal key state still reaches the block publication.
2. `finish_corekey_application_refresh()` ends the Unit update, then replays
   the primary and secondary application refreshes. A secondary collision
   adds the destination reference before removing the source reference.
   The group-refresh tail requires already-established matching block groups
   and fresh empty Scene managers. In that Lighting profile its missing-group
   check is false and it writes nothing. The nil/application255 tail requires
   current keys to have normalized to primary. Macro admission scans only
   current state0 on the primary side and state1 on the secondary side;
   mixed state2 is excluded.
3. `load_scenes(table, pointers, patch, control_group)` uses the shared numeric
   Scene loader. The already-established control-group getter precedes this
   call even when Patch is disabled and no Scene key is selected.
4. `load_key_values(stages, selector, indicator)` replays each raw key under
   the actual template/parent update counters. Scene claim can move block
   data and earlier key mappings before the current key's raw fields load.
5. The complete owner executes the later CoreNeoPro/ST7/surface phases at
   their source positions. `bind_context(context)` binds already-established
   later group/level/Join facts without hidden callbacks. Existing canonical
   identities remain stable. It refuses object deletion and application
   reference replacement, whose setter routes are separate owner work.
6. `adopt_bank_graph(graph)` adopts already-executed bank/occupancy/maintenance
   transitions with the current ordered references. It writes changed stored
   bytes under native bank-owned feedback suppression and infers no aggregate
   or occupancy event.
7. `fresh_function_bindings()` applies the retained function-list admission.
   Modify25 is absent and becomes unlocked16; Invoke24 remains admitted.
8. `install_m8_hooks(control_dispatch=executor)` installs each general Key
   hook before that key's template hook, in ascending key order. General
   activation immediately executes the control branch then recall-conflict
   callback. Template activation repeats the recall callback. The group
   decision handler is installed after these activations.

The synchronous executor receives an immutable `KeyControlRequest` and the
live engine. It executes the complete pinned general control branch against
actual form bindings, including function combo root/list replacement and
broadcast-list population, and returns `None` after nested setters finish.
It must reread current state after each nested callback. Missing execution
refuses with `SourceControlRequired` before the first template-hook activation.
The focused literals use an explicit fake form executor to isolate the model
kernel; they do not establish original control/framework acceptance.

Later owner dispatch can call `set_secondary`, `set_group`, `set_template`,
`set_broadcast_block`, `set_broadcast_active` and `set_label_flavour`. Logical
LabelFlavour1–4 maps to raw enum0–3. Invoke resets it to logical1 after ramp
refresh; the fresh raw0 equality emits no synthetic owned notification.
An unlocked primary-group
edit, a missing object requiring creation, or an installed decision outside
the implemented dispatcher refuses. `SourceObjectRequired.request` identifies
the source-phase group or trigger-level getter; no missing object is invented
from a future inventory.

## Callback and output boundaries

The template attribute keeps its parent key updating during its dedicated
callback. Nested Scene allocation therefore suppresses direct refreshes that
the parent counter guards; it does not defer an invented refresh until later.
Scene swaps cache all nine first-block values, perform setter writes under the
native nested block counters, then update ordered mappings and current
indicator identities. Current template, group, allocation and broadcast
values are reread after nested callbacks.
SwapMappings calls the current Indicator Changed explicitly after its
BlockNumber setter, retaining both native notification positions.

Indicator and Neo extension are stable owned objects. Their custom reference
notifications relay through the owned attribute and manager to Key Changed,
after target managed subscribers and before target BaseOnChange. Owned getters
rearm the attribute and key. Registration emits no synthetic target change.
The Macro object is a distinct reference attribute and has no generic
MacroEnd rematcher. Selected Scene JP0 binds real microfunction0. Modify sets
Scene1 before loading raw stages and again at the common final branch.

`snapshot()` returns detached dictionaries without invoking value getters;
inspection therefore does not rearm publication. A failed callback invalidates
the runtime and refuses further execution or a save projection.

`parameters()` replays private partial key/block/Scene marshalling after the
admitted component phases. It is not a passive snapshot or a full PP save.
It captures CoreKey allocation/block PP first, then CoreNeo Scene PP, before
the ascending key-value serializer. Those earlier PP values remain captured
if a later nil-trigger setter changes live allocations, groups or stored
levels. The later CoreNeoPro SecondApplicationBlocks overlay reads the
post-key-callback mask.
Invoke23/24 with a nil trigger reaches the actual level255 getter and setter
before continuing its captured Invoke branch, even after a nested template
change. Missing level creation refuses at that causal position.
`block_values()` is passive inspection of the eight current block LightLevels.
The real save owner must capture it and rebuild the indexed CoreKey PP before
calling `parameters()`, while key setter callbacks have not run. It must not
use a post-`parameters()` inspection to reconstruct the earlier saved levels.
The owner uses the current LightLevelIndex to rebuild the actual PP with its
prefix255, eight current block levels and suffix255, including native array
growth. ST7 subsequently overlays fixed global positions9/8 in that current
array. Later ST7 and surface bank serializers can overwrite the current
stored-level arrays at their later source positions.
Metadata, Global, target/margin, power, PEC, potentiometer and remaining unit
fields retain their separate owners.

Full orchestration still needs the prekey shared-object lifecycle, actual
group/application/project creation observers, the complete native control
executor, later ST7 decision handlers and final 93-field serialization. Extra
reference receivers, replacement/destruction, nonlive state2 and nonzero
timer-minimum histories are outside this stable internal profile.

The [frozen key-event source check](../research/fixtures/senlla-key-events-source-check-20261004.json)
covers fifteen SENLLA modules at authored commit `6f57ff00`: 287 parents,
3,846 separate subtests and zero failures, errors or skips. All 4,091
tracked inputs remain unchanged in the frozen checkout. Independent review
clears the final event kernel and native save-order/all-eight secondary-loop corrections. The earlier
387-span review is preserved and its save-order/secondary-loop claims are superseded by
the final correction receipt. Full pre-key object continuity, native form
execution, complete 93-field public save and installed-wheel/original/
native/hardware acceptance remain open. Full suites are deferred for speed.

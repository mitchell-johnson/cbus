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
unused group and from nil. A secondary unused group is not required before
its first actual getter. A zero-use secondary application can therefore remain
bound while its manager contains no unused group.

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

## Same-object constructor seam

`SENLLAKeyEvents.fresh(application_addresses=(), group_identities=(),
trigger_levels=(), source_dispatch=None, application_dispatch=None)` creates
the Unit, eight blocks, eight keys and their managers/attributes once. Unit
primary/secondary/Area, block application/group/expiry and key application
references start nil. Scalars and key reference lists start zero/empty.
The graph starts at the source-proven result of constructor bank-link
activation: Allowed true, Active false, High/Low/stores zero. Each bank keeps
its original bound block; Unit updating does not suppress its observer.

The ordered inventory arguments identify actual source-existing objects.
They do not select Unit applications or supply a later PP context. The
application dispatcher receives `(engine, secondary)` synchronously during
the actual Unit reference setter. It owns the inherited Area and application
callback sequence, including guards and nested counters. Missing dispatch
refuses. The separate prekey owner executes the initial application and raw
block requests on these same attributes.

`get_source_application` and `get_source_group` probe the current canonical
objects. A registry miss yields immutable `SourceLookupRequest`, including
for create-false probes: an unregistered identity is not proof of absence in
the actual manager. The synchronous source executor performs the actual
lookup and, when requested, creation/storage/observer work, then confirms a found identity
through `add_source_application`/`add_source_group`. Those registration
methods preserve existing object identity and do not execute native creation.
The getter rereads its registry after the executor returns. Create-false may
return nil only after that actual lookup; create-true requires a confirmed
canonical object. Missing executors refuse unknown lookups. The block
application callback captures the old numeric group address, probes the current
application with create-false, then performs an allow-enabled getter and a
second current-application getter for assignment. Both later calls occur when
the probe found an existing group. Each rereads the application because a
creation/storage callback may change it. Fresh nil-decision uses allow=true;
an installed missing-group decision or create-enabled nil result still needs
its separate source executor.

Dictionary registration order is not native GroupManager Items order.
`bind_source_group_order(application, addresses)` binds the actual current
manager order, requiring exactly its currently registered groups without
replacing them. New registration invalidates that order until rebound.
Later controls must use `current_source_group_order`, which refuses an
unbound order; the identity inventory in `KeyEventContext` cannot substitute
for this source list.

`begin_prekey_load()` begins the outer CoreKey Unit update.
`handoff_to_key_blocks()` requires Unit depth1 with the Unit manager and all
three Unit reference attributes balanced, balanced blocks/keys, canonical
engine-owned application/group pointers, primary-bound state0 keys and empty
reference lists. Matching numeric addresses cannot substitute foreign objects.
It derives the context from actual current references and retains every
original object, counter, subscription and graph. It does not adopt raw rows,
rebuild a snapshot or infer omitted callbacks. The existing kernel phases
then continue on that same engine. A whole prekey operation uses one outer
`_run` so its native cleanup executes before failure invalidates the runtime.

The [constructor seam source receipt](../research/fixtures/senlla-key-events-shared-constructor-source.json)
qualifies this adapter and continuity evidence. Source metadata/Learn/scalar
execution, canonical creation observers, native list order and the complete
ordinary save still require their owning executors. Focused seam tests use
explicit fake executors to isolate identity/counter continuity; they do not
establish complete inherited callbacks or native GUI acceptance.

The [frozen key-event source check](../research/fixtures/senlla-key-events-source-check-20261004.json)
covers fifteen SENLLA modules at authored commit `6f57ff00`: 287 parents,
3,846 separate subtests and zero failures, errors or skips. All 4,091
tracked inputs remain unchanged in the frozen checkout. Independent review
clears the final event kernel and native save-order/all-eight secondary-loop corrections. The earlier
387-span review is preserved and its save-order/secondary-loop claims are superseded by
the final correction receipt. Full pre-key object continuity, native form
execution, complete 93-field public save and installed-wheel/original/
native/hardware acceptance remain open. Full suites are deferred for speed.

The [frozen shared-prefix/control source check](../research/fixtures/senlla-prekey-controls-source-check-20261004.json)
covers seventeen SENLLA modules at authored commit `9a1e024a`: 342
parents, 3,945 separate subtests and zero failures, errors or skips.
All 4,101 tracked inputs remain unchanged in the frozen checkout. Final
independent reviews clear 151 shared-constructor, 162 prekey and 64 control
spans. These checks cover the same-object prefix and persistent control
kernel. Inherited metadata/base execution, actual backend creation/storage,
late Scene topology, concrete framework/comparison/scheduler primitives and
complete 93-field public save remain open. Test executors do not establish
original/native backend or hardware acceptance. Full suites are deferred
for speed; historical receipts retain their original scopes and hashes.

# SENLLA live occupancy component

`senlla_live_occupancy.py` constructs eight retained occupancy objects before
key PP loading. Each has its own actual manager, InputKey reference and four
Boolean attributes. The native initial flag values are false; bytes94/95 are
true and bytes96/97 are false. These are constructor facts, not device defaults.

The owning factory must defer the historical key kernel Smart observer and
construct this component before PP callbacks begin. Attaching after a nonnil
Template is loaded, or while a historical Smart observer remains active,
refuses. Each InputKey reference binds once to the same key object and its
Template observer. Later general key notifications reevaluate that retained
Template pointer. There is no invented MacroEnd rematch or detached replacement
key graph. Arbitrary InputKey rebind, inactive resume and destruction are outside
this ordinary live-owner1 profile.

`get_flag(key, name_or_ordinal)` calls the actual Boolean getter and rearms its
attribute and occupancy owner. `set_flag` uses the actual Boolean setter.
Equal values do nothing. Unequal values publish at the native attribute
position, then execute dedicated callbacks while the manager still keeps the
occupancy owner updating. Light clears Any then Dark; Dark clears Light then
Any; Any clears Light then Dark. Every unequal nested clear finishes its event
callback before the initiating event callback. Sunset goes directly to the
event callback. Observers may see transient overlapping movement flags before
the dedicated mutual clears finish.

`refresh_flags` implements direct QuickSet: current nonnil Template and Join
predicates select one template type, then Light, Dark, Any and Sunset setters
execute in order. Smart refresh retains source bytes94/95, recognizes
29/30/33/34 and all Scene types23/24/25, and rereads current Template after an
actual decision callback before QuickSet. Macro observation sets guard97 and
clears it in finally. Event-to-template refresh sets guard96 and clears it in
finally. Neither guard is an update counter or a saved prior guard value.

The constructor requires concrete owning callbacks for bank refresh,
JoinActive, current broadcast fields, HasBlock and template setters. They
consume the same objects at their actual source positions. `bank_refresh(occ)`
runs after optional event-to-template refresh. It must execute the source bank
setters and current reference/getter order; recording an acknowledgement does
not complete that dependency. Existing live bank integration still needs its
per-flag getter routing rather than an eagerly captured flag tuple.

The late source330 macro decision and source338 event callback start nil.
Install them only at the owning director's actual installation positions.
`MacroOccupancyDecision` exposes the actual mutable bytes94/95; the source307d
decision implementation remains the owner's responsibility.
`EventTemplateDecision.refresh_template` is the source callback's mutable
local Boolean. The source338 callback executes even under guard97, although
guard97 then suppresses the template rewrite. Installed callbacks must perform
the actual decision or refuse. A missing installed callback never becomes a
successful default acknowledgement.

An exception preserves committed values and native unfinished counters. It
invalidates the live component and prevents automatic resume. Raw inspection
through `snapshot()` does not execute getters or rearm publication. This is
separate from a predicate that must short-circuit at each actual getter.

The component does not own native occupancy/key/group collection identities,
the bank algorithm, Join/broadcast backend fields, message-box decisions,
director/scalar/Show/Apply sequencing or public whole-unit save admission.
Those remain concrete owning dependencies. The fixture retains exact numeric
method and VMT digests plus authored callback vectors. Focused tests exercise
actual shared attributes and synchronous nested callbacks. No original
instructions, Windows UI, physical network or full suite were executed.

The Smart numeric occupancy predicate reads the current template twice for its nil and type checks. If its type is outside 29, 30, 33 and 34, it then reads InputKey once and invokes the separate Scene predicate: a current template nil check, followed by a fresh template read for each reached comparison against 23, 24 and 25. These getter positions rearm the actual attributes and are preserved before QuickSet.

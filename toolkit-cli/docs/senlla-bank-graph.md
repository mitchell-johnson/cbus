# SENLLA owning bank dependencies

`cbus_toolkit.senlla_bank_graph.SENLLABankGraph` connects eight banks,
ordered key references, occupancy state and maintenance context. `fresh()`
establishes the state after the actual surface banks bind to fresh blocks:
zero levels, inactive banks, Allowed true, empty references and false
occupancy flags. CoreKey stored-level loading runs Store1 then Store2 within
each ascending block. The later ST7 bank loop assigns Active before Off.

External unequal stored-level setters notify the bound bank. That callback
computes Allowed from all currently attached occupancy keys and the current
maintenance block, then captures both stores and assigns High before Low.
Bank-owned High/Low changes instead suppress their own block observer while
writing the stored byte. Re-evaluation after Bank.EndUpdate retains the same
block identity and emits no delayed value callback. These paths therefore
have different permission effects.

An occupancy callback examines the initiating key's flags and iterates that
key's current references. It can allow a bank even when another attached key
remains occupied. A later actual block change recomputes the aggregate.
Reference changes alone do not do so, and equal occupancy flag assignments
emit no event. Removed references are already absent when the reference-list
callback runs. Raw maintenance Active/Block assignments also have no dedicated
bank refresh callback. The graph keeps context assignment, occupancy events,
owned lux changes and explicit aggregate refreshes separate.

`refresh_event_flags` models the reference callback's direct QuickSet after
the owner handles broadcast clearing and reassignment. It preserves Smart's
decision/refresh fields and clears ordinary-template flags even when Smart
macro refresh was previously disabled. Nil templates and joined keys4..7
skip this direct refresh. It is a distinct path from `macro_changed`.
The direct method does not install the macro guard, and an enclosing guard
does not prevent an installed handler from being called. Its API requires
explicit handler context and refuses changed flags with an installed
event-to-template handler until the owner can replay those nested callbacks.

For example, ordinary Sunset template34 can make Allowed false before the
raw Active value loads. Loading Active true afterward can retain Active true
with Allowed false. An equal raw Sunset true assignment does not repair that
state. A surface LowLux assignment then changes its store without an
aggregate permission refresh. The graph preserves this history.

The [static source fixture](../research/fixtures/senlla-bank-graph-source.json)
combines 160 unique method pins from independently reviewed construction,
observer feedback and reference/maintenance audits. It retains three explicit
feedback literals and six qualified reference/maintenance literals. Template29
examples use explicitly supplied existing state; SENLLA's ordinary raw macro
subset does not load template29. The composed ordinary history tests use34.

This is the bank dependency portion of the owning save engine. Application
and Scene owners must supply their actual ordered references, template and
broadcast events, including generic block notifications at their causal
positions. The graph does not synthesize those events or own project metadata,
whole-form initialization, the complete 93-parameter save, or a public save
command. Original runtime and hardware acceptance remain open in issue41.

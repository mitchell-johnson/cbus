# Internal SENLLA inherited owner and project bridge

`senlla_inherited_owner` executes the mandatory inherited prekey requests on the
same Unit manager, attributes, blocks and keys used by `SENLLAPrekey`. It requires
the guarded 93-field snapshot and one actual selected project/network/unit. This
is an internal component; it does not expose a public programming command or
claim a complete normal save, original GUI execution, or physical acceptance.

The source prefix runs the empty base-agent call, loads the Unit Project string
and CBusUnitName, visits the disabled SENLLA Learn branch, and sets CoreKey
debounce, long-press, EEPROM-level-store, ramp ordinals and the early Core
infrared ordinal before block loading. The Learn attributes retain constructor
false values; their unrelated setter callbacks are outside this admitted phase.
The indicator-brightness gate resolves the actual SENLLA VMT1a8 to the false
ST7 override. The 13 protected/non-sent PP fields remain raw snapshot values.

`parameter_read(name, source, runtime)` optionally supplies the actual CURRENT
agent cache getter at each inherited scalar/string source site. A complete
owner binds its current load-agent journal here; an earlier object-creation or
attribute callback can change a later read. RampRate is read twice, once before
each separate setter. Late NeoPro IR getters also read again at their own
positions. Returned values are detached and admitted against the guarded field
type/count/domain; this component guard is distinct from native cache-getter
validation. The default retains the historical snapshot-bound component
profile. This hook does not replace the separate prekey Application/Area/block
getter schedule, agent-cache lifetime or later save-agent preparation.

String setters implement mutable candidate/changed-flag handling before Begin,
UTF-16 maximum validation, then the native manager/parent update order. Enum
setters return on equality and enforce their native ordinal domains. Dedicated
callback failure can prevent manager/parent End; the outer owning engine must
invalidate that interrupted lifecycle. Calls made by later orchestration must
remain inside its `runtime._run` owner boundary.

`load_neopro_infrared()` is a separate source-position prefix: IRBankP and the
inverted DisableIR/DisableIRNEC setters execute only when the orchestrator
reaches that late NeoPro phase. `initialize_global()` applies the later minimum
status interval 3 on the same live attribute. `scalar_parameters()` reads the
current eleven scalar fields after late IR load; the caller owns their individual
native BeforeSave capture positions. It never reconstructs current attributes
from the raw snapshot. Final Project comes from the current actual Project
TagName, UnitAddress from the selected actual Unit, and UnitName from the live
CBusUnitName attribute. Actual Unit TagName is a separate string property.

Later phase owners may call `register_unit_attribute(name, attribute)` with an
actual source-owned `FlashAttribute` on this same Unit manager, then retrieve it
with `unit_attribute(name)`. Registration performs no setter or notification and
does not infer constructor values or handlers. The root's later ST7/surface
attributes use this seam; early Core/late NeoPro IR and Global status remain
owned here.

## Causal metadata and persistence

`SENLLAProjectBridge.from_document(document, network, unit, storage_path=...)`
uses the existing `ProjectDocument` structural API and actual atomic save/reload.
`from_native(database, project, network, unit, ...)` uses an actual
`NativeDatabase` client for current DBGETXML, DBADDSAFE, Level Value initialization,
PROJECT SAVE, and exact address/name/issued-OID readback. These are concrete
backend operations; an authored mock API pass does not prove vendor acceptance.

The bridge binds once to the SAME runtime. A source lookup confirms current
actual backend metadata at that position and only then registers the canonical
application/group/action pointer. A false lookup can confirm absence without
creation. It does not prefetch future action selectors or infer native manager
order from XML child or registration order. Canonical groups include actual
manager members at address255. Native blank-OID Application/Group AgentSave has
no numeric255 exemption; it reaches creation/storage through the ordinary agent
route. Application recursive creation retains the native creation guard.

Missing creation requires these source owners:

- `metadata_name(kind, application, address, source, runtime)` returns the actual
  current registry/resource-derived TagName. Application title lookup and unused
  names use current resources; GroupByAddress uses
  `StandardCBusApplications.GetGroupName`, rather than the Add-dialog default
  name helper. An actual `application_descriptor(address)` may supply app names
  independently. The action-selector prefix is the retained literal
  `Action Selector N` when no metadata-name provider is supplied.
- `creation_dispatch(request, bridge, runtime)` synchronously owns native
  project listeners at `before_backend_creation`,
  `metadata_ready_before_storage`, and `stored_readback`. It must return None.
  Existing APIs supply Address/Tag atomically; the bridge does **not** replay
  native transient Add, Address, Tag attribute notifications. A prekey phase
  alone does not prove that the actual manager has no listeners. Tests supply
  an explicit authored zero-listener context.
- `manager_order(application, current_rows, runtime)` supplies actual current
  GroupManager Items order. `form_applications()` enumerates current actual
  rows only at the owning list read and binds that order without replacing any
  canonical pointer. It retains raw current TagNames in `FormApplication` and
  `FormGroup`; those fields are not ToString text.
- `display_text(object, current_record, source, runtime)` supplies source-owned
  ToString text/preferences for the persistent control provider. It must not
  substitute TagName for an extended address display without source proof.
- `tag_name_dispatch(owner, bridge)` owns the actual optional Unit TagName
  notification and after-change timer route. Changing the live TagName does not
  itself perform a database write.

`get_level(runtime, canonical_group, address, create=..., source=...)` supports
later Scene, ascending-key and save-time causal getter sites. A newly created
action gets both Address and Value equal to the requested byte. An existing
level is found by Address, and its current Value is a separate fact exposed by
`current_record()` and `level_value()`; native TIntegerAttribute.AsInteger reads
the signed Integer directly without ResolveChange. The owning Scene/save
serializer must not derive Value from
the pointer identity's final address. Both XML attribute and child Value
representations are read; conflicting representations refuse.

That distinction does not change Invoke nibble marshalling: native SetKeyValues
reads the level's Address at `ccb9e8`/`ccba1d` for LP/LR. Each owning getter/save
site must follow its actual Address-versus-Value source route.

Existing Value setters and generic metadata notifications require the actual
metadata attribute owner. This bridge exposes no setter and never changes an
existing Value to match Address. Final PP schema/domain admission remains the
owning serializer's responsibility. With the source-aware engine seam, level
registration passes its actual current Value into `add_source_level`; the older
projected kernel retains only pointer identity, so its serializer remains
explicitly qualified and cannot claim this live metadata value route.

Creation callbacks may run nested setters and getters, including rebinding a
block application between native group probes. All subsequent native reads must
use CURRENT objects; the bridge does not supply a future final context. Failed
storage leaves truthful partial backend state, registers no invented confirmed
object, marks the bridge failed, and never automatically replays or rolls back.

For a causal control Count/ordinal read, use
`group_items(runtime, actual_application)`. It rereads only that actual current
backend application's Group/NetVar rows, requires actual manager order, registers
only its existing canonical groups, and returns those same objects in the bound
order. It creates nothing and seeds no unrelated application or action. The
owning control rereads this interface at each native item position, then uses
`current_record()` or its actual source formatter at the separate ToString
position. `form_applications()` remains a separately qualified global inventory
helper; it must not be substituted for a causal one-application getter. Actual
metadata removal that conflicts with registered canonical pointers requires
its source lifetime/reset owner before a smaller manager order can be bound.

The safe numeric source receipt is
`research/fixtures/senlla-inherited-owner-source.json`. Focused authored tests
cover the inherited prefix, same-object continuity, native string/enum semantics,
current metadata, explicit listener/descriptor/order/display boundaries, nested
rebinds, file persistence, and native API receipt/value/save ordering. No vendor
definitions, defaults, original instructions, network hardware, or full suite
are used.

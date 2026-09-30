# IOPE Aux template and dependent-stage transaction audit

No source-complete bounded input-function transaction is established by this
static audit. A top-level advanced Aux function row is a narrower and useful
next recovery target, but stable reconciliation flags alone would not close it.
The private EXE, MAP and decoded UnitSpecs are present; the remaining blockers
are unclosed source recovery and entry/ownership contracts, not a missing vendor
file or a need for CPU emulation.

The companion `research/fixtures/iope-template-transaction-source-review.json` pins 30 exact next-MAP
method ranges and four UnitSpec hashes. It contains method identities, hashes,
sanitized observations and candidate parameter locations, with no vendor bytes
or private artifact paths. The candidates remain IOPE1R1, IOPE2R2 and IOPE2C4
firmware 1.0.00..1.2.99; no writable edit API is admitted.

## Correction to the earlier advanced-row review

`ComboPropertiesChange` at 0x11b14c0 selects one of two update paths. For a
top-level function node it sets the parameter selector to -1 at 0x11b155b.
The comparison at 0x11b15f1 reaches `UpdateMicroFunction` at 0x11b15f8, then the
unconditional jump at 0x11b15fe skips `UpdateKeyParameters` and rejoins at
0x11b1607. Child parameter nodes instead reach `UpdateKeyParameters` at
0x11b1601. Both paths then call `PopulateComboBoxList`, `Refresh`, and
`RefreshOtherTabs`.

Therefore the earlier statement that this handler always invokes both update
methods is incorrect. A function-only candidate does not inherit every child
parameter write. The selected microfunction path can itself call
`RefreshKeyParameters` when the focused node has children, and the shared refresh
path still reads block, pot and scene-related state. The correction does not
prove those callbacks are independent of the model or other tabs.

`GetKeyPressStageByRowID` at 0x11af344 maps row IDs 0, 1 and 2 directly to stages
0, 1 and 2, and every other ID to stage 3. The stage setter resolves those to
members +0xb0/+0xb4/+0xb8/+0xbc, in JP/SR/LP/LR order. The handler identifies
Aux index 0 by the grid in form field +0x290, otherwise Aux index 1 after its
sender/class and node-topology checks. A bounded API should admit exact row IDs
and input identities rather than reproduce the permissive otherwise branch.

## Concrete dependent rules

`AssignTemplate` assigns function metadata and the whole default microfunction
group under BeginUpdate/EndUpdate. `Group.Assign` copies JP, SR, LP, LR, VC and
VT references. `GetMicroFunctionGroupDefault` selects the first registered group
for a nonempty template, except macro function 48 selects factory group 105.
An empty group list returns null.

The four-stage `ItemAndGroupByMicroFunctions` matcher at 0xc97ff8 searches
templates, then each template's groups, in registration order. The first
JP/SR/LP/LR function-type match wins, subject to an optional nonzero source-type
filter. `RefreshFromMicroFunctions` additionally has a VC/VT branch, detects
scene-family type 4, reconciles the match and falls back to template 58 for a
scene family or template 26 otherwise, with group 56.

`ReconcileTemplateAndGroup` reads flags at macro object +0x8c/+0x8d/+0x8e and
remaps template/group identities. Their semantic meanings and positive entry
values remain unclosed. The inspected fresh macro constructor contains no
explicit writes to these flags. A bounded scan of named InputSource, IOPE unit,
agent and Aux-form method ranges found no matching byte `mov` writers. That
limited scan does not establish a complete writer census or runtime values.

The Aux recoder visits all four stage members and encodes each using retained
scene, ramp and preset selectors. At 0xd5084f..0xd508c9 a zero stage-2 raw member
is first seeded according to the replacement microfunction: type 2 gives 0x19,
type 4 gives 0x11 and type 5 gives 0x17. Every stage setter then invokes virtual
+0xa0, the scene synchronization callback. Retaining old neighbor bytes without
running this model cannot establish their preservation.

`RefreshTemplateFromMacroFunction` locks the template callback while assigning
the recognized template. In the template-after-change handler, the function-6
primary-block defaults occur before the lock check: a zero timer becomes 300
seconds and a missing expiry command becomes microfunction type 15. Locking
alone therefore does not prove suppression of these defaults.

The selected advanced function path retains its previous raw stage value,
changes the microfunction model, refreshes macro/template recognition and checks
application-dependent availability before writing its encoded stage. It writes
the stage twice around scene-index handling and can convert a custom template
26 containing scene microfunctions to template 58. A supported non-scene subset
must prove those branches are unreachable or own their effects explicitly.

`SetAuxValues` serializes +0xb0/+0xb4/+0xb8/+0xbc, except template 16 forces all
four stored stages to zero. Aux2 is serialized only when present. UnitSpec
locations are Aux1 JP/SR/LP/LR at 0x96..0x99 and Aux2 at 0x9e..0xa1. These
locations are candidate dependencies, not admitted edit parameters. The full
`SaveInputSources` contract additionally covers every input's block association
array and both sensor/Aux branches; an isolated component must disclose its
exclusion and pin its own complete serializer ownership.

## Exact remaining gate

1. Recover the ordered macro/group factories, complete raw function type/family
   decoder, default group selection and reachable matching/reconciliation rules.
   Stable flags settle only one part of this model.
2. Bind a positive initialized entry graph through `LoadInputs`, model creation,
   macro refresh and template callbacks, including source/input identity,
   application, scene/bistable state and lock/updating state. Prove the supported
   top-level row can initialize without normalization.
3. Recover `PopulateMacroFunctionsApp1`, `PopulateMacroFunctionsApp2` and
   `PopulateMacroFunctionsScene` membership, so replacement-template availability
   and fallback 26 are executed exactly or refused explicitly.
4. Admit all four retained stage selectors, zero-stage-2 seeding and dependent
   state. Positively exclude or own scene synchronization, function-6 timer
   defaults, shutter/pot effects and parent-tab callbacks.
5. Define the owned PP projection, complete raw dependency guard and rollback
   contract. Source hashes or UnitSpec addresses alone do not provide them.

The companion JSON names exact next recovery method ranges. This audit used
static PE reads and Capstone disassembly only. No original execution, CPU
emulation, tests, native save/reload, hardware/network operations or production
changes occurred. Prior evidence files and commits were preserved.

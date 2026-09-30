# IOPE input-function source boundary

No input-function edit API is admitted by this review. The two inspected original
routes are the Aux function selector and the advanced Aux microfunction row
editor. Their initialization, template recognition and dependent model effects
are not yet complete enough to establish a bounded component projection.

The source candidates are IOPE1R1, IOPE2R2 and IOPE2C4 firmware
1.0.00..1.2.99. This identifies the research boundary; it does not add those
profiles to a new callable function contract.

## Aux function selector

`TfrmIOPEAuxInputs.HandleFunctionComboChange` (0x118b17c) refreshes the macro,
invokes `AttemptExtensionClick`, applies shutter recall overrides when applicable,
and refreshes group controls and other tabs. `AttemptExtensionClick` reads the
original global preference object at offset 0x1a; an enabled preference invokes
a dependent extension dialog. An offline component must explicitly reproduce or
bound that policy and recover the actual flash-combobox selection binding.

The template-after-change event has hidden defaults: function type 6 changes a
zero primary-block timer to 300 seconds and an absent expiry command to Off.
Shutter function types 17, 18 and 20 select LightStoreLevel 249, 252 and 255.
These are observed branches, not a general input-function encoding table.

## Advanced Aux row candidate

The advanced `ComboPropertiesChange` handler (0x11b14c0) branches on row kind.
The top-level function row (sentinel -1) invokes `UpdateMicroFunction`
(0x11b0cc8); child parameter rows invoke `UpdateKeyParameters` (0x11b0f80).
Both routes then refresh this panel and other tabs. The follow-up
[template transaction audit](iope-template-transaction.md) pins this branch and
the remaining factory, initialization and serializer dependencies. `UpdateMicroFunction` invokes the selected
microfunction setter, macro refresh and `EnsureAvailableMacrofunctionIsUsed`
before writing the stage code. That availability check uses the actual input's
application, scene status and bistable-dependent subset; an unavailable template
is replaced by factory type 26.

The complete template factory matching and `ReconcileTemplateAndGroup` behavior
have not been reproduced. Consequently a requested simple microfunction cannot
yet establish preservation of the other stages merely by retaining raw bytes.

The exact `TInputSource` VMT bindings are now resolved:

| Slot | Original target | Recovered effect |
| --- | --- | --- |
| 0x94 | 0xd5130c RefreshBlocksFromTemplate | Delegates to literal base no-op |
| 0x98 | 0xd513e0 RefreshMacroFunctionFromTemplate | Scene-modify path calls macro Changed; ordinary path assigns template |
| 0x9c | 0xd50e38 UpdateMicrofunctionCodes | Delegates to source-specific recoding of stage commands |
| 0xa0 | 0xd51320 RefreshInputAfterMicroFunctionCodeUpdate | Synchronizes selected scene objects |

`AssignTemplate` assigns an entire default microfunction group, and the recoder
uses retained ramp, preset and scene data across the source's stages. Exact
advanced row identities, initialization stability, application/group/scene
objects and dependent block/preset/pot state still need a closed contract.
The no-op block callback alone does not close those dependencies.

## Serializer boundary

The original `SaveInputSources` (0x12df258) serializes every input's block-reference
Boolean array and invokes both `SetSensorValues` and `SetAuxValues`. This is a
full-dialog save effect. A future bounded component may exclude full-dialog save,
but must explicitly document that exclusion and bind its own serializer and raw
read dependencies. Neither the broad save nor the stage setter alone proves
neighbor or inactive-control preservation.

## Evidence and next closure

`research/fixtures/iope-input-functions-source-review.json` pins the original
EXE/MAP hashes, 32 named method ranges, two VMT metadata ranges, the Aux Inputs
and Aux Microfunctions resources, and four decoded UnitSpec hashes. The review
contains no vendor executable/specification bytes and no personal project data.

The next implementation gate is a source-backed template/stage decoder and
application/subset model that can reproduce one exact initialized advanced Aux
row transition, including all template and recoding callbacks. It needs positive
synthetic graph metadata and explicit refusal of unsupported normalization,
scene/pot dependencies and unsupported retained bytes. Only then can canonical
PPPlan replay, stale raw-dependency guards, rollback tests and native targeted
save/reload acceptance be meaningful.

No production module or tests were added. No original execution, emulation,
physical operation or native save/reload acceptance was performed for this
candidate. Static hashes and resolved callbacks are research evidence only.

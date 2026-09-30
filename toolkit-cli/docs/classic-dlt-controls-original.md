# Original classic DLT control evidence

`research/classic_dlt_controls_original.py` recovers the classic DLT control
binding and executes the original Toolkit 1.18.0.2754 x86 instructions against
synthetic boolean attributes. Its frozen receipt is
`research/fixtures/classic-dlt-controls-original.json`. It requires the pinned
EXE, MAP and decoded `I_DLT.xml`; none is committed.

The model property `BlockDynamicUpdates` is the inverse of programming parameter
`EnableDynamicLabels` (`I_DLT.xml` byte `0x3E`, bit 6, default 1). The agent
constructor binds that parameter to its field `+0x200`; the unit constructor
binds the property to `+0x2DC`. Both unit property accessors use that same field.
The load fragment at `0x121C106..0x121C128` reads the parameter, inverts it and
calls `SetBlockDynamicUpdates`.

The original save has two distinct phases. The inherited
`TCBusUnitCGateAgent.SaveProgrammingInformation` computes `agent+0xC0` from the
`Database` verb. The DLT `BeforeSaveProgrammingInformation` fragment at
`0x121D3A0..0x121D400` stores the inverse property for a database save. A network
save initially sets `EnableDynamicLabels=1` so label programming can proceed.
After ordinary physical programming, `AgentSave` calls
`SaveEnableDynamicLabelsOnly` unless the operation includes `Database`,
`AlignUnit` or `DBReaddress`. The separate ClearLabel and SaveFlavours branches
also bypass that ordinary path.

`SaveEnableDynamicLabelsOnly` at `0x121D8D0` does nothing when blocking is false.
When blocking is true, it sets only `EnableDynamicLabels` to literal `0` and
saves with a 30,000 ms timeout. With an existing programming session it performs
SetOne and Save; otherwise it surrounds those with Lock, Start, Load, End and
Unlock. This establishes the final control polarity; it does not authorize
collapsing the original physical label-transfer lifecycle into one generic save.

The retained emulator cases cover both load states, both property values under
each database flag, and both property values with and without an existing
session. The original accessor and dedicated-save method instructions run;
Variant helpers, attribute storage, unit lookup and programming calls are fixture
hooks. No original GUI, native server, physical device or real project is used by
this probe. Its receipts complement separate native C-Gate save/reload tests.

The same report includes reproducible static extraction from
`research/classic_dlt_language_original.py`: 22 original method spans and all 69
language factory identifiers. The Global pane's `chkDLTDynamic` checkbox binds
to `BlockDynamicUpdates`; its language combo binds to the network's
`LanguageTypes` and `LanguageTypeDefault`. The default is a numeric language
identifier, not a combo index or a classic unit PP byte. Network language record
ID 0 stores this identifier in `TagValue`; the fallback is identifier 1 (English).

Changing that original Global language combo also dispatches network
`SET_LANGUAGE` broadcasts for standard-lighting-like applications, then Enable
203 and Trigger 202. KEYL5 refreshes each key's `GroupLanguageFlavours` from that
network default while the per-key selection remains `ExtensionNeo.LabelFlavour`.
An offline metadata/text edit therefore does not reproduce the whole original
language-change action.

Regenerate with explicit private inputs:

```sh
python research/classic_dlt_controls_original.py \
  --executable /private/CBusToolkit.exe \
  --map /private/CBusToolkit.map \
  --specification /private/unitspec/I_DLT.xml \
  --output research/fixtures/classic-dlt-controls-original.json
```

On macOS, Unicorn needs executable JIT memory. A sandbox-denied run can terminate
with SIGILL before any emulated instruction; run this bounded offline probe in
an environment that permits local JIT execution. This does not require network
or hardware access.

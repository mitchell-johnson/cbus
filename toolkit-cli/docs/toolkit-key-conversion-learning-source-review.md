# Learning state during classic-to-Neo conversion

The original fresh-target conversion path gives the modern Neo target model
`LearnedFlag=false` and `LearnedFlagOriginal=false` when its conversion hook
runs. For the bounded target firmware `2.5.00`, the hook therefore makes
`LearnMode` and `LearnAnyApp` writable and makes `LearnedFlag` immutable.
This conclusion comes from the constructor and conversion call order, not from
reading C-Gate PP values or assuming a user's previous editor history.

The sanitized [source receipt](../research/fixtures/toolkit-key-conversion-learning-source-proof.json)
records the exact Toolkit 1.18.0.2754 EXE/MAP hashes, method hashes, call sites
and VMT slots. Original code and GUI execution are not claimed. The scope is
the 21 modern target classes used by the separately selected 93 registered
classic-to-Neo directions, with source firmware `1.2.67` and target `2.5.00`.

## Why the target has no prior learned history

`TCBusUnitConversion.Convert` calls the unit factory at `0xcaeb7f`. The factory
constructs a fresh registered class through `CreateInWorkSpace`; it does not
reuse the source or an editor's retained target object. All 21 reviewed target
constructors enter the common NeoPro chain. The inherited learn-unit
constructor at `0xede1c0` creates separate Boolean attributes for
`LearnedFlag` at model offset `0x1a0` and `LearnedFlagOriginal` at `0x1a4`.
Their Boolean constructor explicitly writes false at `0x7f4511`. None of the
reviewed descendant constructors overwrites these values.

At `0xcaee7e`, conversion stores the source pointer in target offset `0x158`.
The subsequent `ProgrammingParameters` load is sent to the **source** model.
The target receives `UnitCreate, Database`, then `UnitAttributes, Database`.
The create path writes database identity and scalar fields; it does not take
the `ProgrammingParameters` save branch. The attribute-load dispatch resolves
to `LoadDatabaseUnitAttributes` at `0xcb8c44`, whose five reads are TagName,
UnitName, Description, SerialNumber and CatalogNumber. It does not hydrate the
target's learning model from PP.

`AlignUnit` calls `AlignUnitNoSave` at `0xcc02fd`. Alignment copies source
**agent strings**, applies the tweaker and invokes the target conversion hook
at `0xcc0684`. Target programming setup and PP loading follow at `0xcc0312`
and `0xcc032e`; the target model's `ProgrammingParameters` reload is later
still, at `0xcc03a1`, after saving. Those later operations cannot provide the
history consumed by the earlier hook.

Boolean getters do not conceal a lazy PP load. Their `ResolveChange` chain
ends in the concrete target's `TManagedFlashObject.ResolveChange` at
`0x76a444`, which only clears a change marker. All 21 reviewed target VMTs
resolve that slot to the same routine.

## Exact hook rule

The learn hook at `0xcc5f70` computes:

```text
LearnMode.mutable = target.LearnModePropertiesEnabled
LearnAnyApp.mutable = target.LearnModePropertiesEnabled
LearnedFlag.mutable = target.LearnModePropertiesEnabled
                      and not target.LearnedFlag
                      and target.LearnedFlagOriginal
```

For these target classes, `LearnModePropertiesEnabled` resolves to
`0xc9e014`, which compares the firmware string lexically against `1.2.63`.
It is not a numeric-component version comparison. `2.5.00` passes that
predicate, and the two constructor-false model values make the final
`LearnedFlag` writable flag false. The hook sets flags; it does not substitute
the aligned source PP `LearnedFlag` string for either model Boolean.

`AfterLoadProgrammingInformation` at `0xcc5d20` is a different lifecycle
operation. When enabled, it sets the model's current and original learned
values from the negated Boolean CGate attribute. Such a prior load or a caller
edit would invalidate the fresh-target premise. A retained/editor target
therefore needs its actual model context; a raw PP snapshot cannot establish
`LearnedFlagOriginal`. Other target classes, firmware selections and GUI
histories remain outside this receipt.

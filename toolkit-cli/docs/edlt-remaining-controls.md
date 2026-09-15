# Remaining eDLT global controls

This inventory concerns this unchanged EDLTUnit/FrmBaseUnit dialog and its directly exposed settings. It is not a claim of all Toolkit or all profile functionality.

| Area | Current coverage / remaining work | Original evidence and important boundary |
|---|---|---|
| General timings, status report, Tools lock, previous/preset restore selection | Existing General helper | LongPressTime,DebounceTime,StatusRequestInterval,ToolsPageLocked,EnableLevelStore. Actual power-cycle/physical restore behavior remains separate. |
| Display text sizing, big icons, Timer flash, Fan wrap | Existing Display helper | FontStyle,UseBigIcon,EnableTimerFlash,EnableFanControlLevelWrap. |
| Standby timing/destination and nightlight | Existing Standby helper | ActivityDuration,TimeoutPage,EnableNightlightUserKey/PageKey,NightlightColour. |
| Screen/indicator/page colours and brightness | Existing Colours helper | 9 fixed fields and 6 group controls. Numeric group references explicitly do not perform metadata auto-add. |
| Page mode/navigation variants, names and navigation temperature source | Existing Navigation helper | NavWidgetType/Variant, shared static page names, temperature/dynamic source metadata. |
| Quick Status | Existing Quick Status helper | QuickStatusMode, Group, Colour1..3 and Level1..2; see its separate acceptance. |
| Time/Date global formats and MRA shared settings | Existing Time/Date and MRA helpers | TimeFormat,DateFormat,TimeDateLeadingZero; MRA multiplexer/zone. Their widget-specific placement/active-control limits remain as documented. |
| **Unit Activation** | Activation helper; see [activation contract](edlt-activation.md) | 5 PP fields plus 6 human options. Guards depend on existing standby state; conditional primary/trigger group list. |
| **Primary/Secondary Applications** | Bounded original model/two-control workflow implemented; [contract](edlt-applications.md), original/native and CLI acceptance on both Python versions | CBusBaseUnit.PopulateAllLists: cached app ranges 48..127 plus 136; secondary `<Unused>` 255; each excludes the other current value. Changing either triggers PopulatePrimarySecondaryApplication and CheckIfGroupsExist, which traverses widget GetGroup and scene group/trigger checks. Secondary-disable effects and retained scene references are covered for the bounded composition. Dependent control panels, metadata creation and the complete form remain open. |
| **Page Control** | Implemented numeric group workflow; [contract and dual-Python acceptance](edlt-page-control.md) | FrmBaseUnit “Control Page Shown By Group Level”; KeySetsEnableGroup byte 0x131, fixed Enable application203, `<Disabled>` 255. Despite the parameter name, the visible feature is page control, not an established generic unit-disable command. Physical level→page mapping needs separate source/protocol evidence. |
| **Corridor Linking** | Bounded ordered control workflow accepted on both Python versions; [contract](edlt-corridor.md); offline and native CLI accepted on both versions | Link/Office/Corridor groups at 0x132/133/136, primary app. Link 255 disables Office/Corridor controls; lists mutually exclude the other roles. Timer 0x134 int16, UI 60..64800 seconds; changed model values expose the original byte-clamping quirk. Actual widget GetGroup enumeration and complete ordered primary-group cache drive validation. Ten accepted native cases each have full save/close/load verification; full-form and physical behavior remain separate. |
| **Widget preset level editor / synchronised sliders** | Bounded editor implemented; [dual-Python acceptance](edlt-restore-levels.md) | Exact16 constructed controls, displayed-name coupling, same-value no-event behavior and post-edit type-reset precedence are implemented.64 captured Windows cases match all874 fields in four phases; 16tests on both Python versions include15 fresh native/original cases with save/reload each. Requires positive caller cache facts; missing-group normalization, full form initialization and physical power-cycle transfer remain incomplete. |
| **Clear Dynamic Labels** | Guarded one-request workflow and persistent independent fixture; [contract and dual-Python acceptance](edlt-label-clear.md) | FrmBaseUnit btnClearLabel→CBusBaseUnit.ClearEdltLabel→CGateCommunicatorFactory.ClearEdltLabel→native connection.LabelClearEdlt. Physical-only button Enabled rule. Existing label text/icon/Unicode/language transport does not establish clear acceptance. |
| **Network Label Editor / default language save** | Existing bounded label transport only; whole dialog lifecycle not claimed | btnEditLabels launches LabelsMain(network); Save can call Network.SaveDlt and SendSetDefaultLanguageCommand. These are network metadata/transport operations, not global EEPROM label fields. |
| **Global Programming selected-category copy** | Still separate multi-unit workflow | FrmBaseUnit.SaveUnitForGlobalProgramming lists exact category fields, marks them changed, adds OverallCRC and saves destination DB unit. Global Save also has physical/label branches. Single-unit helpers do not implement this orchestration. |
| **Reset/Clear Widgets, factory reset, template dialog, live status refresh** | Separate operational workflows; not implied by global helpers | Buttons call ResetUnit,FactoryReset,TemplatesDialog,UpdateUnitStatus. Existing generic/default/template/native functions need their own mapping/acceptance inventory before declaring these dialog actions covered. |
| Unit identity/address/project/tag/notes | Existing project/programming/addressing modules have bounded coverage | Form fields are partly readonly; exact EDLT identity synchronization/ConfigVersion getter and reset/load side effects are outside the new settings scope. |

### Stored fields that are not proven editable UI controls

- `LabelAlignment`: original EDLTUnit getter/setter and Left 0/Centre 1/Right 2 constants exist; FrmBaseUnit creates a binding source with that name, but no editable control uses it anywhere in the inspected original assemblies. Do not invent a label-alignment UI workflow solely from the schema.
- `InvertDisplay`: model getter/setter and schema bit exist; AfterLoadPPData unconditionally clears stored 1. No editable control binding found.
- `EnableWidgetDividers`, `LevelBarStyle`, `DefaultTempUnit`: schema GlobalParameter entries but no model/UI usages found in the inspected eDLT and CBusLogicModel sources. Preserve them; list as stored/reserved or unexposed until stronger evidence appears.
- `CustomMacrofunction1..8{SP,SR,LP,LR}Microfunction`: tagged global in XML, but used as shared widget macro storage. Existing widget writers cover their proven serialization; a generic arbitrary macro editor is not established by that tag.
- The unused `languagesBindingSource` declaration does not establish a unit-level EEPROM language selector.

## Source ledger

- EDLTUnit.cs:174..202 DefaultPage and ignore visibility;402..413 trigger-level guard;426..449 standby parent;554..573 IgnoreFirst;865..924 proximity properties;1260..1291 radio mappings;1319..1393 AfterLoad/bindings;1429..1441 widget group enumeration;1986..1992 proximity-level notification;2001..2017 corridor conflict validation.
- CBusBaseUnit.cs:428..459 primary/secondary bindings and callbacks;859..861 ClearEdltLabel.
- PPAttributeDataSourceLogic.cs:11..31 mutating group getter/setter;56..70 EnableLogic; PPAttributeLogic disabled sentinel behavior.
- BindingListCBusObject.cs:74..99 conditional constructor;121..174 controller/parent changes;194..244 range/exclusion/255 list construction.
- PPAttribute.cs:280..325 initialization-mode notification behavior.
- CBusNetwork.cs:311..335 default-create application lookup; CBusApplication.cs:71..113 default-create group lookup and user-driven auto-add behavior.
- CommonConstants.cs:187..199 label alignment/event choices;338..342 activation page choices.
- FrmBaseUnit.cs:1047..1051 visibility;5436 activation parent;5452/5485 radios;5467 page;5523..5585 group/mode/action;5622 primary value;5636 ignore;6461..6485 Page Control;6486..6572 corridor;2178..2206 preset slider linking;2603..2616 Clear Dynamic Labels;2964..2971 Label Editor;1420..1490 global programming field lists.
- KEYGL5.xml defines the exact field layouts; its source hash is listed below.

## Pinned source hashes

The inventory was audited against Toolkit 1.18 and the exact KEYGL5/5055EDL/5.5.00 profile. Vendor sources are local research inputs and are not bundled with the CLI. Stored-schema-only fields are distinguished from actual editable controls; generic PP writes do not establish their full UI semantics.

| Input | SHA256 |
| --- | --- |
| `research/vendor/toolkit/app/CBusLogicModel.dll` | `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs` | `641f5abc1c3762cd86a0c4b18bc125424a39017a3d78d6edfa4e1e2964af62b2` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel.Units/CBusBaseUnit.cs` | `4f0468941222c6696db5836a32fc0b70d18fcf704ea8fe6dd0c2d709a3842487` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel.ProgramableProperties/PPAttributeDataSourceLogic.cs` | `a3b56f80b6abb9ba3b24cd9778e450ba8aca3a592f181e04c8eafdfeb600056b` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/BindingListCBusObject.cs` | `700dc6020b82886b9ed69c94c07cddfd0da64da4d14d18941e8308ce75563bbe` |
| `research/vendor/edlt-decompiled/eDLT/eDLT/FrmBaseUnit.cs` | `060323b11494c7a697656d048f97351526a143e339db767731675a87ba1b1b16` |
| `research/vendor/edlt-decompiled/eDLT/eDLT.Controls/NumUpDownPercentage.cs` | `8af1e7a0096314fbd393c28f9d0989f813c91a0a26adc946ea7ceee0a3c1af70` |
| `research/vendor/unitspec-plain/KEYGL5.xml` | `812d2f92ccf3176d9f3d4c0f35fc196ac9ba45bc419639421e4e5ff082d2af21` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/CommonConstants.cs` | `98e20887cf973205eaa42e621f0ee21ee5b9367aac1553f88c75b86e16d39020` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel.ProgramableProperties/PPAttributeLogic.cs` | `b07e0d2dfac418867e2cce36449fc36e2e60d7a3017fe20c55539ff5eade1b1c` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel/PPAttribute.cs` | `6c057abce7de8793501e34b326d862a9bbc2c2e32ed6c7b7ace796b0ad29e9cb` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs` | `ddd65e5d34d94f3b0468f0db5a8468c0b6b5cdc50b8a49ca27b9f7331000d39c` |
| `research/vendor/edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusApplication.cs` | `669554fea6b53c01a2d0d0c1d7cf8c89cd76d68af0b7d2b11f3bb73a6bfe5933` |

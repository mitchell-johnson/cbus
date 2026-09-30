# Specialized output project documentation

The saved-snapshot documentor renders the `RELDF1` fan body for canonical
firmware `2.4.00`–`2.4.99`, `2.5.00`–`2.5.99` and `2.6.00`–`2.6.99`.
Its native class supplies one output channel and zero logic groups.
The report prints the inherited channel table followed by the Master, Slave or
Stand Alone appendix. A slave links its resolved master and has no speed table;
the other roles print the original threshold ranges and stored labels.

This profile requires explicit consumed PP data. `FanTriggerGroup != 255`
selects Master. With an unused trigger group, `StandAloneConfig` either selects
Stand Alone or permits `MasterUnitAddress` resolution in the same saved network.
A missing or known non-fan candidate resolves to Stand Alone; an unknown class
remains partial. The original resolver accepts a fan unit referring to itself.
This models a fresh database unit load, not retained live-model state or a UI
operation that synchronizes slave parameters.

Those three catalogue ranges share one unconditional `RELDF1.xml` schema and
the same native `TRELDF1` / `TCBusFanControllerCGateAgent` registration. The
specification has no includes or parameter-level firmware conditions. The
consumed constructor/loader fields, threshold setters and role getter have no
firmware-specific mappings. The extra AgentLoad master-copy operations require
explicit verbs and are outside this fresh snapshot projection. Catalogue
display class names are not used to select the native class. This supports the
software snapshot projection throughout the ranges. Catalogue metadata and
these source mappings do not establish native or hardware acceptance of the
firmware continuum. Noncanonical strings such as `2.4.1` remain partial.

The threshold table preserves native edge behavior. Low appears only when its
threshold is positive, Medium only when the two thresholds differ, and High
always appears. Lower bounds add one after the original level-to-percent
conversion. Reversed thresholds remain reversed; a high threshold of 255
produces `101% - 100%`. Label lengths are explicit, clamped to eleven UTF-16
units, and markup is left unchanged as in the original report. This projection
admits BMP text only; surrogate and astral character copying remains partial.
An incomplete inherited channel table does not hide a known appendix or become
recovered. Fan output group usage describes `Channel 1`, including group 255.

`DIMDU4`, `DIMPR3A`, `DIMPR6A` and `DIMPR12A` have independently pinned concrete
factory registrations, `TDIMDNUXCGateAgent` loading, and four, three, six and
twelve output channels respectively, with four logic groups. Their explicit PP
channel/logic data can use the shared DIN report projection. Stored firmware
must resolve to the corresponding native registration; absent or malformed
firmware does not select a class. This report projection grants no device
editor or programming support.

Those four error-report outputs resolve `TriggerErrorGroup` in application 202
and selectors by **Address**, independently of their Value. Group 255 disables
both actions, but selector address 255 is an ordinary action. When the two
selectors match, `Trigger Error Report` and `Trigger Error Report Clear` both
append in that order. A missing selector preserves a known match while marking
the result partial. `EnableErrorGroup` uses application 203 and describes
`Error Report Enable Group`, including group 255. These dependencies do not
depend on an invented ErrorMode gate.

The evidence is reproducible from the private pinned Toolkit 1.18.0.2754
EXE/MAP and decoded `RELDF1.xml` specification:

- `research/project_documentor_special_outputs_static.py` verifies 49 checks
  for concrete factories, channel and logic counts, loader fields, label-copy
  limits, role resolution, threshold branches, selector address lookup, action
  append order, group dependency methods, uniform consumed schema and catalogue
  ranges. Its receipt is
  `research/experiments/2026-09-30/project-documentor-special-outputs-static.json`.
- `research/project_documentor_special_outputs_original.py` executes the
  original fan appendix and LevelToPercent instructions in six synthetic
  cases, and the error action method in all four match combinations. The
  inherited Output body, object getters and Delphi string operations are
  bounded hooks. The receipt is
  `research/experiments/2026-09-30/project-documentor-special-outputs-original.json`.
- `tests/test_project_documentation_special_outputs.py` has 50 passing focused
  tests with static receipt regeneration and one intentionally disabled original
  CPU-probe regeneration. It covers retained original output
  comparisons, self-referencing slaves, missing and inactive PP, label copying,
  threshold edge cases, action Address/Value distinctions, group 255, partial
  status preservation and integrated dispatch. All 300 canonical versions are
  compared against the same complete synthetic snapshot projection; this is a
  software model comparison, not new execution of 300 original loaders.

Neither probe executes the original whole loader or captures a generated
project page. Full-page byte and visual comparison remain unassessed.
ArchitecturalDimmer and Bytecraft L1 bodies retain their unrecovered markers;
old DIMPR12 uses the separate [bounded Bytecraft body](project-documentation-bytecraft.md).
Their additional loaders and report fields are outside this specialized-output slice.
The original leaf probe needs permitted local JIT memory on macOS. It starts
no Windows process or C-Gate connection and performs no hardware actions.
It was not rerun for the firmware-range extension.

# Project documentation group and action usage

`project_documentation_usage.py` supplies the per-unit descriptions used in the
Inputs, Outputs, Other and Trigger Action Selector sections. These are bounded
source-derived rules from the pinned Toolkit 1.18 executable and MAP. They do
not establish full-page, browser-layout or printing parity.

Supported group dependency families:

- The eight existing DIN output profiles in `din_output_settings.PROFILES`:
  output channel descriptions first, followed by logic groups in native order.
  A matching logic group is described even when unused. RELDN8 uses its existing
  source-pinned channel-to-PP mapping. Input and Other descriptions are empty.
- RELAY1, RELAY2, RELAY4, DIMMER4 and AN_OUT4: six logic group descriptions in
  logical group order, without channel descriptions. Other reports the area
  group; Input is empty. This follows the group dependency method independently
  of the separate ClassicOutput documentor's GA5 rendering behavior.
- KEY1, KEY2, KEY4, KEYIR1, KEYIR4, KEYAUX4, DINAUX4, KEYBC2 and KEYBC4: Input
  descriptions iterate four blocks, then the physical keys. An unused macro
  does not count as a key use. An assigned group with no active key is described
  as `Block (Unused)`. Other describes the area group before the indicator
  brightness group. The latter is disabled for auxiliary and bus-coupler types.
  On the remaining types, the original loader assigns that group whenever the
  IndicatorBrightness PP value is nonempty, including fixed brightness values.
  Output is empty.

Classic key ActionSelectorUse preserves the original key-major then block-major
order and duplicate uses. The recall-2 branch is nested inside the stored-level-1
comparison: stored level 1 must equal the selector's Address before stored level
2 is tested against its Value. The helper preserves this native behavior and the
separate Address and Value properties. A retrigger-timer microfunction (7) uses
its block's expiry command; start-timer (8) does not satisfy that branch.

The helper returns `Usage(html, status, missing)`. `recovered` with empty HTML is
positive evidence that the admitted method reports no use. Missing consumed PP
values remain `partial` or `unrecovered`; an unknown unit/action implementation
also remains `unrecovered`. The caller must retain those distinctions when
rendering and reporting unresolved coverage. Returned group HTML contains the
native pipe-delimiter conversion to `<br/>`; the caller supplies the unit link
and enclosing lists. Classic key action text has no additional `<li />` prefix.

## Evidence and focused verification

`research/project_documentor_usage_static.py` checks 65 facts against the pinned
original EXE/MAP: effective group-method VMT dispatch for all admitted families,
key and virtual-key counts, indicator-brightness capability, native resource
labels, section wrapper literals, and the four-block/unused-macro constants. Its
receipt also inventories hashes and addresses for the consumed native loader
methods. The frozen receipt is
`research/fixtures/project-documentor-usage-static.json`.

`research/project_documentor_usage_original.py` executes the original
`TClassicKeyInputDocumentor.ActionSelectorUse` instructions in an x86 emulator
for ten synthetic cases. Only that method's original instructions may execute;
unit getters, collections, type identity and Delphi string routines are stubbed.
This independently checks the original method's branches, ordering and emitted
strings against the Python helper. It does **not** execute the PP loader, the
complete native object graph, or original project-page generation. The frozen
cases are `research/fixtures/project-documentor-action-original.json`.

Run the focused test with the repository's Python environment:

```sh
PYTHONPATH=toolkit-cli/src python -m pytest -q toolkit-cli/tests/test_project_documentation_usage.py
```

The optional test replay requires `CBUS_TOOLKIT_EXE` and
`CBUS_RUN_DOCUMENTOR_ORIGINAL=1`; it runs the emulator in a subprocess so a
host executable-memory restriction cannot terminate the whole test process.

Both research scripts require `--executable`, `--map-file` and `--output`; the
emulator additionally requires Unicorn and executable-memory support. They
reject any source hash other than the pinned original pair. No live C-Gate,
network, GUI or household hardware is used. Remaining gaps include other device
families' group usage, non-classic ActionSelectorUse implementations, and an
original generated-page capture.

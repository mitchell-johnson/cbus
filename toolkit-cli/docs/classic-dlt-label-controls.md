# Classic DLT text and dynamic-update controls

Classic DLT labels are project data. The unit stores a 1..4 variant selection
for each of eight PP slots and an `EnableDynamicLabels` bit. It does not store
the project label strings. The bounded workflows here edit database PP and
saved native project XML; they do not send labels to a unit.

## Block Dynamic Updates

`dlt labels show` reports `block_dynamic_updates` alongside the raw enable
bit. `dlt labels plan` and `cgate unit ... dlt-labels` accept
`--block-dynamic-updates yes|no`, optionally together with `--variant`:

```sh
cbus-toolkit dlt labels plan --file neo.json --block-dynamic-updates yes --variant 8=4
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 \
  --dry-run dlt-labels --block-dynamic-updates no
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 \
  dlt-labels --plan reviewed-control-plan.json
```

The control uses `cbus-classic-dlt-control-plan-v1`; existing variant-only
plans remain supported. Applying a control plan re-derives its writes from
the requested controls, checks the exact unit identity and native layout,
and rejects stale input before any write. It verifies every selected field,
the complete slot bytes, and preservation of all seven neighboring bits of
byte `0x3E`. A partial/uncertain PP failure is reported without retry, rollback
or save. Existing database-only destination admission remains in force.

Original Toolkit evidence establishes the inverse polarity:
`BlockDynamicUpdates = not EnableDynamicLabels`, with the latter at byte
`0x3E`, bit 6. `AfterLoadProgrammingInformation` inverts the flag, and the
database branch of `BeforeSaveProgrammingInformation` writes its inverse.
The physical save path behaves differently: it first enables dynamic labels,
then a later dedicated save restores blocking when requested. That physical
sequence is not implemented by this database workflow.

The source receipt
[`classic-dlt-controls-original.json`](../research/fixtures/classic-dlt-controls-original.json)
pins the original executable, map, methods, and recovered control bindings.
The original-instruction probe executes the retained methods/fragments on
synthetic memory with dependency calls intercepted. It is separate from an
executed original GUI or physical-device acceptance.

The owned original C-Gate receipt
[`classic-dlt-controls-native.json`](../research/fixtures/classic-dlt-controls-native.json)
covers KEYBL5 2.1.00, KEYML5 2.0.00/3.0.99 and KEYDL4 2.1.00/3.0.00.
Each profile changes `0xFF → 0xBF → 0xFF → 0xBF`, preserves every other PP
field except explicit variant selections, then survives PP save and project
save/close/load. Public CLI acceptance separately covers show, dry-run, saved
plan, stale refusal, blocked/allowed states, and project reload.

## Text variants and languages

`dlt text` edits explicitly addressed existing Group or Trigger Control
action-selector labels in native `Installation`/`Project` XML. Numeric
language IDs and variants are explicit; no language names or defaults are
inferred, and no physical slot-to-group mapping is guessed.

```sh
cbus-toolkit dlt text show --project-xml project.xml --target //P1/254/56/20
cbus-toolkit dlt text plan --project-xml project.xml --target //P1/254/56/20 \
  --edit '1:1=Kitchen' --edit '2:1=Cuisine' --edit '1:4=Main' > text-plan.json
cbus-toolkit dlt text apply --project-xml project.xml --plan text-plan.json --output labelled.xml
```

Text records use `TagsDLT/TagDLT` with `LanguageID`, `FlavourID`, `TagType=TEXT`
and `TagValue`. The plan binds the exact input XML digest and recomputes the
candidate on apply. Existing OIDs, other variants/languages, unrelated
metadata and unit PP are retained. An empty text value keeps an explicit
blank TEXT record. Replacing FONT/ICON records, deleting labels, creating
groups or actions, editing network language definitions, choosing a global
language, and transferring/rendering labels remain outside this workflow.
The output is a new local XML file; it does not save to a running C-Gate
database. Text length admission is a local resource bound, not a claim about
classic screen capacity or the label transport.

The original C-Gate comparison is retained in
[`classic-dlt-project-text-native.json`](../research/fixtures/classic-dlt-project-text-native.json).
It covers Group and Trigger action labels, language IDs 0/1/255, all four
variants, blank text, XML escaping, Latin-1, Chinese/emoji, 1024 characters and
TAB/LF/CR. New label OIDs are allocated; an edited existing label keeps its
OID and unrelated variants. Labels, language metadata and a Trigger action's
distinct Address/Value survive project save/close/load. Network language
entries use `ID`, while ID 0's `TagValue` carries the default-language
identifier. The source extraction also retains the original 69 language
identifiers; the text workflow requires explicit numeric IDs.

## Focused verification

Run the focused tests with `PYTHONPATH=src:tests:.` from `toolkit-cli`.
The native tests use `CBUS_NATIVE_SERVICE_BACKEND=local`,
`CBUS_LOCAL_CGATE_VENDOR`, `CBUS_CGATE_JAVA` (Java 11), and
`CBUS_UNITSPEC_DIR`; all projects and processes are owned temporary fixtures
on loopback. `CBUS_DLT_CONTROL_REPORT` writes the native controls receipt.
Set `CBUS_TOOLKIT_EXE` for `tests/test_classic_dlt_original.py` to replay the
original instructions (its adjacent `.map` is used unless `CBUS_TOOLKIT_MAP`
is supplied). Set `CBUS_DLT_TEXT_NATIVE=1`, `CBUS_DLT_VENDOR_ROOT` and
`CBUS_CGATE_JAVA` for `tests/test_dlt_project_text_native.py` to rerun the
original text comparisons.

Physical display output, the full original classic dialog, network label
transfer, physical save ordering and power-cycle persistence remain
unverified. Firmware below 2.0 and internal catalogue revisions stay refused
for the unit controls. These additions do not establish full DLT/Toolkit
feature parity.

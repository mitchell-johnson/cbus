# SENLLA surface-mount light-level components

Inspect an identified SENLLA / 5754PE / 2.4.00..2.4.99 PP export offline:

```sh
cbus-toolkit sensors --spec-dir decoded-specs surface-light-level-view sensor.json
```

The command reads thirteen surface fields through `SENLLA.xml`: target and
margin bytes; target, margin and bank group addresses; their three level-store
flags; three power-up group levels; bank threshold behaviour; and eight bank
usage bits. The export must carry its unit type, firmware and catalogue number.
It preserves the export and specification files. The result binds the raw
consumed values in `expected`, reports loaded component state and supplies the
source-derived `component_overlay`. This overlay covers the surface serializer,
not the whole Toolkit dialog transaction; the result marks
`complete_toolkit_save` false. No C-Gate endpoint or edit options are involved.

The three store flags use the memory codec's effective one-bit layout.
Their specification may omit `BitSize`, which defaults to eight in descriptive
schema metadata. Native bit packing still consumes one bit and ignores
`ArraySkip`; integer field layouts remain exact. The
[provider-schema correction receipt](../research/fixtures/senlla-bit-layout-owned-release-20261004.json)
records focused source and installed-wheel validation, including all eight
store-flag combinations and the public command with authored omitted metadata.

The native surface loader gives a used target group precedence over a stored
margin group: it loads logical target byte 45 and clears the loaded margin
group. Its serializer writes the target group into both group slots, target
byte 200 and the derived percentage margin. Margin-only mode loads percentage
9 and serializes the inherited target byte as its margin byte. Fixed modes
clear disabled group level-store flags. A used target group also makes the
margin power-up level and store flag follow the target fields.

Raw inputs must fit their recovered unsigned field widths. A derived surface
margin outside 0..255 refuses the view instead of clipping it or claiming a
saveable byte. This can occur with a used target group and a very large loaded
margin ratio. Fixed component mode retains the raw target byte, including
values above 200; fresh dialog control clamping is outside this view.

Bank behaviour 1 selects low usage; 0, 2 and 3 select high usage. An unused
bank group clears both usage sets and saves behaviour 0 with group 255. Saved
usage is the union of logical low/high usage. Separate pure helpers expose the
recovered current-level display formulas and logical bank serializer. Logical
bank vectors do not establish how all eight raw key/block values initialize
the bank state.

SENLLA has eight keys and one indicator. Its ordinary save calls inherited ST7
save before surface serialization. The similarly named SENLL forced-parameter
helper belongs to conversion, and is excluded from this view. SENLLA's Global
frame also follows the inherited multisensor chain, where separate source
recovery proves the same minimum-three initialization. Global fields are
outside this thirteen-field component view. The existing SENLL save command
continues to refuse SENLLA.

The [static source audit](senlla-surface-source-review.json) records the
catalogue/specification identities, 120 method pins and eight literal component
vectors. It predates implementation and executes no original instructions,
GUI, vendor service or hardware. Eight-key load/macro marshalling, complete
nonzero-key Scene behavior, fresh controls/group creation choices and live
level side effects remain under recovery before ordinary-save admission.
Issue41 and complete Windows Toolkit parity remain open.

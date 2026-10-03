# SENLL Global status interval initialization

An unchanged fresh SENLL ST7 dialog saves stored `StatusReportInterval` 0, 1
or 2 as **3 seconds**. Values 3..255 are preserved. An explicit
`--status-report-interval 3..255` overrides the initialized value, while values
outside that selector domain still refuse. This behavior applies to the
retained 43-field profile and complete 47-field Area/Scene snapshots, on flat
saves and ordered on/off histories.

The native Global frame builds the fixed list of 3..255 choices, installs its
change handler and then populates the selection from the loaded integer.
Formatting a loaded value below 3 selects the displayed label 3. The text
notification and queued change-unlock path invoke the installed handler,
which writes that integer to the unit before explicit controls. Source review
checked fresh DFM defaults, no preselection, both handleless and allocated
edit notification paths, nested change locks and the inherited PP save.
The [static audit](senll-global-status-source-review.json) records 44 method
pins and the pinned resource identity. Original GUI execution remains unrun.

Plans preserve the original raw byte in `expected`. A plan made from raw 0
refuses if the session changed to raw 1, even though both initialize to 3.
Apply checks the final interval domain before reading native schema or values;
forged 0..2 values and omitted required normalization cannot reach PP SET.
The existing identity/schema/readback and source-derived enabled scene guards
remain in place. A failed readback or lost successful save does not cause a
retry or rollback. The byte 66 update preserves its neighbors and unrelated PP
rows. Configured interval bytes do not establish observed physical behavior.

`control_history.global_status_initialization` records the raw and initialized
values. Its phase follows source getter loading and precedes explicit on/off
controls. Explicit interval override remains later in `flat_dialog_edits`.
The initialized value is serialized before SENLL's final forced fields.

This closes the previous below-3 initialization refusal for the admitted ST7
profile. It does not extend sensor families, retained GUI histories, nonzero
key collections or native/physical acceptance. Issue41 and complete Windows
Toolkit parity remain open.

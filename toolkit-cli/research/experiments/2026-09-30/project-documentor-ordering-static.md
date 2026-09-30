# Project documentor ordering: pinned static evidence

Toolkit 1.18.0.2754 source evidence establishes that the original fresh default
for applications, groups and levels is **tag-name ascending**, not address
ascending. The `SortModeApplications`, `SortModeGroups`, and `SortModeLevels`
HKCU preferences default to false; true selects address ascending. Both
choices are custom ascending comparators. Networks and database/physical
units are fixed to numeric-address ascending by their owners.

`GetAllProjectInfo` explicitly calls `LoadAndSort` for networks, applications,
groups and levels. It loads every flash object and runs the existing manager
comparator, without choosing a different sort mode. The report then enumerates
those managers. Numeric sorting remains a defensible explicitly selected
offline profile; it is not the native fresh-process default.

Both custom comparators place address 255 first for Network, Application and
Group objects (including descendants), but only when left and right are
different objects. The left-255 override executes first, followed by the
right-255 override, so two distinct eligible address-255 objects compare +1.
Units and levels have no such exception. `InsertHTMLNetworksNEW` and contents
enumerate every network without a network-255 exclusion. Applications skip
the unassigned object by identity; groups skip `IsUnused`.

Tag-name comparison calls Delphi `AnsiCompareText`, which calls Windows
`CompareString` with locale `0x400` (`LOCALE_USER_DEFAULT`) and flag `1`
(`NORM_IGNORECASE`), then subtracts 2. Python case folding is not an exact
replacement. The original middle-pivot quicksort is unstable and has no
secondary comparison for equal names. Native locale, persisted preferences,
and earlier manager operations remain relevant to exact output.

The [JSON receipt](project-documentor-ordering-static.json) records both
verified source hashes, 28 method spans/hashes, addresses of key calls and
conditions, and the acceptance boundary. No original code bytes or site data
are retained. No original GUI or generated report was executed or compared.

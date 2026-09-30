# Document Project status-report minimum

The pinned Toolkit 1.18 EXE/MAP source verifier is
`research/project_documentor_status_static.py`. Its adjacent JSON receipt
records the verified image hashes, method spans, factory/interface inventory,
CGate-agent load paths, and model hash. It neither executes the original nor
compares an original generated HTML page.

`TProjectDocumentor.GetNetworkMinimumStatusReportInterval` starts at 99999 and
iterates the unit manager. A unit participates only if it supports
`ICBusInputUnit` (GUID `b9f6b2d7-40ec-4399-883d-f40f76931f58`) and its runtime
programming-load flag at offset `0x16d` is true. A strict less-than comparison
retains the first unit when intervals tie. The unchanged sentinel produces
`None`; a selected unit produces the integer immediately followed by
`secs on Unit ` and `DisplayHTMLUnit`. The numeric value is not multiplied,
clamped to three seconds, or treated specially at zero.

The 425 original factory registrations cover 334 concrete classes. Of these
registrations, 108 expose the interface through 94 classes; the rest do not.
Both interface getter implementations return a stored integer attribute:
`TCBusInputUnit.GetStatusReportInterval` or
`TIOPEUnit.GetStatusReportInterval`. Inherited common input-agent loaders map
the `StatusReportInterval` PP directly to the former; IOPE has a separate
verified direct scalar mapping to the latter. `TPC_GIM`, `TSENCT4`, and the
shadowed old `TKEYGL5` class retain an unrecovered PP mapping. Factory order
matters: KEYGL5 first selects `TCBusEDLTUnit`, which does not expose this old
interface, rather than the later registered `TKEYGL5` class.

The offline helper reports a projected minimum only if every potentially
participating unit has known class/firmware membership and a valid recovered
scalar. A missing PP is unknown, never evidence that a unit lacks the
interface. Empty or verified noninput-only networks produce known `None`.
An unknown type, missing/malformed/out-of-range firmware, incomplete scalar,
or unrecovered input mapper invalidates the entire minimum. Numeric firmware
is an explicit admission bound; malformed native version-string behavior is
not projected.

The native documentor sets the load flag before attempting each programming
load, then clears it in each of its 14 recognized exception handlers. Saved
XML cannot establish whether that native load succeeded, failed, or was
cancelled. The result therefore carries
`stored_pp_snapshot; original programming-load success/failure not observed`.
This is source-backed offline projection, not native report acceptance.

Validation: 36 focused unit tests cover absence versus unknown, incomplete
snapshots, class/firmware gating, duplicate factory registration precedence,
zero/one/two without the UI's three-second clamp, integer and hex scalars,
signed bounds, sentinel behavior, IOPE mapping and first-tie selection.

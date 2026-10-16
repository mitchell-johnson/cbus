# Ordered DIN slider controls

This batch advances [issue 40](https://github.com/mitchell-johnson/cbus/issues/40)
with ordered Turn On/Min-Max and recovery-delay controls for the eight existing
DIN firmware-2.7.00 profiles. It builds on the separately published agent-save
projection; it does not close the device-editor umbrella.

Both `din-settings plan` and `cgate unit ... din-settings` accept `--controls`
with an ordered JSON array. Eight operation kinds cover Synchronise checkboxes,
minimum and maximum sliders, recovery-delay sliders, and the corresponding
Stagger buttons. Direct edit flags cannot hide an unspecified order inside
the history. Optional `--toolkit-save` performs one final agent-save projection.
Existing targeted v1 and normalized v2 settings plans retain their behavior.

The separate control-plan format retains every operation, initial and final
slider state, callback events, and its nested settings plan. Applying a saved
history replays and validates the complete result before parameter staging,
then uses the existing whole-snapshot stale check and strict schema-width
checks. No save retry or recovery write is introduced.

The recovered behavior includes:

- Same-position assignments emit no callback and preserve noncanonical raw
  bytes, even while Synchronise is on.
- Min/Max coupling runs before the outer synchronization callback. Endpoint
  clamping and guarded target setters can leave different sender/target values;
  the implementation does not force a uniform result afterward.
- Stagger disables the corresponding Synchronise checkbox and walks channels
  in dialog order. Local slider coupling remains active. Relay Turn On uses
  the minimum threshold, including RELDN8's distinct PP indices.
- Delay staggering uses the original extended constant and ceiling conversion,
  rather than an assumed inverse of the displayed ten-second scale.
- Unrelated histories clamp the displayed position of stored delays below five
  while preserving raw bytes. Delay-edit histories with those initial values
  refuse because implicit loading callbacks are outside the admitted profile.

The [source annex](../research/fixtures/din-output-controls-source-review.json)
pins 40 method spans, three form resources and 12 virtual dispatch slots.
The read-only [verifier](../research/din_output_controls_static.py) reproduced
those bindings and the exact extended constant from pinned original bytes.
Independent review checked callback order, literal edge cases, plan tampering
and the delay display correction. No original instructions or vendor server
were executed.

The focused pure and public tests use literal expected arrays, including all
eight profiles, all four delay choices, no-op preservation, coupled endpoints,
hidden controls, strict JSON types, stale plans and altered coherent receipts.
The 20 public backend cases comprise sixteen full journeys and four dropped
successful-save replies. They compare offline and database previews, staged
bytes, one owning PP save, fresh PP reads, explicit project save/close/load and
unrelated project preservation on both cgate-mock and cmqttd. Synthetic contact
traps check that the represented network is never contacted.

Both frozen nine-module source and fresh installed-wheel selections passed
**130 parent tests and 640 separate subtests**, with **five provisioning skips**
and zero failures each. Each run executed all 20 public backend cases. The
five skips cover two static original-byte provisions, historical original
conversion-instruction regeneration and two native-server DIN provisions.
Separate static byte verification passed; those reads do not convert any
original-runtime or native-server skip into acceptance.

All **2,728 scoped inputs and both owned binaries** remained unchanged. All
**378 package files** matched source, wheel and installation, and the actual
wheel pytest process imported only installed package files at startup and
exit. The installed console also produced the literal coupled 76/79 byte
arrays with `PYTHONPATH` absent. Six regenerated compatibility receipts,
register/census checks and independent source/outcome reviews passed. The
[release receipt](../research/fixtures/din-controls-owned-release-20261003.json)
pins input, package, test-trace and raw backend evidence. Component smoke
scopes overlap these runs and are not added together. No full suite ran.

After both test epochs, internal storage briefly refused a reporting heredoc.
Only this task's disposable Python environments moved to external storage,
with their original paths retained as local symlinks. Test evidence and Rust
binaries remained intact; the installed-console check then passed. Report,
status and release-receipt annotations follow validation without changing
runtime, tests or generated compatibility metadata.

Recovery-level/store/shared-group callbacks, group creation, implicit initial
form notifications, other firmware/models and physical timing/power-cycle
acceptance remain open. See the [operator contract](din-output-settings.md)
for exact operation schemas. The functional census is still incomplete.

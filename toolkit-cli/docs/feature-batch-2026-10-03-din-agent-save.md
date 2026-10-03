# DIN relay and dimmer agent-save projection

This batch advances [P5.03 / issue 40](https://github.com/mitchell-johnson/cbus/issues/40)
by adding the previously omitted agent-save effects to all eight existing
DIN firmware-2.7.00 profiles. It does not close the relay/dimmer/occupancy
controller umbrella or establish complete Toolkit parity.

`din-settings plan --toolkit-save` and
`cgate unit ... din-settings --toolkit-save` apply one recovered agent-save
projection after requested control edits. Ordinary DIN units normalize channel
level-store recovery bytes, pad unused group/level slots and mask relay
interlock values. RELDN8 follows its distinct marshalling override, preserves
short-array tails and can remap its maximum array again on a later explicit
save. The command performs one projection. Existing version-1 targeted plans
retain their behavior; version-2 plans bind the pre-save edits and exact final
projection and refuse changed, malformed or stale results. Native schema width
is checked before v2 staging.

Read the [operator contract](din-output-settings.md) for the exact array rules
and remaining control boundaries. The additive
[static source annex](../research/fixtures/din-output-save-source-review.json)
pins twelve original method ranges and corrects the earlier broad RELDN8
summary. Independent PE reads verified all twelve range hashes. No original
instructions or original server were executed in this batch.

The focused source selection passed 31 parent tests and 38 separate subtests,
with four original/native/static-input provisioning skips. Separate static-only
checks passed after the pinned executable was explicitly provided. The
20-case owned-backend selection passed without skips: sixteen full journeys
(eight types on each of cgate-mock and cmqttd), plus four successful-save
reply losses without replay. These scopes overlap and are not added together.
The public journeys cover literal complete parameter results, unchanged
unrelated project content, offline plans, native dry-run staging, one PP save,
fresh readback, explicit project save/close/load, stale/tampered-plan refusal
and legacy targeted-plan compatibility. Their synthetic network contact traps
received no connection. Structural preservation uses the existing parsed XML
comparison and does not claim byte-for-byte native XML representation.

The user requested fast focused validation while the broad runs were active.
Those runs were interrupted cleanly: source had 558 passes, 611 skips and 525
separate subtests; mock interoperability had 32 passes, one skip and 158
separate subtests. Both exited 2 after KeyboardInterrupt. They are incomplete
runs and do not constitute passing full-suite or maintained-interop gates.
Final focused source validation passed **141 parent tests**, with **588
separate subtests** and **four provisioning skips**. The seven-module fresh
installed-wheel selection passed **107 parent tests**, also with **588 separate
subtests** and **four skips**. Source additionally included the 34 receipt
sanitization cases. Both executed all 20 DIN public-backend cases. The four
skips were the static original-byte input check, original conversion-instruction
regeneration, native DIN module acceptance and native DIN CLI acceptance. The
separate static-only input check passed; it does not turn any original-runtime
or native-server skip into acceptance.

All **2,698 scoped source inputs** and both owned Rust binaries remained
unchanged across validation. All **373 package files** matched source, wheel
and installation at terminal. The actual installed `cbus-toolkit` console
produced the expected v2 plan with `PYTHONPATH` absent. The
[machine-readable receipt](../research/fixtures/din-agent-save-owned-release-20261003.json)
binds these scopes to candidate bytes and retained execution traces; its base
Git commit alone does not identify the uncommitted execution tree. The bounded
counts overlap and must not be added. Current publication-head CI is not claimed.

The integration successor merges main `83b49d10` (repository capacity,
dual-key controls and Neo reports) while preserving the published DIN commit
`801a5775`. DIN runtime and tests remain unchanged; Rust matches the merged
main revision exactly. Both seven-module source and fresh installed-wheel
selections passed **107 parent tests and 588 separate subtests**, with the
same **four provisioning skips** and all **20 public DIN backend cases** each.
All 2,721 scoped inputs and two freshly rebuilt binaries stayed unchanged;
all 377 source/wheel/installed package files matched. Six fresh owned metadata
comparisons, register/census checks and independent merge review passed.
The [integration receipt](../research/fixtures/din-main-integration-20261003.json)
also retains the corrected collection/build setup failures. This is focused
integration evidence; no full suite or new original/native/hardware gate ran.
Historical release receipts above remain unchanged.

Remaining work includes Synchronise Sliders and Stagger, re-entrant
shared-group controls, original form initialization and notifications,
application/group object creation, other firmware/models, and physical
output, timing and power-cycle acceptance. The compatibility ledger remains
18 implemented categories out of 42; the functional census remains incomplete.

# Direct owned-Rust fixture launches

The nine fixture families affected by issue #128 now launch the selected owned Rust executable directly. They pass the synthetic UnitSpec directory with the existing `--unitspec` or `--cgate-unitspec` option and preserve the existing authentication argument where required. The test bodies, synthetic specifications, effect assertions, lost-receipt checks, cleanup behavior and startup PCI expectations remain in place.

Previously these fixtures wrote a Python shebang launcher that called `os.execv` to replace itself with Rust. The strict installed-wheel guard observed that intermediate Python startup without its ordinary launch and terminal records. The earlier hosted failure, including its 312 wrapper startups, is retained as a failed epoch. The fixture change removes those intermediary launchers; the maintained installed-wheel runner and import guard are unchanged.

The changed modules are `test_cgate_din_save_interop.py`, `test_cgate_senll_controls_interop.py`, `test_cgate_senll_inventory_interop.py`, `test_cgate_toolkit_tweaker_interop.py`, `test_cgate_edlt_scene_add_dialog_interop.py`, `test_cgate_toolkit_tweaker_dlt_interop.py`, `test_cgate_toolkit_tweaker_remaining_interop.py`, `test_cgate_edlt_parent_add_dialog_interop.py` and `test_cgate_edlt_global_images_interop.py`. All paths are under `toolkit-cli/tests/`.

The affected selection contains 631 explicit identities across 24 modules. The source run executed that selection once. The fresh installed-wheel run executed separate mock and daemon phases using the same frozen selection and selected Rust binaries. Collection-only checks carry no passing-body credit.

| Actual scope | Passing parent bodies | Failures / errors / skips / subtests | Retained direct Rust processes |
| --- | ---: | --- | ---: |
| Source affected selection | 631 | 0 / 0 / 0 / 0 | 629: 312 mock, 317 daemon |
| Fresh wheel mock phase | 313 | 0 / 0 / 0 / 0 | 312 |
| Fresh wheel daemon phase | 318 | 0 / 0 / 0 / 0 | 317 |

The source pytest reported 3,751.79 seconds; its owning driver exited zero after 3,753.024 seconds. The fresh-wheel owning driver exited zero after 5,249.859 seconds. Every phase has its own raw JUnit, collected/started/call trace, maintained audit and retained journals. No combined wheel JUnit or trace was manufactured.

All 4,174 source inputs were unchanged before and after each owning run. The fresh wheel contains 395 product files that match the frozen source, fresh build copy, wheel ZIP, installed package and distribution RECORD. The RECORD has 406 entries. The selected Rust executable bytes were unchanged; this test-only change did not build Cargo or modify Rust behavior.

The strict wheel origin audit accepted both actual pytest processes and their recognized Python descendants, with zero violations. Its mock phase records 1,037 Python processes and 200,934 origin records; its daemon phase records 1,044 Python processes and 202,242 origin records. All 312 and 317 owned Rust children respectively were reaped, and their PID, direct argv and reap status match the raw process journals. These are the maintained guard's recognized-launch and source-loader checks, not universal attestation of arbitrary executable code.

The data-only raw readback counted the following retained traffic. Offline CLI calls are separate from the relay traffic. Seed and other direct owner traffic outside those relays is outside the command totals.

| Actual scope | Recorded CLI calls: exit 0 / exit 1 | Separate offline CLI calls: exit 0 / exit 1 | Relay connections / tagged commands | Actual dropped upstream successes |
| --- | --- | --- | --- | --- |
| Source | 1,526 / 288 | 136 / 4 | 1,792 / 48,796 | 86 × 200 and 6 × 301 |
| Wheel mock | 762 / 141 | 68 / 2 | 892 / 24,372 | 43 × 200 and 3 × 301 |
| Wheel daemon | 764 / 147 | 68 / 2 | 900 / 24,424 | 43 × 200 and 3 × 301 |

All retained Rust process journals record reaping and closure of owned listeners, PCI and broker resources. The mock reap status is the recorded termination signal -15; the daemon status is zero. The 317 daemon journals in each execution contain exactly eight startup PCI receive frames each, totaling 2,536 rows, with no later PCI traffic. Each wheel phase has five declared refusal faults in addition to its 46 dropped successes. Exact fault tags, selected occurrences, once-only forwarding and retained upstream replies were checked; an intentional earlier pre-backup save is not classified as a retry of the lost later save.

There are 629 raw journals for the source scope and 312 / 317 for the separate wheel phases. Only 146 source journals and 73 journals per wheel phase contain a literal test node ID. Membership of all selected bodies comes from the actual JUnit and trace; a one-to-one journal-to-body mapping is not asserted. Explicit zero closed-graph-trap contacts are present in 625 source journals and 310 / 315 wheel journals. Four source global-image journals, and two per wheel phase, omit that field; there is no universal trap-zero claim.

The process-free fixture-forwarding packet passed 22 cases. The unchanged guard and CI tests passed 120 parent tests and 14 subtests in their separate scope. Two separate tiny negative probes confirmed that the strict audit still rejects an unknown Python shebang/exec handoff and an unobserved Python spawn. Their earlier one-pass/one-failure probe epoch is retained because one help-text assertion used the wrong capitalization before reaching its guard assertion. Those packets are not counted as part of the 631 product bodies.

Three data-reader preparation failures are also retained: a log-path variable shadow in the first raw reader, an occurrence-one assumption that misclassified ten intentional second saves, and an empty declared-module argument in the first package/origin readback. Immutable reader successors corrected those artifact-only checks; no product replay or product-input change was needed to read the completed epochs.

This is focused owned-Rust acceptance. The full configured declaration of 1,007 explicit identities and seven whole modules was not executed locally by this selection. The complete hosted installed-wheel lane remains pending, and issue #128 stays open for that gate. No original C-Gate, vendor, physical hardware, home network, universal Toolkit parity or full native/hardware claim is made. Existing compatibility and source/native gaps remain open.

The fixture author also wrote the raw journal reader. Product execution, maintained gate results and the independent static readbacks are separate evidence scopes. The package/origin artifact check reuses the pinned maintained read-only helpers; it is not a second implementation of the strict guard.

Retained artifact descriptors identify the exact evidence without publishing private paths, auth contents, project XML or raw hex payloads:

| Logical retained artifact | SHA-256 | Bytes |
| --- | --- | ---: |
| Source-scope raw author readback | `ae2856bfcb717665dba6a713e32e51cb8d93c9c255b5f21d5c0f7b5a6d4887eb` | 1,577,106 |
| Wheel mock raw author readback | `fefe44a1b038a610139b7a955330a136c3bce1ab1865c28584e36fc944bc51da` | 784,845 |
| Wheel daemon raw author readback | `71ae40119893eebf20df738baf5cf935fc04200ce7a29499004156e210d3e35f` | 797,191 |
| Wheel package/origin artifact readback | `bdb8c2874128b7017bef606945463fac12e578c695fe8c7b6edd4402102eb9f1` | 5,039 |
| Maintained mock exact-ID audit | `13ef44b4437d6f34a309e7cbd8a9e52b4d30d6a6c97a46d6cdd16b1fe873a606` | 212,402 |
| Maintained daemon exact-ID audit | `d9c9cd83d2fb6d876d4ebea6165f4173c700f786effb3fd12634fb139a53f358` | 217,944 |

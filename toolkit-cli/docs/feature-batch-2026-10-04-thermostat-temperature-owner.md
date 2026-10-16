# Thermostat temperature owner integration — 4 October 2026

The bounded settings owner now loads all 15 raw temperature fields into its shared live integer model and encodes final live values once per issued save. Raw PP, loaded values, current model values and final encoded PP remain distinct. This implements the transaction boundary from [issue 119](https://github.com/mitchell-johnson/cbus/issues/119). The wider thermostat workflow in [issue 42](https://github.com/mitchell-johnson/cbus/issues/42) and manual/native source prerequisites in [issue 72](https://github.com/mitchell-johnson/cbus/issues/72) remain open.

The [operator guide](thermostat-temperature-model.md) describes raw-edit survival, owner seals and the unchanged Celsius/settled control profile. Ordinary settings, output-only and damper-only histories retain their legacy raw round-trip helper. The owner preference is independent of device TemperatureUnits. This slice adds no temperature slider, timing control, Fahrenheit owner initialization or implicit Windows scheduling.

Testing used baseline `3497204ba319ad6de2cbddefac8ce9215ee19436` with the exact file overlay pinned in the [release receipt](../research/fixtures/thermostat-temperature-owner-release-20261004.json). This evidence was prepared before its own PR publication; parent PR 117 CI was pending at that acceptance/preparation checkpoint. Main release and required CI remain separate from these focused local results.

| Terminal epoch | Parent outcomes | Separate passing subtests | Elapsed |
| --- | --- | --- | --- |
| Source `source3`, corrected new backend module | 40 PASS, zero failures/skips | 0 | 91.00 s |
| Fresh installed wheel `wheel2`, 11 whole modules | 318 PASS, one optional static-source SKIP, zero failures | 636 | 184.41 s |
| Separate source metadata `metadata1` | 22 PASS, zero failures/skips | 5 | 9.04 s |

The wheel skip is `test_optional_static_source`: original EXE/MAP inputs were not supplied for that optional static verification. No original software, native Schneider server or physical thermostat was executed. Parent counts and subtest events are separate. The source backend selection is one 40-body module; it is not a unified green source run of all 319 parents. The metadata cohort overlaps other checks and is not added to their counts.

The 40 backend IDs cover 20 cases per cgate-mock/cmqttd backend: eight chained-save profiles, 16 prebackup refusals and 16 lost-save profiles across PC_TSA, PC_TSA5, PC_TSB and PC_TSB5. In each source/wheel raw-review scope there were 64 CLI calls and connections, 3,624 tagged commands, 32 successful exits and 32 expected refusal/uncertainty exits. Sixteen actual upstream 200 save responses were discarded; the client did not retry or roll back them. Forty owned processes were cleaned up. Their 160 expected startup PCI frames were followed by no hardware traffic or closed-graph trap contacts.

The synthetic Basic/Programmable profiles verify complete 101/109-parameter projections, opaque existing Level.Value metadata, identity, leaf-preserving project graphs, both distinct backups and successful save/reopen. A requested raw 120 survives as live 50 and saved 120. A new load of saved 128 produces the separate uncapped 129 save; repeating serialization of an unchanged live model does not introduce a hidden reload. Refusal no-mutation is supported by passing assertions and wire checks; a second refusal PP/project snapshot was not separately serialized. The artifact reviewer authored the fixture expectations and excludes independent approval of its own oracle semantics.

The actual before/after map stayed exact within each phase: 395 packaged files, 778 Python test files and four named temperature research inputs, totaling 1,177. This is not a whole-repository, Rust, private-harness or all-fixture closure. Make/CI and documentation were outside that map; their separate readback and CI guard checks remain separately qualified. The 395 source/snapshot/ZIP/installed package files are byte-identical. The fresh wheel is `b3f8f3a50373dd21967e5324fa467cc7a58bb5dbd2a8da09e8e3604e8bc4244f` (3,013,547 bytes). Each source3/wheel2 parent pytest recorded 43 terminal product-module origins with zero violations; this does not prove continuous or CLI-child import origins.

Three red epochs are retained unchanged:

| Retained epoch | Parent outcomes | Passing subtests | Elapsed | Correction |
| --- | --- | --- | --- | --- |
| Source1, 11 modules | 310 PASS, 8 FAIL, 1 SKIP | 636 | 160.38 s | Changed-only preview oracle included an unchanged capped127 field. |
| Source2, new 40-body module | 32 PASS, 8 FAIL, zero SKIP | 0 | 87.88 s | The second backup name exceeded the existing eight-character limit. |
| Wheel1, 11 modules | 310 PASS, 8 FAIL, 1 SKIP | 636 | 181.79 s | The same second-backup name defect. |

Only the backend test changed between those input maps; all 395 production package files remained exact after the first frozen integration. The narrow test successors preserve whole PP/graph equality, raw 120 and complete encoded maps, distinct backups, save ordering/counts and real lost-response/no-replay assertions. Earlier static reviews missed the two fixture errors; their failed runs and review qualifications remain retained.

CI/Make registers 985 exact backend IDs: the inherited 945 are unchanged and the 40 new IDs are split 20 per backend. Historical 907/829/813/745 digest guards remain. The new pure/owner modules and both backend selections require passing bodies. `make check-thermostat-temperature-owner` runs the focused 11-module cohort with explicitly supplied existing binaries and has no Cargo or original-software prerequisite.

The changed Make/CI closures required two separate Rust-only producer refreshes. Tagged SESSION_ID passed 11 cases per existing debug binary; the Unit mapper passed 12 exact-wire cases plus two combined Network reads per binary. The four maintained sanitized derivatives preserve their full technical payload. That earlier producer epoch separately froze 473 Rust inputs and both binaries; the Python phase map did not capture Rust. No new Cargo build/test gate or original execution is credited to this Python batch. Contract inventory, parity register and skip-census check commands returned 0.

The category ledger remains 18 of 42; this is not a functionality percentage. The register still has 487 provisional obligations with zero accepted, 22,103 scope items and an incomplete census. Installed `coverage --require-complete` returned 1 without a trusted evidence root. Full original form, application migration, Delete, native/physical acceptance and broader initialization remain unclosed. Hashes for source, tests, gates, private raw artifacts, the wheel, existing binaries and qualified reviews are recorded in the public receipt; private paths and raw logs are omitted.

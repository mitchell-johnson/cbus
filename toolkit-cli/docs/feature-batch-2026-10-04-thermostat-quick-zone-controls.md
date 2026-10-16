# Thermostat quick-zone owner validation

The settings CLI now composes explicit quick-zone checkbox histories, plant selection and owner-issued message delivery with existing output Select/Add/Edit and damper controls. The [control guide](thermostat-quick-zone-controls.md) defines the admitted Celsius/settled profile, operation schema, source callback order and separate Basic/Programmable save rules. Issue [42](https://github.com/mitchell-johnson/cbus/issues/42) remains open for the wider workflow.

The tested Python code is recorded in commit `b099ad917973d2007d7d555ebc3629556f77b5fd`. Execution occurred on baseline `42d2b326e18e0c19b2ed8721c6fefd0c71c7b1a6` with the exact code/test overlay later committed there. The source pure and source backend phases ran separately; no combined source 199-parent epoch was run.

| Actual terminal epoch | Selected modules | Passing parent bodies | Passing unitemized subtest events | Failures / skips | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Source pure | 4 | 157 | 5 | 0 / 0 | 32.33 s |
| Source owned-backend | 1 | 42 | 0 | 0 / 0 | 351.11 s |
| Fresh installed wheel | 5 | 199 | 5 | 0 / 0 | 283.87 s |

The maintained execution audits passed. Collected, started and passing parent IDs match in each epoch, and every required module has passing bodies. The five extra passing events retain their parent ID and have no separately itemized subtest identities; they are not five additional parent tests. The pure phase emitted a pytest cache-permission warning without a test failure.

The fresh wheel has 394 package files with identical source, ZIP and installed bytes, excluding bytecode caches. At the acceptance checkpoint, all 1,962 declared snapshot inputs matched the stage and source; documentation and this receipt were appended afterward. Actual pytest terminal records identify the selected interpreter and 31 source-pure, 41 source-backend and 42 installed product modules from the expected package roots, with exact source bytes. This observes the parent at session finish; it is not continuous monitoring, child-CLI import tracing or a full Git-checkout closure.

Each backend epoch has the same 42 passing identities: 38 owned-service records and four schema refusals before any TCP connection. The 38 records comprise 24 positive histories, eight refusals, four lost-successful-response cases and two stale-state refusals. Each epoch records 62 CLI calls, 3,968 tagged commands, 48 successful exits and 14 expected refusal/uncertainty exits. Four actual upstream tagged `200` responses were discarded; the resulting uncertainty stops without retry or rollback. All 38 service children were cleaned up. The 152 PCI startup frames per epoch were startup-only, with no later PCI traffic.

The assertions cover synthetic Basic 101-field and Programmable 109-field PP, complete project graphs, shared identities and opaque existing Level metadata, source backup and fresh successful reload, and causal creation/rename wire order. Quoted Edit uses the recovered `DBSET` path with preceding current-OID/old-name guards. Inactive live schedule references are distinguished from the saved 32/33/34 defaults. Refusal preservation is checked by the executed body; the raw refusal record does not independently serialize a second full after-graph. These are owned synthetic C-Gate acceptance cases, with the raw reviewer excluding approval of its own authored semantic oracle.

The owned services are the exact recorded debug binaries: cgate-mock SHA256 `0cbc6c40377cb75a1b83679c8293ffd3a9026df801a7e5c87397f07dd7bc28e5` and cmqttd SHA256 `657a04a65691f321d3431d6d1a86648caad9eaeb2995741a150a16ef8710b956`. This Python batch does not rerun or recredit the Rust workspace gates and makes no fresh release-binary claim.

Earlier outcomes remain separate: an initial source collection failed with seven import errors before body acceptance; the legacy selection passed 147 parents with five skips and 375 subtest events; backend attempt 1 passed four and failed 38 due to fixtures; attempt 2 passed 30 and failed 12 due to source-oracle expectations. The successful successor preserves the strong PP/graph/save/loss assertions while correcting ordered ZoneAfter shutdown expectations, live versus stored schedule values and the quoted Edit command. Source-fidelity review checked the corrected literals against pinned source bodies, and an independent assertion-scope review found no weakening. The component author's source review is not independent semantic acceptance.

The isolated coverage command exited 1 and reported incomplete coverage/census, with no trusted evidence root supplied and functional percentage unavailable. The category ledger remains 18 of 42; that category count is not a functionality percentage. The [sanitized receipt](../research/fixtures/thermostat-quick-zone-owner-release-20261004.json) binds the actual phase, code, gate and review hashes.

Windows message delivery, native control SetText/SetEnabled/focus timing, arbitrary external subscribers, a complete original initialized form, broader temperature/time initialization, application migration, output Delete and physical acceptance remain outside this profile. The earlier component and damper receipts retain their own scopes.

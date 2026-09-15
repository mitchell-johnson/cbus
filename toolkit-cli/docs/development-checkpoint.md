# Development checkpoint

The initial Git checkpoint is `1b40486` on branch `Toolkit`; `fce83df` preserves the retained scheduling corrections and first native-adapter regressions, and `48925ce` records the earlier documentation checkpoint. The current checkpoint adds the accepted native scheduling CLI and supplied-registry condition evaluator. **Toolkit 1.18 parity remains incomplete.** See [implementation status](implementation-status.md) for every feature area, completed function and outstanding task.

## Complete wheel acceptance

The latest complete installed-wheel result remains [1,725 tests on each of Python 3.13.14 and 3.10.20](test-acceptance.json), with zero failures, errors or skips and all 14 native gates enabled. Later focused checkpoints overlap one another and this suite; their counts cannot be added to it. A fresh complete wheel run is still required for the newer tree.

## Native thermostat scheduling

The retained core's earlier [17-test checkpoint](../research/fixtures/thermostat-schedule-levels-acceptance.json) compared all 14 captured original CreateLevels outcomes and ordered phases. The subsequent [29-test development record](../research/fixtures/thermostat-schedule-development-checkpoint.json) added twelve fake-peer adapter tests. Those historical reports remain unchanged and made no native persistence claim.

The [native scheduling API and CLI](native-thermostat-schedule.md) now pass **67 tests on each Python version**, with zero failures, errors or skips. This includes the core and fake-peer checks, public CLI and cleanup/output regressions, plus five native integration methods covering eight project/group scenarios per run. Fresh isolated C-Gate processes verified all three actions, original-record preservation, backups, save/reload, second-action no-op, stale metadata rejection and actual partial writes after injected lost Value/TagName receipts. All owned processes and storage were removed; the listening CNI sentinel observed no connections. The [acceptance record](../research/fixtures/thermostat-schedule-native-acceptance.json) pins the sources, 443-file archive and reports.

The first native pilot exposed that project reload clears the command session's selected project; explicit `PROJECT USE` fixed it and the corrected pilot passed 182 commands. Failed fixture and acceptance-preparation attempts remain preserved separately. The focused runs replay the 14 original captures; they perform no fresh original instruction execution. Outer selection/settings, original service factories, native collection-order equivalence and physical behavior remain outstanding.

## Supplied registry conditions

[Context v2](toolkit-update-registry-conditions.md) adds explicitly supplied HKCU key/entry existence and bounded string/Int32 content comparisons to the existing command. **78 tests pass on each Python version**, with zero failures, errors or skips: 17 new registry tests and 61 condition/metadata/revocation regressions. These compare 11 supported original registry outcomes, explicitly exclude one culture-sensitive comparison, replay 107 Int32 observations and preserve all 248 pre-change v1 reports byte for byte. The [acceptance record](../research/fixtures/toolkit-update-registry-conditions-acceptance.json) pins the exact inputs and reports.

The original v1 registry pilot failed because an exact forwarding dependency was absent. The fresh v2 pilot passed 12 original leaves and 12 independent same-provider witness reads; all scratch keys and handles were cleaned. Supplied facts remain unverified. Live registry observation, other providers/comparisons, rollout, complete applicability and update availability remain separate work.

## CSV database projection

The production [CSV serializer](toolkit-database-csv.md) still takes explicit captured report values. Cached getter research completed ten normal and two declared provider-stop cases. The [prepared backend harness](../research/experiments/2026-09-15/csv-backend-harness-prepared-v2/README.md) passes 15 host guard tests on each Python version, with zero original/native backend executions. Its eight original cases, four native captures and separate replay are the next evidence step; original cold XML/cache loading, associations and complete database-to-report composition are still outstanding.

Authored research source snapshots and their byte hashes are retained under [experiments](../research/experiments/2026-09-15/README.md). Proprietary binaries, large raw reports and VM runtime output remain outside Git. No new complete wheel or physical-device acceptance is claimed by this checkpoint.

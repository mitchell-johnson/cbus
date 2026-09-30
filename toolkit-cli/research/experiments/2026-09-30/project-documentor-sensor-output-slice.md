# Classic inputs, sensors and specialized output reports

This slice extends the saved-snapshot project documentor using the same pinned
Toolkit 1.18.0.2754 EXE/MAP as the existing report recovery. It performs no
device programming, network access, preference mutation or original GUI startup.
The complete original generated page has still not been captured. Method-level
instruction comparisons below use synthetic objects and selected callbacks;
they do not establish the original PP loader or whole application workflow.

## Implemented scope

- Eight classic input bodies: KEYIR1/4, KEYBC2/4, KEYAUX4, DINAUX4, BCNC4A/B.
  Explicit factory class/agent admission pins physical key counts, AUX macro
  reconciliation and BCNC read-only loading. BCNC group and action usage is added.
- Four PIR types under their registered old/ST7 classes: SENPIRSS, SENPIROA,
  SENPIRIA and SENPIRIB. Four ordinary keys, sensor macros, enable polarity and
  ordered group/action usage are projected. Surface multisensor is excluded.
- SENTEMP, SENTEMPB and SENTEMP4 report bodies, plus SENTEMP/B group usage.
  Celsius with period decimal is the explicit project-rendering profile.
- RELDF1 2.4.00 single-channel body, roles, labels, thresholds and output usage.
- DIMDU4 and DIMPR3A/6A/12A output bodies, error/clear actions and Enable usage.

Shared key-table rendering now accepts independently recovered block application
and macro facts. Stored values resolve by application/group identity. Existing
KEY1/2/4 behavior remains covered by its focused tests. Shared output profiles
delegate only the four proven error-report classes to the specialized adapter.

## Evidence and validation

| Area | Static checks | Independent comparisons |
| --- | ---: | --- |
| Additional classic profiles | 93 | 1,769,472 AUX macro source-table comparisons |
| PIR | 84 | 983,040 macro source-table comparisons; 12 original appendix and 15 action cases |
| Temperature | 39 | 18 original body cases, 576 original numeric formatting cases, 511 original Ceil cases |
| Specialized output | 43 | 6 original fan appendix and 4 error-action cases |

Each area has a separate source receipt, research helper, focused tests and
documentation. Independent reviewers checked the runtime/source projections and
retained comparisons without finding blocking mismatches. Original comparisons
completed on their already approved execution route. The final combined run
deliberately disabled all new native CPU probes after the execution-safety notice.

The final combined `test_project_documentation*.py` run used the existing Python
toolchain, pinned read-only EXE/MAP and unit specifications, disabled pytest and
bytecode caches, and set `CBUS_RUN_DOCUMENTOR_ORIGINAL=0`. It reported 656 passed,
8 intentional native-probe skips and 2 stale output-module hash receipt failures.
Regenerating that receipt resolved both failures. The affected output,
specialized-output and sensor-workflow files then reported 85 passed and one
intentional native-probe skip, including four added complete output-body cases.
No full repository suite, Rust build, installation or wheel build ran.

The source CLI also rendered a synthetic native XML snapshot containing all 20
newly admitted type profiles. Every body reported `recovered`, UTF-8 BOM and CRLF
were checked, and the output retained `original_toolkit_executed=false` and
unassessed byte/visual parity. The synthetic snapshot intentionally leaves some
dependency, status and calculator fields absent; its 162 corresponding markers
remain visible. This smoke check does not claim a completely recovered project.

## Remaining gaps

KEYC/KEYCIR need NeoProClassic scene and virtual-key projections. PIR encoded
scene keys and nonempty scene dependency tables remain partial. Architectural
and Bytecraft outputs need their distinct loaders; other fan firmware and
non-BMP fan label copying remain partial. Light-level/multisensor, thermostat,
wireless and remaining specialized bodies are outside this slice. DALI/SENLL
work remains independently owned and must be preserved during integration.

Fresh complete-page acceptance additionally needs an isolated working original
Toolkit runtime, private profile/project state, supported offline project load
and a captured output/ordering/locale trace. Existing leaf receipts cannot
replace that capture. Printing and interactive progress remain unimplemented.

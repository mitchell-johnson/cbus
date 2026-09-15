# Development checkpoint: 15 September 2026

This Git checkpoint preserves the CLI implementation, tests, original-code research tools, captured fixtures and documentation written so far. Toolkit 1.18 parity remains incomplete; this is a development checkpoint, not a release acceptance claim.

The last audited complete wheel ran 1,725 tests on both Python 3.13.14 and Python 3.10.20, with no failures, errors or skips. Its exact wheel, inputs and reports are identified in [test-acceptance.json](test-acceptance.json). Later focused checkpoints are documented separately and overlap; their test counts must not be added to that total.

The newest `thermostat_schedule_levels.py` and `native_thermostat_schedule.py` modules are work in progress. Original CreateLevels research passed twelve supplied-provider cases and two additional existing-address cases, and the original selection predicates passed twenty-four calls. The pure scheduling core has passed fourteen initial Python 3.13 tests, including comparisons with all fourteen captured original cases. Its dual-runtime acceptance and review remain pending; the native adapter has not yet been tested or connected to the CLI. Existing accepted scalar temperature conversions are a separate completed feature.

Proprietary Toolkit/C-Gate binaries, installed runtimes, virtual environments, VM job output and large execution archives remain outside Git. Authored experiment source snapshots and their provenance manifest are stored under `research/experiments/2026-09-15`; original execution archives remain at their recorded local paths. Research probes use explicit owned fixtures and are not production entrypoints.

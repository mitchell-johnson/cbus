# RELDN Toolkit conversion: owned native acceptance

The bounded native check on 2026-09-30 converted seven registered Toolkit
RELDN directions and verified the remaining direction fails before C-Gate I/O.
The eight requested directions are **not all implemented**: `RELDN4 → RELDN8`
remains refused because native RELDN4 logic values have four elements and the
recovered original tweaker directly reads eight. Filling the missing elements
would invent behavior. See the [source review](toolkit-reldn-conversion-source-review.md).

The independently written literal vectors in
[`research/reldn_tweaker_native.py`](../research/reldn_tweaker_native.py) include
distinct group positions, group addresses 0/254/255, nondefault logic, all-one
and all-zero logic rows. The native test compares every planned relay field,
fresh PP readback and raw stored `PP Value` against these literals. It checks
the target's four-element logic truncation for `RELDN8 → RELDN4` separately
from the unsafe short-source reverse direction.

| Native outcome | Directions |
| --- | --- |
| Converted and persisted | RELDN8 → RELDN12, RELDN4, RELDN8B, RELSM8 |
| Converted and persisted | RELDN12, RELDN8B, RELSM8 → RELDN8 |
| Refused before I/O | RELDN4 → RELDN8 |

The [sanitized receipt](../research/fixtures/reldn-tweaker-native.json) records
seven conversions, one pre-I/O refusal, five refused unregistered self
conversions, and 15 source/target units verified after project save, close and
load. No conversion issued a failed PP SET. It also verifies:

- Repeated read-only planning and native `NOOP` leave the database unchanged.
- Source PP and metadata remain unchanged, while selected nondefault fields
  copy correctly and immutable SerialNo remains at the fresh target default.
- Native reload preserves every raw PP string and pre-existing scalar value.
  Reload materializes only the observed `DeviceName=NEWUNIT` and empty
  `GroupNumber` scalar defaults.
- The C-Gate 3.4.0.2001 process owns its ephemeral loopback listeners, adopts no
  project, exits, and removes its temporary directory.

Run only the targeted native check with the explicit private input locations:

```sh
CBUS_CGATE_JAVA=... CBUS_LOCAL_CGATE_VENDOR=... CBUS_UNITSPEC_DIR=... \
  PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_reldn_tweaker_native.py -q
```

The provisioned wrapper passed (`1 passed`). With those inputs absent it
skips, which is not native acceptance. Regenerate the receipt with the same
variables using `research/reldn_tweaker_native.py --output PATH`; its input
hashes cover the selected vendor files and the exact helper, test and relay
implementation files. The receipt retains synthetic relay values but no
vendor specification contents or private paths.

The final targeted run combined the existing conversion tests, the new RELDN
portable tests and this native wrapper: **28 passed, 367 subtests passed**,
with native prerequisites present and no skips. It included all eight existing
DIMDN/DIMDU4 conversions after correcting the inherited immutable Burden flag;
their [separate receipt](../research/fixtures/toolkit-dimdn-burden-native.json)
records all eight project reload comparisons. Neither the full Python suite
nor a Rust build was run for this conversion-only package.

This is client-side Toolkit conversion followed by native database PP
persistence. The helper rejects `CONVERTUNIT` and network-open commands. It
never executes the original Toolkit GUI or contacts physical C-Bus hardware;
GUI conversion behavior and physical programming acceptance remain open.

# python-legacy — archived Python implementation

This directory holds the original Python implementation of the cbus library,
cmqttd daemon, simulator, proxy, and test suite, archived at the Phase 8
cutover of the Rust migration (see `docs/rust-migration/PLAN.md`).

The Rust implementation in `rust/` is the maintained codebase. Wire/MQTT
parity between the two was proven by `rust-migration-harness/run.sh`
(3201 golden vectors + 17 behavioral assertions) immediately before this
archive was created; the harness vectors were generated from exactly this
code.

Notes:

- Nothing here is installed, tested, or maintained. It is kept for
  reference — in particular for features that were deferred rather than
  ported (web UI, zeroconf/mDNS ESP32 discovery, `cbus-proxy`,
  `toolkit/graph.py`, `fetch_protocol_docs`).
- `Dockerfile.python` was written for the pre-cutover repo layout; to build
  the legacy image, use a checkout prior to this commit rather than
  adjusting its paths.
- The harness auto-skips its Python selfcheck suites when the `cbus`
  package is no longer importable (or force with `SKIP_SELFCHECK=1`).

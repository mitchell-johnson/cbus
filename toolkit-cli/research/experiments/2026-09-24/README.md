# Repository refresh evidence, 24 September 2026

These records distinguish current source tests, original-code observations, native C-Gate fixtures and unfinished research. None proves full Toolkit parity.

- `offline-test-summary.json`: 1,872 passed, 239 provisioning-gated skips and 17,337 passing subtests on Python 3.13; all recorded source hashes unchanged.
- `installed-wheel-focused.json`: 46 scheduling tests, Python minimum metadata and entrypoint checks against a fresh installed wheel. This is not full-wheel acceptance.
- `thermostat-outer/`: source snapshot and capture summary for 12 original outer workflow cases. The retained vectors live in `../../fixtures/thermostat-scheduling-outer-vectors.json`. Earlier failed instruction-boundary capture remains external and its hash is preserved.
- `thermostat-native-access.json`: rechecked historical seven-case parameter evidence establishing the owned loopback `Clipsal` fixture configuration.
- `registry-host-review.json`: 108 focused host tests. The production Windows worker has not passed live acceptance.
- `rust-cgate-review.json`, `rust-final-checks.json`, `mock-focused-acceptance.json`: mock fixes, final 50 Rust tests/clippy/format checks and 13 Python interoperability tests with stable binary hashes. Mock behavior retains the listed fidelity gaps.
- `csv-original8-analysis.json`, `csv-native4-analysis.json`, `csv-replay-partial.json`: eight original backend cases, four passed native captures, and the subsequent failed replay after B01/B02. B03 and B04 remain unverified.

Large archives, proprietary binaries and raw execution reports remain on the external volume at the paths recorded in the summaries. Authored harness snapshots contain local research paths and declared providers; they are not portable public CLI commands.

Next work is the missing-group replay method at `0xf28978`, full thermostat load/save composition, and fresh Windows observer acceptance. A prepared thermostat loader probe is retained at `/Volumes/external/cbus-toolkit-thermostat-unit-load-20260924-v1/REVIEW.md`; its 13 host guards pass but it has executed no original instructions. Fresh read-only Windows evidence and the absent-runner renewal plan are under `/Volumes/external/cbus-toolkit-registry-live-review-20260924/windows-readonly-v1/`. These preparations do not close those tasks.

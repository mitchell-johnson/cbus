# Scoped C-Gate `SESSION_ID` differential

This acceptance slice compares nine ordered `SESSION_ID` command cases from
the retained, owned C-Gate 3.4.0.2001 loopback capture with fresh Rust TCP
sessions. It covers three defined functions: own-session query, listing live
external command sessions, and one-shot session tagging. It does not cover
Toolkit GUI behavior, physical C-Bus I/O, TLS, non-loopback peers, ACCESS/LOGIN
variations, persistence, or the rest of C-Gate's command surface.

The original capture is
`research/experiments/2026-09-25/cgate-session-native-acceptance.json`;
`research/functional-obligation-pilot.json` pins its SHA-256 and the public
HELP and contract anchors. The native service was an owned disposable process
without a project or physical CNI. Its vendor JAR hash is retained in the
capture and pilot manifest. The binary and vendor JAR themselves are not
committed.

Run the mock differential after building `cbus-cgate` from the current Rust
source:

```sh
cd rust
cargo build -p cbus-cgate
cd ../toolkit-cli
.venv/bin/python research/cgate_session_differential.py \
  --mock-bin ../rust/target/debug/cgate-mock \
  --output research/runtime/cgate-session-differential-mock.json
```

Run the production `cmqttd --cgate-bind` path through the disposable PCI
simulator and held local broker socket:

```sh
cd rust
cargo build -p cmqttd
cd ../toolkit-cli
PYTHONPATH=src .venv/bin/python research/run_cgate_session_cmqttd_differential.py \
  --cmqttd-bin ../rust/target/debug/cmqttd \
  --output research/runtime/cgate-session-differential-cmqttd.json
```

`make check-session-differential` rebuilds both Rust binaries and requires
both nine-case comparisons to pass. `make check-interop` includes that target
before the broader Python-to-Rust interop suites.

Both runners use ephemeral `127.0.0.1` listeners and two live command
connections. Each required case receives a stable ID, a client-assigned wire
tag and a terminal reply; no case is silently skipped. Missing startup
provision yields a **blocked** receipt and nonzero exit. An interrupted or
malformed tagged reply and other executed behavior differences yield a
**failed** receipt and exit 1, with remaining cases counted as skipped. Only all nine
matching cases yield a **passed** receipt and exit 0.

The comparison maps the two separately observed `cmdN` session IDs to logical
connections `a` and `b`. It validates that each external listing row reports
the corresponding live loopback peer port, a well-formed stable connection
time, the exact tag text and the original continuation or terminal status
separator. It then substitutes only the variable IDs, ports and times. It
checks that every Rust reply echoes its supplied client tag. The original
capture stores tag-stripped response payloads, so the native tag-prefix wire
behavior remains a separate capture gap.

Native `SESSION_ID ALL` additionally lists an internal `cmd1` Console row.
The runner excludes only that exact native row and records each exclusion in
the receipt; any other extra row fails. The external rows retain their
`300-`/`300 ` framing. Full unfiltered ALL parity remains open. The first
pre-fix mock artifact and its red nine-case receipt are retained as
`research/fixtures/cgate-session-differential-pre-fix.json`. A new accepted
receipt must name the exact rebuilt binary SHA-256 and match the source
fingerprint over the C-Gate crate, manifests, lockfile, runner, parity
builder/validator and interaction tests. For `cmqttd`, its source and
manifest are included too.
Source or native-capture changes invalidate a prior receipt; regenerate it
before crediting original-differential acceptance.

The retained pre-fix mock SHA-256 is
`1dbc9c1c041da90993e407c68131c49748dd3435cacd8b6d9dcecfe78c1fb242`:
0 passed, 9 failed, 0 skipped. That red receipt's top-level
`source_revision` names the comparison runner; its separate
`rust_artifact.source_revision` names the pre-fix worktree HEAD, with the
build-provenance limit stated in the receipt. The corrected mock artifact is
`c39a24c27749c627807a82452ba219281d933b053e49034f99bedbeae5290aad`:
9 passed, 0 failed/skipped. Independently, the offline cmqttd artifact is
`50694bcf914b6fdb803ce46e8e7c5758061c6906ae70de47cb0ee2c2eeb0f53f`:
9 passed, 0 failed/skipped. Each sanitized receipt identifies its artifact,
source revision and source-file hashes. These hashes belong to those exact
local builds; a later build needs a new receipt.

The three functional obligations stay `in_progress`. Even a green scoped
original-differential receipt does not resolve their physical applicability,
accept broad C-Gate paths, or complete the Toolkit parity census.

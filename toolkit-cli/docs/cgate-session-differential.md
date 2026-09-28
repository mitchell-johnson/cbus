# Scoped C-Gate `SESSION_ID` differential

This acceptance slice compares nine ordered `SESSION_ID` command cases from
the retained, owned C-Gate 3.4.0.2001 loopback capture with fresh Rust TCP
sessions. It covers three defined functions: own-session query, listing the
internal Console and live external command sessions, and one-shot tagging. It does not cover
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
connections `a` and `b`. It requires the internal `cmd1` Console row in each
listing with a stable, valid connection time. It validates that each external listing row reports
the corresponding live loopback peer port, a well-formed stable connection
time, the exact tag text and the original continuation or terminal status
separator. It then substitutes only the variable IDs, ports and times. It
requires native CRLF line endings and checks that every Rust reply echoes its supplied client tag. The original
capture stores tag-stripped response payloads. The separate
[full-envelope native capture](cgate-tagged-session-native.md) now preserves
the original client prefixes, status separators, CRLF and internal Console
row. This nine-case comparator still uses the earlier payload-only original
capture; the separate eleven-case gate below requires the tagged envelope.

Both Rust servers now include the native `cmd1` Console row. The runner compares
it, including its position and `300-` continuation delimiter; any missing or
extra row fails. The external rows retain their `300-`/`300 ` framing. This is
the complete row set for the captured two-client loopback profile. The first
pre-fix mock artifact and its red nine-case receipt are retained as
`research/fixtures/cgate-session-differential-pre-fix.json`. A new accepted
receipt must name the exact rebuilt binary SHA-256 and match the source
fingerprint over the C-Gate crate and every transitive in-workspace path
dependency's source and manifest. The daemon receipt also includes `cmqttd`
and its MQTT/test-support dependencies. Literal in-workspace Rust `include!`,
`include_str!` and `include_bytes!` assets are hashed, including the retained
DALI help fixture compiled into both servers. The workspace manifest, lockfile,
runner, parity builder/validator and interaction tests are also included.
Changes to these sources or the native capture invalidate a prior receipt; regenerate it
before crediting original-differential acceptance.

The retained pre-fix mock SHA-256 is
`1dbc9c1c041da90993e407c68131c49748dd3435cacd8b6d9dcecfe78c1fb242`:
0 passed, 9 failed, 0 skipped. That red receipt's top-level
`source_revision` names the comparison runner; its separate
`rust_artifact.source_revision` names the pre-fix worktree HEAD, with the
build-provenance limit stated in the receipt. The corrected mock artifact
rebuilt from source commit `7457ef0` is
`509a75a70e3bcfa3aa904f6ec0918c88a6822419b4a6ce85d0d7da036c738360`:
9 passed, 0 failed/skipped. Independently, the offline cmqttd artifact is
`b3bc5ad3ec4297c3ef675a4760af5257c5b528a6280fd121f97c60a26aaa2801`:
9 passed, 0 failed/skipped. Each sanitized receipt identifies its artifact,
source revision and source-file hashes. The hashes above document the previous
external-row-only acceptance and are invalidated by the Console/CRLF source
change. The current v2 [mock receipt](../research/fixtures/cgate-session-differential-fixed.json)
binds artifact SHA-256
`139c220c8b3b6333f53c5e0885b8cfdbd349c18d6796505ecae4b1e595dc3ebd`;
the separate [cmqttd receipt](../research/fixtures/cgate-session-differential-cmqttd.json)
binds `5a3dfc590624605725216bbf697e71e6123c1ba803f3341d6c2ab09c375579d6`.
Both pass 9/9 full-row loopback comparisons with no failed or skipped cases.
Their source fingerprints include the updated comparator and contract pilot.

The three functional obligations stay `in_progress`. Even a green scoped
original-differential receipt does not resolve their physical applicability,
accept broad C-Gate paths, or complete the Toolkit parity census.

The separate [tagged-wire differential](cgate-tagged-session-native.md)
requires all eleven numeric-tag request and response envelopes on both Rust
servers. It preserves the `cmd1` Console row, exact echoed tags on every
continuation and terminal line, CRLF, status and tag-reassignment behavior.
The cmqttd receipt is separately bound into the parity evidence bundle for
the three defined session functions. It adds no fully accepted obligation;
all other required dimensions and profiles remain open.

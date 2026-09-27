# Original tagged SESSION_ID wire capture

The 2026-09-28 capture records eleven ordered commands against an owned
C-Gate 3.4.0.2001 process using two loopback TCP command sessions. It preserves
the full native response envelope in
[`cgate-tagged-session-native.json`](../research/experiments/2026-09-28/cgate-tagged-session-native.json).
The original JAR SHA-256 is
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`.
The receipt also pins the Java executable, private raw capture, private capture
driver and committed owned-process lifecycle helper. Vendor binaries and raw
traces remain outside Git; their hashes bind retained evidence, without
making that private capture independently reproducible from this repository
alone.

Each request used a numeric `[tag] ` prefix and CRLF. Every reply line echoes
that exact prefix, including all continuation rows and the final row of
`SESSION_ID ALL`. The original listing includes internal `cmd1` with
`origin=internal` and `tag=Console`, followed by both external sessions.
Continuation rows use `300-`; the final row uses `300 `. The fixture preserves
these separators and CRLF exactly. Only external session IDs, loopback client
ports and timestamps are normalized to stable role placeholders. Timestamp
equality between roles is not asserted.

The sequence includes each session's own ID, a pre-tagging session listing,
first `TAG native-a` and `TAG native-b` success, listings from both clients,
a rejected second tag (`408 Operation failed: tag name has already been set`),
a subsequent listing retaining both original tags, and missing tag syntax
(`400 Syntax Error: tag name not supplied`).

`tests/test_cgate_tagged_session_native.py` replays all eleven native envelopes
through the Python C-Gate client. Six negative cases remove or change the
client prefix on each of the three ALL rows, including the Console row; each
must reject and disconnect. These tests validate client handling of retained
native evidence. They do not launch the original service or establish Rust
server equivalence.

The process used a fresh empty project directory with no CNI or physical
network configured. All six listeners were verified as owned by the direct
child and bound to loopback. The captured cleanup confirms process exit,
removal of the temporary work directory, reserved-socket closure and log
closure. The capture did not contact house devices.

The [session differential](cgate-session-differential.md) retains its earlier
nine-case payload capture. A separate, mandatory
`make check-tagged-session-differential` compares this full eleven-case tagged
wire capture with fresh `cgate-mock` and offline `cmqttd` TCP sessions.
Its [runner](../research/cgate_tagged_session_differential.py) sends each
literal numeric-tag request, requires that tag on every reply line, then
replaces only the two queried external session IDs, owned loopback peer ports
and stable Console/a/b connection timestamps. It compares every resulting
line byte-for-byte with this fixture, including the internal Console row,
continuation/final separators, statuses, tag reassignment and CRLF. The
committed [mock](../research/fixtures/cgate-tagged-session-differential-cgate-mock.json)
and [cmqttd](../research/fixtures/cgate-tagged-session-differential-cmqttd.json)
receipts bind the native fixture SHA-256, exact Rust binary SHA-256 and the
transitive Rust source closure. CI executes and retains a fresh receipt for
both products. This is additional narrowly scoped evidence; it does not
change the existing functional obligation status or complete the parity census.

The greeting check covers 201/readiness and CRLF, not product-specific text.
Other tag forms, concurrent commands, TLS and non-loopback peers remain
outside this capture's scope; issue #17 remains open.

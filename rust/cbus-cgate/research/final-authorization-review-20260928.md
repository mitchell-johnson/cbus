# Final safe native handler-entry role sweep, 2026-09-28

The owned C-Gate 3.4.0 build 2001 sweep covered all 44 paths that lacked a
native role observation in the 442-path inventory at `4b54565`. It used the
original jar with SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`
and explicit Java 11. The [capture](../../testdata/fixtures/native_cgate_final_authorization_probe.json)
is bound to its [reproducer](native_final_authorization_probe.py), the common
role command reader and the owned `LocalCGate` harness by SHA-256. Every child
owned six IPv4 loopback listeners, had no C-Bus endpoint, and exited before
its disposable work directory was removed. Each invocation had a fresh role
socket; `SHUTDOWN` was never followed by `CONFIRM` on that socket.

Thirty-three paths showed `420 Access denied.` at every lower role and a
non-420 response at the floor or above. Bare family/help entries were
`AIRCON`, `AUDIO`, `CGL`, `CLOCK`, `CONFIG`, `ENABLE`, `EREPORT`, `LIGHTING`,
`MEASUREMENT`, `MEDIATRANSPORT`, `NET`, `NETWORK`, `PORT`, `PROJECT`, `SECURITY`,
`SHORTMESSAGE`, `TELEPHONY`, `TEMPERATURE`, `TEST_SPAM`, `TOPOLOGY`, `TRIGGER`,
`APPLICATIONS`, `CALCULATOR`, `IDENTIFY`, `REPOSITORY`, and `TRANSFORM`.
Executable or session entries were `ACCESS LOAD`, `FILE UPLOAD`, `QUIT`,
`SESSION_ID TAG`, `SHUTDOWN`, `TEST_SPAM EREPORT`, and
`TEST_SPAM LIGHTING`. `ACCESS LOAD` ran in a **separate native child for every
role**, because a native LOAD of a missing filename can replace the active
credential table. Its Clipsal floor returned `200 OK.`; a disposable filename
and generated credentials never left the children. The two `TEST_SPAM` forms
used an absent `MISSING` network, so no generator reached a physical endpoint.
`SHUTDOWN` reached only its `600` confirmation challenge at Admin; no process
shutdown was confirmed. The [vectors](../../testdata/vectors/cgate_final_authorization.jsonl)
retain every exact floor and its immediately lower denied role.

The eleven other paths did **not** show a native handler-entry threshold.
Tagged `#` and `//`, `ACCESS_CONTROL CLOSE/LOCK`, `CONFIRM`, and the cmqttd-only
`CMQTT CAPABILITIES/LABELS` and `UNIT READMEM/IDENTIFY` returned `400` at all
roles. `LOGIN` queried the current role and `LOGOUT` restored the interface
role at all roles. They remain without a native handler-role claim. The four
cmqttd extensions have no original C-Gate handler. Native `QUIT` requires
Connect; cmqttd now applies that gate to its documented `EXIT` alias too.

The Rust registry and source-bound Toolkit contract inventory now record 431
exact handler-entry observations. All 431 `handler_roles` subaxes remain
unresolved for other selectors, object-level checks, successful physical
delivery, and broader session/peer profiles. The 11 unpromoted paths remain
without a native entry observation. Lower-role service tests assert denial
before durable state, event emission, or PCI I/O, including the FILE UPLOAD
document path. This sweep does not establish complete authorization parity
under issue #26.

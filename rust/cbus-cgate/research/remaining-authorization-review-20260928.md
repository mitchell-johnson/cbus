# Remaining native handler authorization, 2026-09-28

This issue #26 slice captures 31 previously unprobed primary or supplement
command paths at all nine native ACCESS levels (279 exact role responses).
The entry floors are Operate for `DBADD`, `DBADDSAFE`, `DBCOPYSAFE`, four
`IDENTIFY` leaves and `LIGHTING STOP`; Admin for `DBCREATENET`, four
`DBGETJSON` selectors, two `DBRENAMENET` forms, two `CONVERTUNIT` leaves and
`PROJECT ARCHIVE`; Program for four `PORT` leaves, `NET CREATE`,
`NET PROJECT_IDENTIFY`, `NETWORK LOCATE`, `TOPOLOGY EXPLORE`,
`TRIGGER INDICATORKILL` and `APPLICATIONS GET_CATALOG`; and Clipsal for
`ACCESS LIST`, `DELETE` and `SAVE`. Every exact invocation returned native
`420 Access denied.` below its floor and a non-420 response at or above it.

The [capture](../../testdata/fixtures/native_cgate_remaining_authorization_probe.json)
is bound to the [reproducer](native_remaining_authorization_probe.py), its
common engine and the owned `LocalCGate` harness by SHA-256 fields. The
original C-Gate 3.4.0.2001 jar hash was
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`.
The child owned six IPv4 loopback listeners, used generated per-role
credentials, configured no C-Bus endpoint, and exited before its temporary
work directory was removed. `PORT CNISCAN` and `CNISCAN2` used explicit
loopback destinations; `PORT PROBE` targeted loopback port 1. All object
targets were absent under `MISSING`, and local ACCESS snapshot writes lived
only in the disposable child.

The Rust gate applies these 31 exact command-path floors before dispatch.
The source-bound Toolkit inventory now records 376 observed path entries and
keeps all 376 handler-role subaxes unresolved for later selector, object and
physical checks. Unit tests verify the nine-role capture and lower-role
denial before repository mutation, event fanout or PCI I/O. The
[vectors](../../testdata/vectors/cgate_remaining_authorization.jsonl) check
six family examples over the real cmqttd TCP listener at the denied and
admitted roles. An admitted non-420 response establishes entry; it does not
claim a successful network operation or byte-for-byte response parity.

The inventory still has 66 paths without a captured entry floor. These
include parent/help forms, cmqttd extensions, native-obsolete commands and
remaining active leaves such as ACCESS ADD/LOAD and selector variants of
probed paths. Native successful-device authorization, object ownership and
broader TLS/admission profiles remain open under issue #26.

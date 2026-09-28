# Native DALI handler and selector authorization, 2026-09-28

This P2.04 slice adds original C-Gate entry-role evidence for 126 previously
unprobed DALI command paths. Together with the two earlier DALI probes, all
128 inventoried DALI paths now have one captured native handler entry floor.
This does not close issue #26 or establish later object/device permission.

The [capture](../../testdata/fixtures/native_cgate_dali_authorization_probe.json)
contains 192 exact invocations at each of nine ACCESS levels (1,728 role
responses). Sixty-six paths were sent in both the default mode and the native
`poll` mode advertised by the retained
[DALI help](../../testdata/fixtures/native_cgate_dali_help.json). Every captured
invocation returned `420 Access denied.` below Program and a non-420 response
at Program or above. The private `DALI GATEWAY PROJECT_CUSTOM` bare form
reached a later syntax error at Program, so it supplies only entry-order
evidence. CDG targets were under an absent `MISSING` project; no physical DALI
or C-Bus operation was attempted.

The [reproducer](native_dali_authorization_probe.py) used the owned
`LocalCGate` harness with original Schneider C-Gate 3.4.0.2001 and an explicit
Java 11 runtime. All six listeners belonged to the direct child and bound
IPv4 loopback. Credentials were generated per run and redacted before the
fixture was retained. The harness confirmed child exit and removal of its
disposable work directory. Source hashes in the fixture bind the capture
script, common engine, harness and help fixture. The original jar SHA-256 is
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`;
the retained capture SHA-256 is
`d2ffb8d86b296ea123b6b667d484e9c5415ec41b0db55c25f14ef6262f67af8f`.

`access.rs` now applies the 126 exact Program floors before DALI dispatch.
The source-bound contract inventory records both captured selector invocations
where present, but leaves `authorization.handler_roles` and functional
acceptance unresolved for each path. Its known entry observations rise from
219 to 345. The service unit test runs all 192 commands below Program and
checks unchanged repository bytes, no event and no PCI frame. The real-daemon
[vectors](../../testdata/vectors/cgate_dali_authorization.jsonl) exercise five
default, `poll`, gateway and session forms over TCP at Admin and Program.
One absent-project DALI 401 response was aligned with the original native
`Object not found` text. The native `DALI GATEWAY LIST` and missing-session
responses differ from the configured cmqttd test backend after admission;
the vector retains both replies so role parity is not mistaken for complete
response parity.

Focused checks for this slice:

```sh
cd rust
CARGO_TARGET_DIR=/private/tmp/cbus-parity-final-20260928/rust/target cargo test -p cbus-cgate dali_handler_and_poll_selector_floors_match_owned_native_responses --lib
CARGO_TARGET_DIR=/private/tmp/cbus-parity-final-20260928/rust/target cargo test -p cbus-cgate dali_native_handler_and_poll_floors_deny_before_dispatch_or_mutation --lib
CARGO_TARGET_DIR=/private/tmp/cbus-parity-final-20260928/rust/target cargo test -p cmqttd --test system_cgate_access dali_native_role_vectors_hold_on_the_real_cgate_listener
cd ../toolkit-cli
PYTHONPATH=src:tests:. /Users/mitchell/source/cbus/toolkit-cli/.venv/bin/python -m pytest -q tests/test_cgate_contract_inventory.py
```

The full workspace suite and hardware acceptance were outside the requested
focused run. Source-bound C-Gate session differential receipts become stale
when `access.rs` or `service.rs` changes; regenerate them after integrating
concurrent slices, then rebuild the parity register. Other native command
families, successful physical-device authorization, object ownership, and
broader TLS identity/admission profiles remain open under issue #26.

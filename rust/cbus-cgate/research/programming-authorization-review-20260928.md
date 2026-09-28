# Programming authorization review, 2026-09-28

This P2.04 slice adds native-evidenced entry authorization for 40 commands:
27 PP leaves at Clipsal, eight PROGRAMMER leaves at Program, and five
DEPLOY_QUEUE leaves at Program. Together with the earlier PP LOCK capture,
every maintained PP leaf requires Clipsal. The dynamically reported
`access_native_handler_probe_levels` now contains 129 paths;
`access_global_command_level_matrix` remains false.

## Independent original evidence

The [capture](../../testdata/fixtures/native_cgate_programming_authorization_probe.json)
records all 40 invocations at all nine native ACCESS roles (360 observations).
The [reproducer](native_programming_authorization_probe.py) starts the original
C-Gate 3.4.0 build 2001 Java server with an owned disposable TEST project,
six loopback listeners and no C-Bus endpoint. Generated login credentials and
vendor catalogue bodies are not retained. The fixture records source and
runtime hashes, listener ownership, process exit and completed cleanup.

Original JAR SHA-256:
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`.

The probe records exact `420 Access denied.` below each observed floor and
non-420 responses at and above it. Missing sessions and units deliberately
bound this evidence to handler entry; these responses do not establish
successful hardware programming or later object-specific permission rules.
All rows share one disposable process, as disclosed in the fixture.

## Implementation and focused checks

Implementation base: `5f8abc461665918ad5253199ed0c58ff7a53b285`.
The new mapping in `src/access.rs` feeds the existing command dispatch guard
and capability response. No transport or TLS implementation was changed.

Checks run from `rust/`:

| Command | Result |
| --- | --- |
| `cargo fmt --check` | Passed |
| `cargo clippy -p cbus-cgate --all-targets -- -D warnings` | Passed |
| `cargo test -p cbus-cgate programming_ --lib` | 9 passed |
| `cargo test -p cbus-cgate handler_floors --lib` | 6 passed |
| `cargo test -p cbus-cgate --test tls` | 8 passed |
| `cargo test -p cmqttd --test system_cgate_access` | 2 passed |
| `cargo clippy -p cmqttd --test system_cgate_access -- -D warnings` | Passed |

The first two test selections overlap. The new tests pin the native fixture
to its reproducer and harness, check all lower roles before dispatch, and
verify unchanged persisted bytes, no events and no PCI output on denial.
A Clipsal owner can create a PP session, log down to Program without losing
it, and regain access through LOGOUT. A separate Clipsal connection cannot
take ownership. Program remains sufficient for creating/deleting an owned
empty programmer. Existing TLS tests cover client-certificate admission
separately from ACCESS-user authorization.

Builds used `CARGO_PROFILE_DEV_DEBUG=0`, `CARGO_PROFILE_TEST_DEBUG=0` and
`CARGO_INCREMENTAL=0` with a shared Cargo target cache; Cargo rebuilt the
affected crates from this branch. The cmqttd ACCESS tests launched the rebuilt
daemon with an ephemeral broker and simulated PCI, verifying the 129-path
capability response and durable ACCESS behavior. Tested daemon SHA-256:
`bd00768bdf9db4e401fa40549fa67b4eccd940b2a9f06805168ac7c272904a25`.
No live Docker deployment was accepted. No full workspace suite was run, following the
user's request for focused checks. Integrated source-bound parity receipts
must be regenerated after combining branches.

## Remaining P2.04 work

This does not close issue #26. Later object-specific authorization,
unprobed native command paths and other certificate/admission profiles
remain outside this slice. Existing cmqttd recovery-token policy remains a
separate, documented gate. No house lights or physical devices were used.

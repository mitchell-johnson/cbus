# Native C-Gate administrative handler entry roles

This bounded P2.04 result expands the retained original C-Gate 3.4.0.2001
authorization matrix by 22 unique command paths. It does not close P2.04.

The [capture script](native_admin_authorization_probe.py) launched the pinned
Schneider C-Gate jar (SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`)
with Temurin 11 under `LocalCGate`. All six listeners belonged to its direct
child and were bound to IPv4 loopback. A disposable `TEST` project and absent
`MISSING` targets prevented physical C-Bus I/O. Each of the nine ACCESS roles
used a fresh command socket and a generated credential. The harness verified
child exit and removal of its owned temporary directory. The committed
[sanitized fixture](../../testdata/fixtures/native_cgate_admin_authorization_probe.json)
contains all 198 role/invocation responses, source hashes and cleanup flags;
it contains no generated credentials, raw logs, site paths or vendor files.

Observed minimum levels at handler entry:

| Role | Newly probed paths |
| --- | --- |
| Operate | `MEASUREMENT DATA` |
| Admin | `CONFIG OBSET`, `CONFIG OBRESET`, `CONFIG LOAD`, `CONFIG SAVE`, `PROJECT CLOSE`, `PROJECT RESTORE` |
| Program | `FILE DELETE`, `FILE DOWNLOAD`, `NET DELETE`, `NET FLUSH`, `NET LEARN`, `NET LOAD`, `NET RENAME`, `NET SAVE`, `NET SYNCNEW`, `NET UNRAVEL`, `NET UNRAVELUNIT`, `LABEL CLEAR`, `LABEL CLEAREDLT`, `LABEL KFIGET`, `LABEL KFISET` |

For every listed invocation, all lower roles received `420 Access denied.` and
the minimum role reached a non-420 parser/handler result. This proves only the
entry floor for that exact invocation. It does not establish later
object-specific permission, successful physical delivery or alternate selector
forms. The Rust `native_minimum_for` registry now enforces these floors before
dispatch. The focused service test verifies lower-role denial with unchanged
durable repository bytes, no event and no PCI frame; three admitted invocations
also reach their later handler stage. The generated Toolkit contract inventory
retains each probe as a source-bound known fact while its `handler_roles`
subaxis remains unresolved. It now records 195 exact role probes overall.

Validation commands from this worktree:

```sh
PYTHONPATH=toolkit-cli/src python3.13 toolkit-cli/research/build_cgate_contract_inventory.py --check
cd rust
cargo fmt --check
CARGO_TARGET_DIR=/private/tmp/cbus-parity-final-20260928/rust/target cargo clippy --workspace --all-targets -- -D warnings
CARGO_TARGET_DIR=/private/tmp/cbus-parity-final-20260928/rust/target cargo build --release --workspace
CARGO_TARGET_DIR=/private/tmp/cbus-parity-final-20260928/rust/target cargo test -p cbus-cgate admin_handler_floors_match_owned_native_role_responses --lib
CARGO_TARGET_DIR=/private/tmp/cbus-parity-final-20260928/rust/target cargo test -p cbus-cgate admin_native_handler_floors_deny_before_dispatch_or_mutation --lib
CARGO_TARGET_DIR=/private/tmp/cbus-parity-final-20260928/rust/target cargo test -p cmqttd --test system_cgate_access access_family_is_redacted_sandboxed_durable_and_connection_safe
cd ../toolkit-cli
PYTHONPATH=src:tests:. /Users/mitchell/source/cbus/toolkit-cli/.venv/bin/python -m pytest -q tests/test_cgate_contract_inventory.py::test_native_handler_role_expansion_is_source_bound_and_stays_partial tests/test_cgate_contract_inventory.py::test_native_admin_role_probe_weakening_cannot_rebuild
```

All listed checks passed. The full local Rust test suite, original-TLS
identity matrix, and physical C-Bus acceptance were not
run for this bounded slice. Changing the access registry invalidates
source-bound C-Gate differential receipts; refresh those receipts and regenerate
the parity register after integration with concurrent source changes.

P2.04 still needs the unprobed native handlers and selector variants, exact
object-specific authorization and concurrent/reconnect/persisted-admission
comparisons across both servers. The native TLS certificate probe currently
supports certificate admission independent of ACCESS/LOGIN for one profile;
broader native TLS configurations and identity mapping remain unproven.

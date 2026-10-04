# Installed-wheel interoperability with the Rust services

The automatic `Toolkit installed wheel and Rust interoperability` CI job runs
the maintained Python-to-Rust selections against both `cgate-mock` and
`cmqttd` using a newly built, noneditable Python 3.13 wheel. The existing
source and offline-wheel jobs remain separate. This implements the installed
interop portion of [issue 121](https://github.com/mitchell-johnson/cbus/issues/121).
Provisioned native and physical release gates remain under
[issue 22](https://github.com/mitchell-johnson/cbus/issues/22).

The complete default declaration contains 1007 explicit selectors: 498 for
the mock and 509 for the daemon. This includes the preserved 985 quoted
selectors, 16 Application-order selectors and six additional unquoted daemon
guards. One mock and six daemon
whole-module selections expand into additional collected cases. These numbers
describe the declaration, not a claim that a focused local run executed it.

## Run the complete installed selection

Supply both existing executable paths and a new artifact directory outside
the source checkout. The target does not build Rust; CI has a preceding
`make build-interop` step.

```sh
cd toolkit-cli
make check-wheel-interop WHEEL_PY=python3.13 \
  CGATE_MOCK_BIN=/absolute/path/cgate-mock \
  CMQTTD_BIN=/absolute/path/cmqttd \
  WHEEL_INTEROP_OUTPUT=/absolute/path/new-wheel-interop-artifacts
```

The runner creates its own build and install environments and installs all six
extras: `test,research,serial,usb,firmware,network`. It does not require pip in
the calling environment. It clears inherited C-Bus provisioning and
endpoint settings, then supplies the two selected binaries to the tests.
Tests own their synthetic projects, loopback services and PCI/broker peers.
This does not use the house network or start an original Toolkit/native server.

## Run a focused selection

Use repeated `--select` arguments containing exact tokens from either
maintained Make declaration. Unknown, duplicate and empty selections fail.
Do not substitute `-k` expressions or call a focused result a full default pass.

```sh
python3.13 research/installed_rust_interop.py \
  --mock-bin /absolute/path/cgate-mock \
  --cmqttd-bin /absolute/path/cmqttd \
  --output /absolute/path/new-focused-artifacts \
  --select 'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_chained_saves[pc_tsa-mock]' \
  --select 'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_chained_saves[pc_tsa-daemon]'
```

`--timeout` bounds each backend's run. A focused selection may name one
backend, but both executable arguments remain required and are pinned.

## Read the evidence

The result separates full declaration scope from the issued selection and
actual collected, started and completed identities. JUnit cases and the
pytest execution trace must agree. All explicit selected identities require
passing bodies; every selected module needs a passing body. Whole-module
collection and execution must match. Missing binaries, dropped identities,
deselection, unexpected skips and malformed evidence fail the gate.

Two whole-module cases may report missing private unit specifications:

- `RustInteropTests::test_edlt_lighting_programming_round_trip` in
  `tests/test_rust_cgate_interop.py`.
- `test_protection_matrix_matches_a_fresh_derivation` in
  `tests/test_cmqtt_programming_methods_interop.py`.

Their exact source/census conditions and reasons are checked. A skip never
satisfies a required explicit identity. Report their skips separately from
passing parent cases and unitemized unittest subtest events.

The package checks compare source, build snapshot, wheel archive and installed
files, validate the installed distribution RECORD and pin both binaries.
The fresh environment has an owned import guard that observes the pytest
process and launched Python CLI processes independently of child PYTHONPATH.
Expected launches must have matching process records; bypassing the guard
cannot silently remove a child from the audit. The guard compiles checked product source directly and rejects product
bytecode caches. Ordinary ignored source `__pycache__` `.pyc`/`.pyo` files are
excluded from the original checkout comparison and are never copied into the
reference or build tree. Symlinked caches and non-bytecode cache entries still
fail, as do any product caches in the wheel, installed package or import path.
Source fallback, package substitution, unsafe package entries
and unreaped owned children fail. This observes recognized direct Python and
console launches and product source-loader imports; it is not universal
attestation of arbitrary native descendants or adversarial executed code.

Inspect the retained summary, JUnit, trace, origin and launch records after
both success and failure. CI uploads the runner artifact directory with an
`always()` step. These are owned-service interoperability results. They do
not establish original GUI behavior, Schneider-native semantics, physical
effects or full Toolkit parity. `coverage --require-complete` remains the
separate enforcing compatibility decision.

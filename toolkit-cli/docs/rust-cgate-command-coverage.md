# Rust C-Gate command coverage

The Rust `cbus-cgate` crate has complete command-name coverage for the supplied
C-Gate 3.4 build. Its inventory combines two independent sources:

- all **224** headings in section 4.5 of the 2024 C-Gate 3.4 manual; and
- all **268** subcommand registrations recovered from the supplied C-Gate
  bytecode, including private Toolkit families such as `PP`, `DALI`, `FILE`,
  `PROGRAMMER`, `DEPLOY_QUEUE`, `EVENT_CHANNEL`, `TRANSFORM`, `ACCESS`, and
  `REPOSITORY`.

The sources overlap in 61 places and define **431 unique command paths**. The
manual PDF has SHA-256
`812f84b0206b8714e6780b80ea5dfe6347357530aa899f6aecc0f7da8f44c97b`; the
audited C-Gate jar has SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`.
The executable inventory is in `rust/cbus-cgate/src/manual.rs`. Tests fail if
the public count, bytecode-registration count, uniqueness, or dispatcher
coverage changes.

Core Toolkit operations have dedicated native-shaped implementations:
project and repository lifecycle, database safe and unsafe verbs, CGL,
network lifecycle and discovery, object reads and writes, XML and JSON
envelopes, calculator, event subscriptions, application levels, labels,
triggers, enables, named scenes, unit conversion, and PP locks/sessions,
catalogue reads and raw data. Patch execution remains an explicit failure.
Legacy `GET`, `SHOW`, `DO`, `ON`, `OFF`,
`RAMP`, `TERMINATERAMP`, `REPORT`, `NEW`, `OID`, and macro `RUN` spellings are
also implemented.

The remaining application and private families use a declarative stateful
model. They validate the registered command and argument shape, retain state,
emit events, and implement list/delete/session behavior. This includes every
air-conditioning, audio, clock, media transport, measurement, security,
short-message, telephony, temperature, DALI, deploy-queue, programmer and event
channel registration. The private `FILE` family uses a bounded in-memory file
store with real SHA-256; database save/load and named scenes also round-trip
in memory.

This is complete command support for the Rust **in-memory C-Gate model**. It is
not a claim that a hardware-free process performed physical C-Bus operations.
Commands that inherently require serial/CNI hardware—DALI discovery and
commissioning, port probes, topology exploration, live application telegrams,
physical clock traffic and network learning—produce deterministic modeled
state and native-shaped responses without claiming a bus-side effect. Server
files, access entries, database snapshots and shutdown confirmation are also
process-local; `SHUTDOWN` confirms the modeled operation but deliberately does
not kill the test server. The separate Rust service embedded in `cmqttd`
implements the physical subset in the
[cmqttd replacement ledger](../../docs/cmqttd-cgate.md); commands outside that
ledger still require native C-Gate or further implementation when physical
effects are the acceptance criterion.

The embedded cmqttd service implements all five maintained ACCESS paths plus
native-shaped LOGIN/LOGOUT session levels. Active rows and LOAD/SAVE snapshots
are durable local state and perform no PCI I/O. Its security boundary is
intentionally safer than the vendor daemon: credentials are digest-only and
LIST-redacted, snapshot names cannot traverse the host filesystem, a missing
LOAD cannot replace the active policy, and unresolved address rows never enter
the list or poison later connections. Fresh/pre-ACCESS state remains reachable
through Docker/NAT until address admission is explicitly changed; unmatched
peers can still present a configured recovery token without gaining access to
other commands first. These differences are pinned in
`native_cgate_access.json` and the real-daemon `system_cgate_access.rs` test.

The embedded cmqttd service also implements thirteen previously fail-closed PP
administrative/catalogue/session-memory paths and seven PROGRAMMER queue
metadata paths as bounded local operations. Catalogue and LOAD_FROM_FILE access
is confined to `--cgate-unitspec`; raw memory belongs to an owned staged
session; PROGRAMMER queues are runtime-only. `PROGRAMMER TRIGGER ... START`
and `PP WRITE_PATCH` remain 502 because they require physical execution
backends, while PATCH_VERSION reproduces the native missing-patchset 408. This
substantially reduced the aggregate executable 431-path gap. Retained
evidence is in `rust/testdata/fixtures/native_cgate_pp_programmer.json`, with
real-daemon coverage in `system_cgate_pp_programmer.rs`.

The embedded service now also has a dedicated implementation for all five
`DEPLOY_QUEUE` paths. LIST, terminal DELETE and typed DELETE_ALL are local
volatile administration. ADD completes only an empty or fully cancelled
PROGRAMMER as a no-work STOPPED task; any executable instruction returns 502
before mutation. RETRY remains an explicit 502 because native retry
reinitializes and executes the task group. Implemented transitions publish the
retained `updated-entries`, `started`, and `ended` envelopes only to sessions
subscribed through EVENT_CHANNEL; `debug` is silent without a real worker.
Exact sanitized evidence is in
`rust/testdata/fixtures/native_cgate_deploy_queue.json`; the real-daemon test
also verifies zero queue PCI traffic, restart volatility and MQTT continuity.

Fourteen family roots now reproduce the exact retained C-Gate 3.4 help
envelopes for bare, literal `?`, and `HELP` forms. Nine of those roots are in
the 431-path inventory (`CGL`, `CLOCK`, `ENABLE`, `EREPORT`, `LIGHTING`,
`SHORTMESSAGE`, `TEMPERATURE`, `TEST_SPAM`, and `TRIGGER`). The other five
parent roots are pinned in the separate supplement. These local help endpoints
do not change any child command's capability class. Together with the NET and
deploy-queue tranches, the matrix now contains **208 physical, 159
local/session, 62 fail-closed, and 2 obsolete paths**. Evidence is in
`rust/testdata/fixtures/native_cgate_family_help.json`.

Current verification is:

- Rust unit, server-integration, TCP, and system tests for the modeled and
  hardware-backed paths;
- exhaustive dispatch checks for all 224 manual headings and all 268
  bytecode registrations;
- stateful tests for application/config/clock/lock commands, legacy lighting,
  named scenes, database snapshots, hidden files/SHA-256, deploy queues and
  DALI registration families;
- Python interoperability tests using the production `CGateClient` and typed
  Toolkit wrappers against freshly built Rust services; and
- warning-free `cargo clippy -p cbus-cgate --all-targets -- -D warnings` plus
  `rustfmt --check`.

The command inventory test proves that a documented or registered command can
never fall through to `400 Unknown command`. Dedicated behavior tests and the
Python suite verify the stateful paths used by this repository. Hardware
acceptance remains separate because an in-memory model cannot prove a physical
device changed state.

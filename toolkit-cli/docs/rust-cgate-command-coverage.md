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
catalogue reads, raw data and patches. Legacy `GET`, `SHOW`, `DO`, `ON`, `OFF`,
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
not kill the test server. Use the vendor service or a future Rust physical
backend when physical effects are the acceptance criterion.

Current verification is:

- **58 Rust tests**: 42 library, 9 server integration and 7 TCP integration;
- exhaustive dispatch checks for all 224 manual headings and all 268
  bytecode registrations;
- stateful tests for application/config/clock/lock commands, legacy lighting,
  named scenes, database snapshots, hidden files/SHA-256, deploy queues and
  DALI registration families;
- **13 Python interoperability tests** using the production `CGateClient` and
  typed Toolkit wrappers against a freshly built `cgate-mock`; and
- warning-free `cargo clippy -p cbus-cgate --all-targets -- -D warnings` plus
  `rustfmt --check`.

The command inventory test proves that a documented or registered command can
never fall through to `400 Unknown command`. Dedicated behavior tests and the
Python suite verify the stateful paths used by this repository. Hardware
acceptance remains separate because an in-memory model cannot prove a physical
device changed state.

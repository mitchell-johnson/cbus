# Implementation status

## Maintained scope

The maintained applications are the Python Toolkit CLI in `toolkit-cli/` and the Rust workspace in `rust/`. The older Python MQTT/protocol implementation, migration harness, and standalone ESP32 firmware are retired.

## Toolkit CLI

`cbus-toolkit` targets Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001. It provides offline XML/CBZ project editing, C-Gate and PCI clients, native project and unit workflows, commissioning, scenes, and supported keypad, sensor, and eDLT configuration. It also includes JSON output, compatibility evidence, and a feature ledger.

Full Toolkit parity remains unfinished. The ledger records 38 feature areas: 17 implemented, 19 in progress, and 2 pending. See [Toolkit implementation status](../toolkit-cli/docs/implementation-status.md) for per-feature behavior and limits. `cbus-toolkit coverage --require-complete` reports the current machine-readable status and returns nonzero while completion requirements remain unmet.

## Rust functionality

| Area | State | Notes |
| --- | --- | --- |
| C-Bus wire codec | Complete for the supported packet families | Checksums, PM, PP, DM, CAL, SAL, reset, confirmation, error, status reports, JSON conversion, strict and lenient decoding |
| SAL applications | Implemented | Lighting, clock, enable control, temperature broadcast, and status request |
| PCI/CNI transport | Implemented | TCP and serial endpoints, framing, initialization, confirmations, retries, reconnection, and adaptive flow control |
| CNI interface discovery | Implemented for the captured IPv4 UDP profile | Exact query and strict CNI2/Wiser reply codec, bounded collection, hidden-product policy, malformed evidence, deterministic JSON in `cbus-tools`; discovery does not prove absence, reachability or physical-network identity |
| MQTT bridge | Implemented | Light commands and state, Home Assistant discovery, binary sensors, time synchronization, status resync, TLS, authentication, and project labels |
| Project backups | Implemented | One-file `.cbz` archives and bare project XML; network selection; application, group, unit, and channel metadata export |
| Unit interrogation | Implemented | Unit discovery and CAL identify/recall queries over a TCP CNI |
| Selected-serial plan verify/apply | Implemented for the strict two-known-serial source-255 scope | Read-only classification plus fresh-before/option-66 gated one-shot apply on one shared PCI connection, durable exclusive recovery journal, no automatic address-command replay within an attempt, and independent post-send verify. The canonical fingerprint is process-local; cross-process safety depends on preserving one stable exclusive journal path, and different paths are not globally deduplicated. Confirmed read probes may retry. Scripted loopback evidence does not establish hardware compatibility, movement cause, or persistence |
| PCI simulator | Implemented as a development test double | Connection startup, local echo, interface options, confirmations, selected SAL handling, and status responses |
| C-Gate command surface | Complete inventory coverage | 224 public manual headings plus 268 registered command paths, 431 unique paths |
| C-Gate core state | Stateful | Project, database, network, unit, level, event, lock, session, and programming-session workflows |
| C-Gate specialist families | Deterministic model | All registered commands dispatch; specialist or hardware-facing operations return stable in-memory results rather than controlling physical equipment |
| Embedded physical C-Gate | In progress | Persistent database plus real lighting, native `DBNETWORKPATH`, shared-interface `PROJECT_IDENTIFY`, direct and one-to-six-bridge read-only `PINGU`/`SYNC`/`CHECKUNIT`, general `SYNCNEW`, and `DO ... SYNC`, physical network-clock inspection/configuration/recovery, persistent named-scene record/playback, Trigger, Enable, clock, Temperature Broadcast, dynamic labels, eDLT/KFI controls, direct targeted `SYNCNEW`, verified `SET_PROJECT_IDENTIFY`, guarded readdressing and bounded `UNRAVELUNIT MATCHDB`, unit identity, physical PP LOAD/SAVE with native C-Bus 3 NVM commit, and memory backends over cmqttd's shared CNI connection |
| Test infrastructure | Implemented | Compatibility vectors, generated per-vector tests, property tests, in-process MQTT broker, scripted PCI, full-system tests, formatting and lint gates |
| Container image | Implemented | Builds and ships `cmqttd`, `cbus-tools`, `cbus-simulator`, and `cgate-mock` |

## Current limits and outstanding work

- `cgate-mock` is an in-memory compatibility server. The separate C-Gate service embedded in `cmqttd` persists its database and implements the physical operations listed in [its replacement ledger](cmqttd-cgate.md); other physical commands fail explicitly.
- Complete command dispatch means every inventory path has a response model. It does not mean every specialist command reproduces every device-specific side effect of native C-Gate.
- The PCI simulator models the protocol behavior needed by the workspace and test suite. It is not a complete electrical or timing simulation of every C-Bus unit.
- Real-site validation remains necessary for unusual topologies, serial adapters, broker policies, and device families not represented by the committed fixtures.
- Unit specifications must be supplied to `cgate-mock --unitspec DIR` when tests require catalogue-backed programming parameters. The repository does not distribute vendor catalogue files.

Toolkit workflow parity and Rust C-Gate command coverage are separate measures. A mock handler or passing simulator test alone does not establish compatibility with every Toolkit workflow or physical unit.

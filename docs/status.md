# Implementation status

## Maintained scope

All maintained source code is in the Rust workspace. The earlier language implementation, Toolkit reimplementation, reverse-engineering artifacts, migration scripts, and standalone ESP32 firmware have been removed from the active repository.

## Completed functionality

| Area | State | Notes |
| --- | --- | --- |
| C-Bus wire codec | Complete for the supported packet families | Checksums, PM, PP, DM, CAL, SAL, reset, confirmation, error, status reports, JSON conversion, strict and lenient decoding |
| SAL applications | Implemented | Lighting, clock, enable control, temperature broadcast, and status request |
| PCI/CNI transport | Implemented | TCP and serial endpoints, framing, initialization, confirmations, retries, reconnection, and adaptive flow control |
| MQTT bridge | Implemented | Light commands and state, Home Assistant discovery, binary sensors, time synchronization, status resync, TLS, authentication, and project labels |
| Project backups | Implemented | One-file `.cbz` archives and bare project XML; network selection; application, group, unit, and channel metadata export |
| Unit interrogation | Implemented | Unit discovery and CAL identify/recall queries over a TCP CNI |
| PCI simulator | Implemented as a development test double | Connection startup, local echo, interface options, confirmations, selected SAL handling, and status responses |
| C-Gate command surface | Complete inventory coverage | 224 public manual headings plus 268 registered command paths, 431 unique paths |
| C-Gate core state | Stateful | Project, database, network, unit, level, event, lock, session, and programming-session workflows |
| C-Gate specialist families | Deterministic model | All registered commands dispatch; specialist or hardware-facing operations return stable in-memory results rather than controlling physical equipment |
| Test infrastructure | Implemented | Compatibility vectors, generated per-vector tests, property tests, in-process MQTT broker, scripted PCI, full-system tests, formatting and lint gates |
| Container image | Implemented | Builds and ships `cmqttd`, `cbus-tools`, `cbus-simulator`, and `cgate-mock` |

## Current limits and outstanding work

- The C-Gate server is an in-memory compatibility server. It does not embed or launch Schneider C-Gate, persist its model across restarts, or provide physical network access.
- Complete command dispatch means every inventory path has a response model. It does not mean every specialist command reproduces every device-specific side effect of native C-Gate.
- The PCI simulator models the protocol behavior needed by the workspace and test suite. It is not a complete electrical or timing simulation of every C-Bus unit.
- Real-site validation remains necessary for unusual topologies, serial adapters, broker policies, and device families not represented by the committed fixtures.
- Unit specifications must be supplied to `cgate-mock --unitspec DIR` when tests require catalogue-backed programming parameters. The repository does not distribute vendor catalogue files.

The supported product boundary is the Rust workspace described here. The removed Toolkit replacement is not an outstanding component of this repository.

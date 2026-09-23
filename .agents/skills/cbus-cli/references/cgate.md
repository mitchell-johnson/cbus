# C-Gate and Toolkit compatibility reference

The user-facing CLI is Python `cbus-toolkit cgate`; see [toolkit.md](toolkit.md) for installation, typed workflows, and JSON output. This reference describes its Rust test server. Connect the CLI with `--host 127.0.0.1 --port 20033` for the default mock listener; native plain TCP defaults to 20023.

## What is supported

The maintained registry combines 224 public headings from C-Gate manual section 4.5 with 268 registered bytecode command paths, producing 431 unique paths after overlap removal. Tests assert inventory sizes, uniqueness, help visibility, parser reachability, and dispatch reachability. Unknown commands return an error.

Core project, database, network, unit, group-level, label, lock, session, event, repository, and PP programming flows use shared in-memory state. Specialist application and hardware-facing commands have deterministic handlers so a client can exercise every registered path without Schneider services or physical equipment.

The Rust mock supports CLI clients and C-Gate command traffic. It does not provide persistent project storage, physical C-Bus access, firmware transfer, real port discovery, or exact device timing and side effects. The Python Toolkit CLI has its own native-server and physical-device workflows with separate limits and acceptance evidence. Full Toolkit parity remains unfinished.

## Start and connect

```sh
rust/target/release/cgate-mock --bind 127.0.0.1:0
```

Read the printed address, then connect with a line-oriented TCP client. For a fixed development port:

```sh
nc 127.0.0.1 20033
```

Commands may be untagged or tagged. A tag is written before the command:

```text
APIVER
[1] PROJECT LIST
[2] EVENT ON
```

Tagged replies retain the client tag. Multiline replies use a hyphen after the status/tag prefix for continuation lines and a space for the final line. Events may appear before a command's final response and can arrive asynchronously on subscribed clients, so clients must parse reply framing rather than assume one input line produces one output line.

## Addresses and stateful examples

C-Gate addresses use forms such as `//PROJECT/NETWORK/APPLICATION/GROUP`. The tests use examples like:

```text
[1] PROJECT LIST
[2] PROJECT USE TEST
[3] LIGHTING ON //TEST/254/56/1
[4] LIGHTING RAMP //TEST/254/56/1 128 20
[5] LIGHTING OFF //TEST/254/56/1
```

These commands require suitable model state; a fresh mock may return a not-found response for an address that has not been created. Use `HELP` and the repository command inventory for discovery, and construct a project/network/application/group before testing level changes.

Programming sessions are lock-gated:

```text
[10] PP LOCK L //TEST/254
[11] PP START S L
[12] PP NEW S KEY1 1.2.67
[13] PP SET S Example value
[14] PP GET S *
[15] PP END S
[16] PP UNLOCK L
```

Run with `--deny-programming` when testing access denial. Supply `--unitspec DIR` when catalogue-backed parameter schemas are required. Without vendor specifications, the model still supports the spec-free programming behavior allowed by the command.

## Sessions and events

The server model is shared across TCP connections. Each connection keeps its own selected project and event mode. `EVENT ON`, `EVENT OFF`, or a detailed `e[+0-9]s[01]c[01]` mode controls delivery. Subscribed clients receive cross-client events; the originating client receives eligible command events in order before its reply.

## Resource bounds

- Input line: 1 MiB maximum.
- Here-document body: 16 MiB maximum.
- Library event queue: 4,096 entries by default, with an overflow marker.
- TCP fanout: unbounded channels; a subscribed client that never reads can consume growing memory while writers continue.
- Unit-spec file: 8 MiB maximum; include traversal is capped at 128 files and checked for directory containment.

Use loopback and an ephemeral port in automated work. Stop the child process after the check. Do not expose the mock listener beyond the intended test environment.

# C-Bus Toolkit CLI and Rust tools

Manage Clipsal/Schneider C-Bus projects from the terminal and connect C-Bus lighting to MQTT and Home Assistant.

This repository has two main applications:

- **[`cbus-toolkit`](toolkit-cli/README.md)** — a Python CLI for Toolkit-style project editing, commissioning, unit configuration, scenes, and diagnostics. It works with project files offline and connects to C-Gate or a CNI for online operations. JSON output makes it usable from scripts and AI agents.
- **[`cmqttd`](docs/configuration.md)** — a Rust daemon providing MQTT/Home Assistant support and an embedded C-Gate service over one shared C-Bus connection. It runs without Schneider C-Gate, Windows, or the Toolkit application. Its [C-Gate replacement status](docs/cmqttd-cgate.md) distinguishes implemented hardware operations from outstanding compatibility work.

The Rust workspace also provides protocol tools, a PCI simulator, and a C-Gate compatibility server for development and testing. Install the application you need; the Python CLI and Rust bridge can be used independently.

## Which program do I need?

| I want to… | Use |
| --- | --- |
| Create, inspect, edit, validate, or export Toolkit XML/CBZ projects | `cbus-toolkit project` |
| Manage native C-Gate projects, configure supported units, control groups, or commission a network | `cbus-toolkit cgate` |
| Plan supported keypad, sensor, eDLT, scene, or unit-conversion settings offline | `cbus-toolkit keys`, `sensors`, `edlt`, `scene`, and `unit-conversion` |
| Query a CNI directly or inspect routed PCI messages | `cbus-toolkit pci` and `pci-route` |
| Connect C-Bus lights to MQTT and Home Assistant | `cmqttd` |
| Read live eDLT labels without Windows, while MQTT keeps running | `cbus-toolkit cgate edlt-labels`, connected to `cmqttd` |
| Decode a frame, export project labels, or interrogate a unit | `cbus-tools` |
| Test a C-Gate client without a vendor server or hardware | `cgate-mock` |
| Test PCI/CNI protocol traffic without hardware | `cbus-simulator` |

## Toolkit CLI

### Install

Requires **Python 3.13 or newer**. From the repository root, on macOS or Linux:

```sh
python3.13 -m venv toolkit-cli/.venv
toolkit-cli/.venv/bin/python -m pip install -e ./toolkit-cli
source toolkit-cli/.venv/bin/activate
cbus-toolkit --help
```

On Windows, use `py -3.13 -m venv toolkit-cli/.venv`, then run `toolkit-cli\.venv\Scripts\python.exe -m pip install -e ./toolkit-cli` and `toolkit-cli\.venv\Scripts\cbus-toolkit.exe --help`.

The base package has no external Python dependencies. Optional serial and USB features have separate extras; see the [Toolkit CLI guide](toolkit-cli/README.md).

### Try it without hardware

Create a project, add a network and lighting group, then inspect it:

```sh
cbus-toolkit project new demo.cbz --name DEMO
cbus-toolkit project add demo.cbz --kind network --address 254 --name Local
cbus-toolkit project add demo.cbz --kind application --parent /254 --address 56 --name Lighting
cbus-toolkit project add demo.cbz --kind group --parent /254/56 --address 1 --name Lounge
cbus-toolkit project inspect demo.cbz
cbus-toolkit project export demo.cbz demo.xml --format xml
```

Project editing preserves unknown XML and opaque programming fields. Use `--output` on an edit to write a separate copy. Native C-Gate 3 SQLite projects are managed through `cbus-toolkit cgate project` instead of the offline XML/CBZ editor.

### Connect to C-Gate

Point the CLI at your C-Gate server. This example reads the project list:

```sh
cbus-toolkit cgate --host 192.168.1.20 --port 20023 project list
```

Replace the example address and port with your server's values. Use `cbus-toolkit cgate --help` for project, network, database, unit, addressing, scene, and control commands. The transport supports verified TLS and client certificates. Advanced parameter workflows may require vendor unit specifications; those files are supplied separately.

For an exact C-Gate command, use `cbus-toolkit cgate exec 'PROJECT LIST'`. For a file of commands that must share one session, use `cbus-toolkit cgate run commands.txt`. Add the same connection options as above; command batches stop at the first failure.

Results are JSON on stdout; operation errors are JSON on stderr and return a nonzero exit status. Put `--compact` before the command for single-line JSON. Event monitoring emits JSON lines.

### Toolkit compatibility and current status

The CLI targets **C-Bus Toolkit 1.18.0.2754 and C-Gate 3.4.0.2001**, with full Toolkit functionality as the goal. Implemented workflows include offline project editing, native project management, supported unit programming and addressing, keypad presets, scenes, CGL exchange, and substantial eDLT configuration. Device and firmware support is documented per workflow.

**Full Toolkit parity is not complete.** The feature ledger currently records 38 areas: 17 implemented, 19 in progress, and 2 pending. These categories are not a percentage of Toolkit functionality. Check the current machine-readable status with:

```sh
cbus-toolkit coverage --require-complete
```

This intentionally returns exit status `1` while parity remains unfinished. The [completed functions and outstanding work](toolkit-cli/docs/implementation-status.md) describe supported profiles, test evidence, and remaining work. The [Toolkit CLI guide](toolkit-cli/README.md) contains detailed command examples.

## MQTT and Home Assistant bridge

Build the Rust tools with a current stable Rust toolchain, from the repository root:

```sh
cargo build --manifest-path rust/Cargo.toml --release --workspace
```

The binaries are written to `rust/target/release/`. Run the bridge against your MQTT broker and CNI, replacing these example addresses:

```sh
rust/target/release/cmqttd \
  --broker-address 192.168.1.20 \
  --broker-disable-tls \
  --tcp 192.168.1.10:10001
```

`cmqttd` publishes Home Assistant discovery and lighting state, and forwards MQTT light commands to C-Bus. Add `--project-file house.cbz` for names from your Toolkit project and `--cbus-network 'Main Network'` to select a network. TLS is enabled by default; omit `--broker-disable-tls` when using a TLS broker. Serial and ESP32 bridge connections are also supported.

For Docker, copy `.env.example` to `.env`, configure your broker and C-Bus endpoint, then run `docker compose up --build`. See [bridge configuration](docs/configuration.md) for authentication, certificates, project files, time synchronization, and status updates.

### Use cmqttd as the CLI's server

Enable `--cgate-bind 127.0.0.1:20023` together with `--project-file house.cbz`. The daemon imports your project into a persistent database and serves the Toolkit CLI while continuing MQTT on the same PCI/CNI connection. Docker Compose enables this listener and stores the database in the `cmqttd_data` volume.

```sh
cbus-toolkit cgate --host 127.0.0.1 project list
cbus-toolkit cgate --host 127.0.0.1 exec 'CMQTT CAPABILITIES'
cbus-toolkit cgate --host 127.0.0.1 edlt-labels //PROJECT/254/p/5
```

Replace the project/network/unit with your actual address. Live eDLT label reads verify the device identity, stable configuration header, and static-text CRC; results include the 64 stored strings and widget/scene labels. Dynamic label caches are reported as unread.

**Full C-Gate replacement is the target, not the current completion claim.** Hardware-backed lighting, Trigger Control, Enable Control, clock and Temperature Broadcast commands, complete-coverage `NET PINGU`, identity-populating `NET SYNC`, duplicate-aware `NET CHECKUNIT`, unit identity, schema-driven physical `PP LOAD`, extended-memory reads, live observations, and persistent database operations are implemented while MQTT continues on the same CNI connection. Physical `PP LOAD` requires privately installed decoded unit specifications; `PP SAVE` and other remaining hardware workflows return explicit errors instead of simulated success. See the [supported operations and remaining work](docs/cmqttd-cgate.md).

## Development tools and simulation

`cbus-tools` provides small inspection commands:

```sh
rust/target/release/cbus-tools decode 05013800790148
rust/target/release/cbus-tools dump-labels --pretty 2 rust/testdata/fixtures/project.xml
```

To exercise the Toolkit CLI against the Rust C-Gate model, start the server in one terminal:

```sh
rust/target/release/cgate-mock --bind 127.0.0.1:20033
```

Then, with the Python environment activated, use another terminal:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 project new DEMO
cbus-toolkit cgate --host 127.0.0.1 --port 20033 project list
```

`cgate-mock` implements all **431 unique command paths** in the maintained C-Gate inventory. It supports shared project state, per-client project selection, tagged replies, events, and programming sessions. This is complete command coverage in an in-memory test server; it does not establish full Toolkit workflow parity or physical-device behavior. State is lost when the server stops. See [C-Gate compatibility](docs/cgate.md).

For a PCI/CNI test endpoint, run `rust/target/release/cbus-simulator 127.0.0.1 10001`. This is a separate protocol from C-Gate: point PCI clients at the simulator and C-Gate clients at `cgate-mock`.

## Documentation and AI agents

- [Toolkit CLI guide](toolkit-cli/README.md) and [feature status](toolkit-cli/docs/implementation-status.md)
- [Architecture](docs/architecture.md), [command reference](docs/commands.md), and [protocols](docs/protocol.md)
- [MQTT bridge configuration](docs/configuration.md) and [C-Gate compatibility](docs/cgate.md)
- [Testing and development](docs/testing.md)
- [AI skill](.agents/skills/cbus-cli/SKILL.md) with command, system, and workflow references; [repository agent guidance](AGENTS.md)

## Repository layout

```text
toolkit-cli/             Python cbus-toolkit application, tests, and feature docs
rust/                    Rust MQTT bridge, protocol libraries, and supporting tools
rust/testdata/           committed protocol vectors and system-test fixtures
docs/                    shared architecture, configuration, and development docs
.agents/skills/cbus-cli/ AI skill and operational references
cmqttd_config/           optional local Docker configuration
```

## License

GNU Lesser General Public License v3.0 or later. See [COPYING](COPYING) and [COPYING.LESSER](COPYING.LESSER).

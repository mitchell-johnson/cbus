# libcbus

Talks to Clipsal C-Bus from Rust — plus an ESP32 firmware option.

Copyright 2012-2020 Michael Farrell, 2024-2026 Mitchell Johnson.
Licensed under the GNU LGPL3+. See `COPYING` and `COPYING.LESSER`.

> **Note:** This software is not certified or endorsed by Clipsal or Schneider
> Electric. Clipsal claim that use of C-Bus with non-Clipsal hardware or
> software may void your warranty.

## What is this?

A C-Bus protocol implementation and MQTT bridge for Home Assistant. No
proprietary `libcbm` library, no C-Gate, no Java runtime needed.

Two ways to run:

| Method | What it does |
|--------|-------------|
| **cmqttd** (Rust daemon) | Run on a Raspberry Pi, server, or Docker container. Connects to your CNI and bridges to MQTT. |
| **ESP32 firmware** | Flash an ESP32 board. It connects directly to your CNI and MQTT broker. No server, no Docker needed at runtime. |

Both produce identical Home Assistant MQTT Discovery messages, so you can
switch between them freely.

The original Python implementation lives in [`python-legacy/`](python-legacy/)
for reference. The Rust workspace in [`rust/`](rust/) is the maintained
implementation; it is wire- and MQTT-compatible with the Python daemon
bit-for-bit, as proven by the parity harness in
[`rust-migration-harness/`](rust-migration-harness/) (3,200+ golden vectors
plus an end-to-end behavioral suite — `./rust-migration-harness/run.sh` must
exit 0).

## cmqttd (Rust daemon)

### Build and run

```bash
cd rust
cargo build --release --workspace

# Plain MQTT broker, TCP CNI:
./target/release/cmqttd -b mqtt.example.com --broker-disable-tls \
    -t 192.168.1.100:10001 -P /path/to/project.cbz

# TLS broker using the system trust store (add -c for a custom CA
# file or directory, -A for a username/password file):
./target/release/cmqttd -b mqtt.example.com -t 192.168.1.100:10001
```

Useful flags (run `cmqttd --help` for the full list):

| flag | meaning |
|------|---------|
| `-b HOST` | MQTT broker address (required) |
| `-p PORT` | broker port; 0 = auto (8883 TLS / 1883 plain) |
| `--broker-disable-tls` | plaintext MQTT (insecure) |
| `-c PATH` | CA certificate file *or* directory of PEMs; default: system trust store |
| `-t HOST:PORT` | TCP connection to a CNI/PCI |
| `--esp32-wifi HOST[:PORT]` | connect via an ESP32 bridge over WiFi |
| `--esp32-serial DEV` | connect via an ESP32 bridge over USB serial (alias: `--serial`) |
| `--esp32-discover` | find an ESP32 bridge via mDNS (`_cbus._tcp`) |
| `-P FILE` | C-Bus Toolkit backup (`.cbz` or `.xml`) for entity names |
| `-N NAME` | network name within the project file |
| `-T SECONDS` | timesync interval (0 disables) |
| `-C` | don't answer clock requests |
| `-v LEVEL` | log verbosity (`DEBUG`..`CRITICAL`) |

### MQTT topics

cmqttd implements [Home Assistant MQTT Discovery][ha-auto]; lights appear
automatically. Topics follow the [JSON schema][ha-mqtt]:

| topic | purpose |
|-------|---------|
| `homeassistant/light/cbus_<ga>/config` | discovery config (retained) |
| `homeassistant/light/cbus_<ga>/set` | commands: `{"state": "ON", "brightness": 128, "transition": 4}` |
| `homeassistant/light/cbus_<ga>/state` | state echo (retained) |
| `homeassistant/binary_sensor/cbus_<ga>/state` | on/off as a binary sensor |

The default lighting application (0x38) uses the bare group address in
topics (`cbus_10`); other lighting apps use `cbus_<app:03>_<ga:03>`
(e.g. `cbus_048_011`).

### Docker

```bash
docker build -t cmqttd .
docker run -e "MQTT_SERVER=192.0.2.1" -e "CNI_ADDR=192.0.2.2:10001" \
    -e "TZ=Australia/Adelaide" -it cmqttd
```

Or copy `.env.example` to `.env`, edit it, and `docker-compose up -d`.
Configuration is via environment variables (`MQTT_SERVER`, `MQTT_PORT`,
`MQTT_USE_TLS`, `CNI_ADDR`, `SERIAL_PORT`, `CBUS_TIMESYNC`, `CBUS_CLOCK`,
`CMQTTD_PROJECT_FILE`, `CMQTTD_CBUS_NETWORK`, `CMQTTD_VERBOSITY`); see
`entrypoint-cmqttd.sh`.

### Other binaries

The workspace also builds:

| binary | purpose |
|--------|---------|
| `cbus-simulator [addr] [port]` | fake PCI TCP server (default `127.0.0.1:10001`) — test without hardware |
| `cbus-tools decode <frame>` | decode a single C-Bus serial frame |
| `cbus-tools dump-labels <cbz>` | dump a Toolkit backup as JSON |
| `cbus-tools interrogate --tcp host:port --unit N` | read unit attributes over a CNI |
| `cbus-vector-check <dir>` | golden-vector runner used by the parity harness |

See [`rust/README.md`](rust/README.md) for crate-level details.

## ESP32 Firmware

The ESP32 replaces the entire cmqttd stack — one small device handles everything.

```
C-Bus Network <-> CNI (5500CN) <-> ESP32 <-> MQTT Broker <-> Home Assistant
                                   WiFi
```

### Quick Start

1. **Flash the firmware** to any ESP32 board (ESP32-WROOM, Lolin D32, NodeMCU, etc.):

   ```bash
   cd esp32-firmware
   pip install platformio
   pio run -e esp32dev -t upload
   ```

2. **Connect to the setup portal** — on first boot, the ESP32 creates a WiFi network called **CBus-Bridge** (password: `cbusbridge`). Connect with your phone or laptop and the captive portal opens automatically.

3. **Enter your settings:**
   - WiFi network name and password
   - CNI address and port (e.g. `192.168.1.100:10001`)
   - MQTT broker address and port
   - MQTT username/password (if required)
   - Timezone (POSIX TZ string, e.g. `AEST-10AEDT,M10.1.0,M4.1.0/3`)

4. **Save and reboot** — the ESP32 connects to your network and starts bridging C-Bus to MQTT. Lights appear in Home Assistant automatically via MQTT Discovery.

### Web Interface

Once connected, browse to the ESP32's IP address to see the status dashboard:

- **Status page** (`/`) — WiFi, CNI, MQTT connection status, active lights, uptime, free memory
- **Config page** (`/config`) — change all settings without reflashing
- **API** (`/api/status`) — JSON status endpoint for monitoring

### Serial Console

Connect via USB serial at 115200 baud for CLI configuration:

```
wifi <ssid> <password>   Set WiFi credentials and reboot
cni <host> <port>        Set CNI address
mqtt <host> <port>       Set MQTT broker address
mqttauth <user> <pass>   Set MQTT credentials
tz <posix_tz>            Set timezone
scan                     Scan for WiFi networks
status                   Show current status
reset                    Reboot device
factory                  Erase all settings and reboot
help                     Show commands
```

### Supported Boards

Any ESP32 board with WiFi works. Tested on:

- Lolin D32 Pro
- ESP32-WROOM-32 DevKit
- NodeMCU ESP32

The firmware uses ~65% flash and ~16% RAM, leaving plenty of headroom.

### Building for a Specific Board

```bash
cd esp32-firmware

# Generic ESP32
pio run -e esp32dev -t upload

# Lolin D32 Pro
pio run -e lolin_d32_pro -t upload
```

To set your serial port, create `platformio_override.ini` (gitignored):

```ini
[platformio]
default_envs = lolin_d32_pro

[env:lolin_d32_pro]
upload_port = /dev/cu.usbserial-XXXXX
monitor_port = /dev/cu.usbserial-XXXXX
```

## Hardware Support

Works with these C-Bus PC Interfaces:

| Interface | Connection | Notes |
|-----------|-----------|-------|
| [5500PC][5500PC] | Serial RS-232 | |
| [5500PCU][5500PCU] | USB (cp210x) | Linux kernel v2.6.25+ |
| [5500CN][5500CN] / [5500CN2][5500CN2] | Ethernet TCP | Must have IP configured |

## Project Structure

```
rust/                    Rust workspace (the maintained implementation)
  cbus-protocol/         wire codec: packets, CALs, SALs, decoder, JSON
  cbus-mqtt/             topics, HA discovery payloads, CBZ labels
  cbus-transport/        framing, PCI client state machine, TCP/serial
  cmqttd/                the MQTT bridge daemon
  cbus-simulator/        fake PCI TCP server
  cbus-tools/            decode / dump-labels / interrogate CLIs
  cbus-vector-check/     golden-vector runner

rust-migration-harness/  parity oracle: golden vectors + behavioral suite

esp32-firmware/          ESP32 Arduino firmware
  src/main.cpp           MQTT bridge firmware
  lib/cbus_core/         C-Bus protocol in C (shared with tests)
  test_exhaustive.c      511 C++ protocol tests

python-legacy/           the original Python implementation (reference only)
docs/                    Documentation
```

## Testing

```bash
# Rust unit + property tests
cd rust && cargo test --workspace

# Full parity harness (vectors + end-to-end behavioral suite)
./rust-migration-harness/run.sh

# Quick harness run (skips two ~2-minute throttle assertions)
SKIP_SLOW=1 ./rust-migration-harness/run.sh

# C++ protocol tests (native, no ESP32 needed)
cd esp32-firmware
cc -std=c11 -I lib/cbus_core/src lib/cbus_core/src/*.c test_exhaustive.c -o test_exhaustive
./test_exhaustive
```

## C-Bus Simulator

Test without hardware using the built-in simulator:

```bash
cd rust && cargo run -p cbus-simulator            # listens on 127.0.0.1:10001
```

Then point cmqttd or the ESP32 at `localhost:10001`.

## Logging

Control verbosity with the `CMQTTD_VERBOSITY` environment variable (Docker)
or the `-v` flag:

```bash
cmqttd -v DEBUG ...   # CRITICAL, ERROR, WARNING, INFO, DEBUG
```

## License

GNU Lesser General Public License v3.0 or later. See `COPYING` and `COPYING.LESSER`.

[5500PC]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500PC
[5500PCU]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500PCU
[5500CN]: https://updates.clipsal.com/ClipsalOnline/Files/Brochures/W0000348.pdf
[5500CN2]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500CN2
[ha-auto]: https://www.home-assistant.io/docs/mqtt/discovery/
[ha-mqtt]: https://www.home-assistant.io/integrations/light.mqtt/#json-schema
[clipsal-docs]: https://updates.clipsal.com/ClipsalSoftwareDownload/DL/downloads/OpenCBus/OpenCBusProtocolDownloads.html

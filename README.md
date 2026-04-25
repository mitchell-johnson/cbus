# libcbus

Talks to Clipsal C-Bus using Python 3.7+ and ESP32.

Copyright 2012-2020 Michael Farrell, 2024-2025 Mitchell Johnson.
Licensed under the GNU LGPL3+. See `COPYING` and `COPYING.LESSER`.

> **Note:** This software is not certified or endorsed by Clipsal or Schneider
> Electric. Clipsal claim that use of C-Bus with non-Clipsal hardware or
> software may void your warranty.

## What is this?

A pure-Python C-Bus protocol implementation and an **ESP32 firmware** that bridges C-Bus lighting to Home Assistant via MQTT. No proprietary `libcbm` library, no C-Gate, no Java runtime needed.

Two ways to run:

| Method | What it does |
|--------|-------------|
| **ESP32 firmware** (recommended) | Flash an ESP32 board. It connects directly to your CNI and MQTT broker. No server, no Docker, no Python needed at runtime. |
| **cmqttd** (Python daemon) | Run on a Raspberry Pi, server, or Docker container. Connects to your CNI and bridges to MQTT. |

Both produce identical Home Assistant MQTT Discovery messages, so you can switch between them freely.

## ESP32 Firmware (recommended)

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

## cmqttd (Python Docker/daemon)

The traditional Python approach — run on a server or Raspberry Pi.

### Docker Setup

1. Copy `.env.example` to `.env` and edit:

   ```bash
   cp .env.example .env
   ```

   ```env
   TZ=Australia/Sydney
   MQTT_USE_TLS=0
   MQTT_SERVER=mqtt.example.com
   CNI_ADDR=192.168.1.100:10001
   CMQTTD_CBUS_NETWORK=My Network
   ```

2. Start:

   ```bash
   docker-compose up -d
   ```

### Direct Install

```bash
pip install -e .
cmqttd -b mqtt.example.com --broker-disable-tls -t 192.168.1.100:10001
```

### ESP32 Connection Mode

cmqttd can also connect to an ESP32 bridge instead of a CNI directly:

```bash
# Connect via WiFi
cmqttd -b mqtt.example.com --esp32-wifi 192.168.1.50:10001

# Connect via USB serial
cmqttd -b mqtt.example.com --esp32-serial /dev/ttyUSB0

# Auto-discover ESP32 on the network via mDNS
cmqttd -b mqtt.example.com --esp32-discover
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
cbus/                    Python C-Bus protocol library
  protocol/              Packet encoding/decoding
  daemon/                cmqttd MQTT bridge
  transport/             TCP/Serial transport abstraction
  esp32/                 ESP32 connection manager & emulator
  web/                   Web configuration server

esp32-firmware/          ESP32 Arduino firmware
  src/main.cpp           MQTT bridge firmware
  lib/cbus_core/         C-Bus protocol in C (shared with tests)
  test_exhaustive.c      511 C++ protocol tests

cbus-simulator/          C-Bus PCI simulator for testing
cbus-proxy/              Protocol analyzer proxy

tests/                   Python test suite (800+ tests)
docs/                    Documentation
```

## Testing

The project has 1400+ automated tests across Python and C++:

```bash
# Python tests
pip install -e ".[test]"
pytest tests/ -v

# C++ protocol tests (native, no ESP32 needed)
cd esp32-firmware
cc -std=c11 -I lib/cbus_core/src lib/cbus_core/src/*.c test_exhaustive.c -o test_exhaustive
./test_exhaustive

# Real hardware tests (set ESP32_HOST env var)
ESP32_HOST=192.168.1.50 pytest tests/test_real_esp32.py -v
```

## C-Bus Simulator

Test without hardware using the built-in simulator:

```bash
python -m cbus_simulator --port 10001
```

Then point cmqttd or the ESP32 at `localhost:10001`.

## Logging

Control verbosity with the `CMQTTD_VERBOSITY` environment variable:

```bash
export CMQTTD_VERBOSITY=DEBUG   # CRITICAL, ERROR, WARNING, INFO, DEBUG
```

Or via CLI: `cmqttd --verbosity DEBUG ...`

## License

GNU Lesser General Public License v3.0 or later. See `COPYING` and `COPYING.LESSER`.

[5500PC]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500PC
[5500PCU]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500PCU
[5500CN]: https://updates.clipsal.com/ClipsalOnline/Files/Brochures/W0000348.pdf
[5500CN2]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500CN2
[ha-auto]: https://www.home-assistant.io/docs/mqtt/discovery/
[ha-mqtt]: https://www.home-assistant.io/integrations/light.mqtt/#json-schema
[clipsal-docs]: https://updates.clipsal.com/ClipsalSoftwareDownload/DL/downloads/OpenCBus/OpenCBusProtocolDownloads.html

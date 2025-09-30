# libcbus

[![Documentation Status](https://readthedocs.org/projects/cbus/badge/?version=latest)][rtd]

Talks to Clipsal C-Bus using Python 3.7+.

Copyright 2012-2020 Michael Farrell. Licensed under the GNU LGPL3+. For more
details see `COPYING` and `COPYING.LESSER`.

> **Note:** This software is not certified or endorsed by Clipsal or Schneider
> Electric. Clipsal claim that use of C-Bus with non-Clipsal hardware or
> software may void your warranty.

More information about the project is available on
[the libcbus ReadTheDocs site][rtd], and in the `docs` directory of the source
repository.

## About this project

This is a reimplementation of the PCI serial protocol _from scratch_. This is
done using a combination [Clipsal's _Open C-Bus_ documentation][clipsal-docs]
and reverse engineering (to fill in the gaps).

Unlike some contemporary alternatives, it does **not** use the `libcbm`
library/DLL from Clipsal, or C-Gate, which have serious problems:

* The `libcbm` module is written in C, and does not support `x86_64` or
  comparatively-modern ARM architectures (such as that used in the Raspberry
  Pi).

  `libcbm` was previously only available as a static library for `x86_32` Linux
  and Windows systems. [Source is available][libcbm-src] under the Boost
  license, but this was last updated in 2009.

* C-Gate requires an OS and architecture specific closed source serial
  library (SerialIO), the Java runtime, and itself has various licensing
  restrictions.

Because this is a pure-Python implementation, it should run on any Python
supported platform. It has been primarily developed on Linux on `armhf`,
`x86_32` and `x86_64` and macOS on `x86_64`.

At a high level, this project includes `cmqttd`, a daemon to bridge a C-Bus PCI
to an MQTT Broker. `cmqttd` supports Home Assistant's
[MQTT Light model][ha-mqtt] and [MQTT topic auto-discovery][ha-auto].

_Integration with Hass.io is still a work in progress._

## Docker Setup

This project includes Docker support for easy deployment. To use it:

1. Copy the `.env.example` file to `.env`:
   ```
   cp .env.example .env
   ```

2. Edit the `.env` file to match your configuration:
   ```
   # Timezone
   TZ=Your/Timezone

   # MQTT Settings
   MQTT_USE_TLS=0
   MQTT_SERVER=your-mqtt-server.example.com

   # C-Bus Settings
   CMQTTD_PROJECT_FILE=your-project.cbz
   CNI_ADDR=192.168.x.y:10001
   CMQTTD_CBUS_NETWORK=Your Network
   ```

3. Build and start the container:
   ```
   docker-compose up -d
   ```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `TZ` | Timezone for the container | `Australia/Sydney` |
| `MQTT_USE_TLS` | Whether to use TLS for MQTT connection (0=no, 1=yes) | `0` |
| `MQTT_SERVER` | MQTT broker address | `mqtt.example.com` |
| `CMQTTD_PROJECT_FILE` | C-Bus Toolkit project backup file | `project.cbz` |
| `CNI_ADDR` | C-Bus PCI address and port | `192.168.1.10:10001` |
| `CMQTTD_CBUS_NETWORK` | C-Bus network name | `My Network` |

The `.env` file is excluded from version control to keep your configuration private.

## Hardware interface support

This should work with the following C-Bus PC Interfaces (PCIs):

* [5500PC Serial PCI][5500PC]

* [5500PCU USB PCI][5500PCU]

  On Linux, this requires v2.6.25 or later kernel, with the `cp210x` module.

* [5500CN Ethernet PCI][5500CN] (and likely _also_ [5500CN2][])

  This software _does not_ support configuring the Ethernet PCI for the first
  time. It must already have an IP address on your network.

## C-Bus Protocol Analyzer Proxy

This project includes a transparent proxy that can intercept and analyze C-Bus communications 
between cmqttd and your CNI. This is useful for:

* Debugging C-Bus communication issues
* Learning how the C-Bus protocol works
* Monitoring your C-Bus network in real-time
* Analyzing packet timing and confirmations

### Using the Proxy

The proxy sits between cmqttd and your real CNI, logging all packets with detailed analysis:

```
┌─────────┐     TCP      ┌───────────┐     TCP      ┌─────────┐
│ cmqttd  │ ────────────▶│   Proxy   │ ────────────▶│   CNI   │
│         │◀──────────── │           │◀──────────── │         │
└─────────┘              └───────────┘              └─────────┘
                               │
                               ▼
                         Detailed Logs
```

To use the proxy with Docker Compose:

```bash
# Set your CNI address in .env
CNI_HOST=192.168.1.100
CNI_PORT=10001

# Start the proxy and cmqttd
cd cbus-proxy
docker-compose up
```

The proxy provides colored output showing:
* Raw packet data in hex and ASCII
* Decoded packet type and structure
* Command details (lighting on/off, ramp, status requests)
* Confirmation tracking
* Error detection
* Session statistics

See [cbus-proxy/README.md](cbus-proxy/README.md) for detailed documentation.

## C-Bus Simulator

For testing purposes, a C-Bus simulator is available in the `cbus-simulator` subdirectory. 
This can be used to simulate a C-Bus PCI without needing actual hardware. 
See the README.md file in that directory for more details.

# Logging Configuration

The C-Bus MQTT Daemon (cmqttd) now supports centralized logging configuration through a single environment variable.

## Configuration

### Using Environment Variable

Set the `CMQTTD_VERBOSITY` environment variable to control logging verbosity across all C-Bus components:

```bash
export CMQTTD_VERBOSITY=DEBUG
```

Valid values are:
- `CRITICAL` - Only critical errors
- `ERROR` - Errors and above
- `WARNING` - Warnings and above 
- `INFO` - Informational messages and above (default)
- `DEBUG` - All messages including debug output

### Using .env File

For local development, you can set the verbosity in your `.env` file:

```env
CMQTTD_VERBOSITY=DEBUG
```

The `.env` file is automatically loaded when running cmqttd locally.

### Docker Configuration

When running in Docker, set the environment variable in your `docker-compose.yml`:

```yaml
environment:
  - CMQTTD_VERBOSITY=INFO
```

Or pass it when running the container:

```bash
docker run -e CMQTTD_VERBOSITY=DEBUG ...
```

### Command Line Override

You can still override the logging level using the command line argument:

```bash
cmqttd --verbosity WARNING ...
```

The command line argument takes precedence over the environment variable.

## Benefits

- **Single Point of Control**: One environment variable controls logging for all C-Bus components
- **Consistent Formatting**: All log messages use the same format across modules
- **Environment-Friendly**: Works seamlessly with Docker and other deployment environments
- **Backwards Compatible**: Command line arguments still work as before
- **Development Friendly**: Automatically loads from `.env` file in development

## Troubleshooting

If logging doesn't appear to be working correctly:

1. Check that `CMQTTD_VERBOSITY` is set to a valid value
2. Ensure the environment variable is exported (not just set in the shell)
3. For Docker, verify the variable is passed to the container
4. Check for any command line `--verbosity` arguments that might override the setting 


## Recent updates (2024)

This project continues to be actively maintained with regular updates to dependencies and documentation.

There are many backward-incompatible changes:

* This _only_ supports Python 3.7 and later.

* Python 2.x support _has been entirely removed_, [as Python 2 has been sunset as of 2020][py2].

  Python 3.6 and earlier support is not a goal. We want to use new language features!

* D-Bus is no longer used by this project:

  * `cmqttd` (C-Bus to MQTT bridge) replaces `cdbusd` (C-Bus to D-Bus bridge).

  * `dbuspcid` (virtual PCI to D-Bus bridge) has been removed. It has no replacement.

* `sage` (libcbus' web interface) and `staged` (scene management system) have been removed.
  `cmqttd` supports [Home Assistant's MQTT Discovery schema][ha-auto].

  This allows `libcbus` to reduce its scope significantly -- Home Assistant can interface with much
  more hardware than C-Bus, and has a large community around it.

* This no longer uses Twisted -- `asyncio` (in the standard library) is used instead.

Many APIs have changed due to refactoring, and is subject to further change without notice. The
most stable API is via MQTT (`cmqttd`).

[rtd]: https://cbus.readthedocs.io/en/latest/
[5500PC]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500PC
[5500PCU]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500PCU
[5500CN]: https://updates.clipsal.com/ClipsalOnline/Files/Brochures/W0000348.pdf
[5500CN2]: https://www.clipsal.com/Trade/Products/ProductDetail?catno=5500CN2
[ha-auto]: https://www.home-assistant.io/docs/mqtt/discovery/
[ha-mqtt]: https://www.home-assistant.io/integrations/light.mqtt/#json-schema
[clipsal-docs]: https://updates.clipsal.com/ClipsalSoftwareDownload/DL/downloads/OpenCBus/OpenCBusProtocolDownloads.html
[libcbm-src]: https://sourceforge.net/projects/cbusmodule/files/source/
[py2]: https://www.python.org/doc/sunset-python-2/

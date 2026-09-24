# cmqttd configuration

## Required connections

`cmqttd` requires an MQTT broker address and exactly one C-Bus endpoint.

For a TCP CNI:

```sh
cmqttd --broker-address mqtt.local --tcp 192.168.1.10:10001
```

For a serial bridge:

```sh
cmqttd --broker-address mqtt.local --esp32-serial /dev/ttyUSB0
```

TLS is enabled unless `--broker-disable-tls` is set. With the default port value `0`, the bridge selects port 8883 for TLS and 1883 for plain MQTT.

## Authentication and TLS

`--broker-auth FILE` expects the username on line one and password on line two. `--broker-ca` accepts a PEM file or a directory of PEM files. If it is omitted, the system trust store is used. Client-certificate authentication requires both `--broker-client-cert` and `--broker-client-key`.

## Labels and network selection

Use `--project-file project.cbz` or a bare project XML file for human-readable labels. Use `--cbus-network Main Network` when the project contains multiple networks. Without a project file, address-derived labels are used.

## Time and status

`--timesync SECONDS` controls periodic time synchronization; zero disables it. `--no-clock` disables replies to C-Bus clock requests. `--status-resync SECONDS` controls periodic status sweeps; zero disables them.

## Docker

Copy `.env.example` to `.env` and set at least `MQTT_SERVER` plus `CNI_ADDR` or `SERIAL_PORT`. `docker compose up --build` uses a private bridge network, with outbound access to the configured CNI and broker. C-Gate port 20023 is published on the host's `127.0.0.1` only. Use reachable LAN addresses for the broker and CNI; container localhost is not the host's localhost.

Optional container files live in `cmqttd_config/`:

- `project.cbz`
- `auth`
- `certificates/`
- `client.pem` and `client.key`
- `unitspec/` containing privately installed decoded C-Gate unit specifications

These files are excluded from Git. The Docker build copies any that exist locally into `/etc/cmqttd`. Rebuild the image after changing copied files, or mount them into `/etc/cmqttd` at runtime.

The entrypoint maps environment variables to `cmqttd` options. `MQTT_USE_TLS=1` enables TLS, `CBUS_TIMESYNC` sets the synchronization interval, `CBUS_STATUS_RESYNC` sets the status interval, `CBUS_CLOCK=0` disables clock replies, and `CMQTTD_CBUS_NETWORK` selects a project network. The daemon runs as PID 1 so Docker stop signals reach it directly.

## Embedded C-Gate service

`--cgate-bind ADDRESS:PORT` enables the command service and requires a project
file. `--cgate-state FILE` selects its persistent database; the default is
`cmqttd-data/cgate.json`. `--cgate-unitspec DIR` supplies optional private decoded
vendor schemas for PP INFO/defaults and physical PP LOAD. The container entrypoint
passes `/etc/cmqttd/unitspec` automatically when that directory exists. Compose enables the service when a project is present, using
`CMQTTD_CGATE_BIND=0.0.0.0:20023` inside the container and a loopback-only host
port. Set that variable to `off` for MQTT only. State lives in the named
`cmqttd_data` volume; do not delete that volume when recreating containers.

See [C-Gate service and replacement status](cmqttd-cgate.md) for the actual
hardware operations, live eDLT label command, tests, and outstanding workflows.

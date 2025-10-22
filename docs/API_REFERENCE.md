# libcbus API Reference

**Version:** 0.2
**Last Updated:** 2025-10-22

This document provides a comprehensive API reference for the libcbus library.

---

## Table of Contents

1. [Core Protocol](#core-protocol)
2. [MQTT Gateway](#mqtt-gateway)
3. [Packet Types](#packet-types)
4. [Applications](#applications)
5. [Common Utilities](#common-utilities)
6. [Toolkit](#toolkit)

---

## Core Protocol

### PCIProtocol

The main protocol class for communicating with C-Bus PCI/CNI devices.

#### Class: `cbus.protocol.pciprotocol.PCIProtocol`

Main protocol handler that implements the C-Bus PCI serial protocol using asyncio.

**Constructor:**

```python
PCIProtocol(
    timesync_frequency: int = 10,
    handle_clock_requests: bool = True,
    connection_lost_future: Optional[Future] = None
)
```

**Parameters:**
- `timesync_frequency` (int): How often to send time sync packets to the network (in seconds). Set to 0 to disable. Default: 10
- `handle_clock_requests` (bool): Whether to automatically respond to clock requests from the network. Default: True
- `connection_lost_future` (Optional[Future]): Future that will be set when connection is lost. Default: None

**Example:**

```python
import asyncio
from cbus.protocol.pciprotocol import PCIProtocol

async def main():
    loop = asyncio.get_event_loop()
    connection_lost = loop.create_future()

    def factory():
        return PCIProtocol(
            timesync_frequency=300,  # Sync every 5 minutes
            handle_clock_requests=True,
            connection_lost_future=connection_lost
        )

    # Connect via TCP
    transport, protocol = await loop.create_connection(
        factory, '192.168.1.100', 10001
    )

    # Wait for connection loss
    await connection_lost

asyncio.run(main())
```

#### Methods

##### `lighting_group_on()`

Turn on lights for specified group addresses.

```python
async def lighting_group_on(
    self,
    group_addr: Union[int, Iterable[int]],
    application_addr: Union[int, Application]
) -> bytes
```

**Parameters:**
- `group_addr`: Group address(es) to turn on. Can be a single int (0-255) or an iterable of up to 9 ints.
- `application_addr`: Application address to use (typically `Application.LIGHTING` or values 0x30-0x5F)

**Returns:**
- `bytes`: Single-byte confirmation code for tracking the command

**Raises:**
- `ValueError`: If group_addr iterable contains more than 9 addresses
- `ValueError`: If group_addr is not in valid range (0-255)
- `IOError`: If transport is not connected

**Example:**

```python
from cbus.common import Application

# Turn on single light
await protocol.lighting_group_on(1, Application.LIGHTING)

# Turn on multiple lights at once
await protocol.lighting_group_on([1, 2, 3], Application.LIGHTING)

# Use different application address
await protocol.lighting_group_on(5, Application.LIGHTING_30)
```

##### `lighting_group_off()`

Turn off lights for specified group addresses.

```python
async def lighting_group_off(
    self,
    group_addr: Union[int, Iterable[int]],
    application_addr: Union[int, Application]
) -> bytes
```

**Parameters:**
- `group_addr`: Group address(es) to turn off. Can be a single int (0-255) or an iterable of up to 9 ints.
- `application_addr`: Application address to use

**Returns:**
- `bytes`: Single-byte confirmation code for tracking the command

**Raises:**
- `ValueError`: If group_addr iterable contains more than 9 addresses
- `ValueError`: If group_addr is not in valid range (0-255)
- `IOError`: If transport is not connected

**Example:**

```python
# Turn off single light
await protocol.lighting_group_off(1, Application.LIGHTING)

# Turn off multiple lights
await protocol.lighting_group_off([1, 2, 3], Application.LIGHTING)
```

##### `lighting_group_ramp()`

Ramp (fade) a light to a specified level over a duration.

```python
async def lighting_group_ramp(
    self,
    group_addr: int,
    application_addr: Union[int, Application],
    duration: int,
    level: int = 255
) -> bytes
```

**Parameters:**
- `group_addr`: Group address to ramp (0-255)
- `application_addr`: Application address to use
- `duration`: Duration in seconds (0-1020). Values are rounded to nearest supported duration.
- `level`: Target brightness level (0-255). 0=off, 255=full brightness. Default: 255

**Returns:**
- `bytes`: Single-byte confirmation code for tracking the command

**Raises:**
- `ValueError`: If group_addr is not in valid range (0-255)
- `ValueError`: If duration is negative
- `ValueError`: If level is not in range 0-255
- `IOError`: If transport is not connected

**Supported Durations:**

C-Bus supports specific fade durations:
- 0 (instant)
- 4, 8, 12, 20, 30, 40 seconds
- 1:00, 1:30, 2:00, 3:00, 5:00, 7:00, 10:00, 15:00, 17:00 (minutes:seconds)

Values between these are rounded to the nearest supported duration.

**Example:**

```python
# Fade to 50% brightness over 4 seconds
await protocol.lighting_group_ramp(1, Application.LIGHTING, 4, 128)

# Fade to full brightness over 30 seconds
await protocol.lighting_group_ramp(1, Application.LIGHTING, 30, 255)

# Instant on to 75%
await protocol.lighting_group_ramp(1, Application.LIGHTING, 0, 192)
```

##### `lighting_group_terminate_ramp()`

Stop a light that is currently ramping.

```python
async def lighting_group_terminate_ramp(
    self,
    group_addr: Union[int, Iterable[int]],
    application_addr: Union[int, Application]
) -> bytes
```

**Parameters:**
- `group_addr`: Group address(es) to stop ramping
- `application_addr`: Application address to use

**Returns:**
- `bytes`: Single-byte confirmation code

**Example:**

```python
# Start ramping
await protocol.lighting_group_ramp(1, Application.LIGHTING, 30, 255)

# Stop the ramp after 5 seconds
await asyncio.sleep(5)
await protocol.lighting_group_terminate_ramp(1, Application.LIGHTING)
```

##### `request_status()`

Request the current status of group addresses.

```python
async def request_status(
    self,
    group_addr: Union[int, Iterable[int]],
    application_addr: Union[int, Application]
) -> bytes
```

**Parameters:**
- `group_addr`: Starting group address for status request (typically a block start like 0, 32, 64, etc.)
- `application_addr`: Application address to query

**Returns:**
- `bytes`: Single-byte confirmation code

**Note:** Status responses are received via the `on_level_report()` event handler.

**Example:**

```python
# Request status for groups 0-31
await protocol.request_status(0, Application.LIGHTING)

# Request status for groups 32-63
await protocol.request_status(32, Application.LIGHTING)
```

##### `clock_datetime()`

Send the current date/time to the C-Bus network.

```python
async def clock_datetime(
    self,
    when: Optional[datetime] = None
) -> bytes
```

**Parameters:**
- `when`: The datetime to send. If None, uses current local time. Default: None

**Returns:**
- `bytes`: Single-byte confirmation code

**Example:**

```python
from datetime import datetime

# Send current time
await protocol.clock_datetime()

# Send specific time
specific_time = datetime(2024, 1, 1, 12, 0, 0)
await protocol.clock_datetime(specific_time)
```

##### `identify()`

Send an IDENTIFY command to query device information.

```python
async def identify(
    self,
    unit_address: int,
    attribute: int
) -> bytes
```

**Parameters:**
- `unit_address`: Unit address to query (0-255)
- `attribute`: Attribute ID to retrieve (see `IdentifyAttribute` enum)

**Returns:**
- `bytes`: Single-byte confirmation code

**Example:**

```python
from cbus.common import IdentifyAttribute

# Get manufacturer info
await protocol.identify(10, IdentifyAttribute.MANUFACTURER)

# Get firmware version
await protocol.identify(10, IdentifyAttribute.FIRMWARE_VER)
```

#### Event Handlers

Override these methods to handle events from the C-Bus network.

##### `on_lighting_group_on()`

Called when a lighting "on" event is received.

```python
def on_lighting_group_on(
    self,
    source_addr: int,
    group_addr: int,
    application_address: int
) -> None
```

**Parameters:**
- `source_addr`: Unit address that generated the event
- `group_addr`: Group address that was turned on
- `application_address`: Application address

##### `on_lighting_group_off()`

Called when a lighting "off" event is received.

```python
def on_lighting_group_off(
    self,
    source_addr: int,
    group_addr: int,
    application_address: int
) -> None
```

**Parameters:**
- `source_addr`: Unit address that generated the event
- `group_addr`: Group address that was turned off
- `application_address`: Application address

##### `on_lighting_group_ramp()`

Called when a lighting ramp event is received.

```python
def on_lighting_group_ramp(
    self,
    source_addr: int,
    group_addr: int,
    application_address: int,
    duration: int,
    level: int
) -> None
```

**Parameters:**
- `source_addr`: Unit address that generated the event
- `group_addr`: Group address being ramped
- `application_address`: Application address
- `duration`: Ramp duration in seconds
- `level`: Target level (0-255)

##### `on_level_report()`

Called when a level status report is received.

```python
def on_level_report(
    self,
    application: int,
    block_start: int,
    report: LevelStatusReport
) -> None
```

**Parameters:**
- `application`: Application address
- `block_start`: Starting group address of the report block
- `report`: LevelStatusReport object containing levels

**Example:**

```python
class MyProtocol(PCIProtocol):
    def on_level_report(self, application, block_start, report):
        for i, level in enumerate(report):
            if level is not None:
                ga = block_start + i
                print(f"Group {ga}: level={level}")
```

##### `on_confirmation()`

Called when a confirmation response is received.

```python
def on_confirmation(
    self,
    code: bytes,
    success: bool
) -> None
```

**Parameters:**
- `code`: Confirmation code that was acknowledged
- `success`: True if command succeeded, False if it failed

##### `on_clock_request()`

Called when a device requests time from the network.

```python
def on_clock_request(
    self,
    source_addr: int
) -> None
```

**Parameters:**
- `source_addr`: Unit address requesting time

**Note:** If `handle_clock_requests=True` was set in the constructor, this method will automatically respond with the current time.

---

## MQTT Gateway

### CBusHandler

Extends PCIProtocol to bridge C-Bus events to MQTT.

#### Class: `cbus.daemon.mqtt_gateway.CBusHandler`

```python
class CBusHandler(PCIProtocol):
    def __init__(
        self,
        labels: Optional[Dict[int, Dict]] = None,
        *args,
        **kwargs
    )
```

**Parameters:**
- `labels`: Dictionary mapping application addresses to (name, {group_addr: label}) tuples
- `*args, **kwargs`: Passed to PCIProtocol constructor

**Example:**

```python
labels = {
    0x38: ("Lighting", {
        1: "Living Room",
        2: "Kitchen",
        3: "Bedroom"
    })
}

handler = CBusHandler(
    labels=labels,
    timesync_frequency=300
)
```

### MqttClient

Manages MQTT connection and publishes C-Bus events.

#### Class: `cbus.daemon.mqtt_gateway.MqttClient`

```python
class MqttClient:
    def __init__(
        self,
        userdata: CBusHandler,
        host: str,
        port: int,
        keepalive: int,
        tls_kwargs: dict | None
    )
```

**Parameters:**
- `userdata`: CBusHandler instance to bridge with
- `host`: MQTT broker hostname
- `port`: MQTT broker port
- `keepalive`: MQTT keepalive interval in seconds
- `tls_kwargs`: TLS configuration dict (see aiomqtt documentation)

**Example:**

```python
import ssl

tls_context = ssl.create_default_context()
tls_kwargs = {'tls_context': tls_context}

mqtt_client = MqttClient(
    handler,
    "mqtt.example.com",
    8883,
    60,
    tls_kwargs
)

async with mqtt_client:
    # Connection is now active
    await connection_lost_future
```

---

## Packet Types

### PointToMultipointPacket

Broadcast packet sent to multiple devices.

```python
from cbus.protocol.pm_packet import PointToMultipointPacket
from cbus.protocol.application.lighting import LightingOnSAL

packet = PointToMultipointPacket(
    sals=[LightingOnSAL(group_addr=1, application=Application.LIGHTING)]
)
```

### PointToPointPacket

Direct communication with a specific device.

```python
from cbus.protocol.pp_packet import PointToPointPacket
from cbus.protocol.cal.identify import IdentifyCAL

packet = PointToPointPacket(
    unit_address=10,
    cals=[IdentifyCAL(attribute=IdentifyAttribute.MANUFACTURER)]
)
```

---

## Applications

### Application Enum

```python
from cbus.common import Application

# Lighting applications (0x30 - 0x5F)
Application.LIGHTING          # 0x38 (default lighting)
Application.LIGHTING_30       # 0x30
Application.LIGHTING_5F       # 0x5F

# Other applications
Application.CLOCK            # 0xDF
Application.TEMPERATURE      # 0x19
Application.ENABLE           # 0xCB
Application.STATUS_REQUEST   # 0xFF
```

### LightingApplication

```python
from cbus.protocol.application import LightingApplication

# Get all supported lighting application addresses
apps = LightingApplication.supported_applications()
# Returns: [0x30, 0x31, ..., 0x5F]
```

---

## Common Utilities

### Group Address Validation

```python
from cbus.common import validate_ga, check_ga

# Validate (returns bool)
is_valid = validate_ga(100)  # True
is_valid = validate_ga(300)  # False

# Check (raises exception)
check_ga(100)  # OK
check_ga(300)  # Raises ValueError
```

### Ramp Rate Conversion

```python
from cbus.common import duration_to_ramp_rate, ramp_rate_to_duration

# Convert duration to ramp rate code
rate = duration_to_ramp_rate(30)  # Returns LightCommand.RAMP_00_30

# Convert ramp rate code to duration
duration = ramp_rate_to_duration(rate)  # Returns 30
```

### Checksum Functions

```python
from cbus.common import cbus_checksum, add_cbus_checksum, validate_cbus_checksum

# Calculate checksum
data = b'\x05\x38\x00\x79\x64'
checksum = cbus_checksum(data)

# Add checksum
data_with_checksum = add_cbus_checksum(data)

# Validate checksum
is_valid = validate_cbus_checksum(data_with_checksum)
```

---

## Toolkit

### CBZ File Parser

Parse C-Bus Toolkit project backup files.

```python
from cbus.toolkit.cbz import CBZ

with open('project.cbz', 'rb') as f:
    cbz = CBZ(f)

    # Access project structure
    for network in cbz.installation.project.network:
        print(f"Network: {network.tag_name}")

        for application in network.applications:
            print(f"  Application {application.address}: {application.tag_name}")

            for group in application.groups:
                print(f"    Group {group.address}: {group.tag_name}")
```

### Periodic Task Scheduler

```python
from cbus.toolkit.periodic import Periodic

# Create throttler with 200ms period
throttler = Periodic(period=0.2)

# Queue a task
throttler.enqueue(lambda: print("Task executed"))

# Cleanup
await throttler.cleanup()
```

---

## Configuration

### Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `CMQTTD_VERBOSITY` | Logging level | INFO | DEBUG, INFO, WARNING, ERROR, CRITICAL |

### Logging Configuration

```python
from cbus.logging_config import configure_logging

# Configure logging
logger = configure_logging('cbus', default_level='DEBUG')

# Or get a pre-configured logger
from cbus.logging_config import get_configured_logger
logger = get_configured_logger('cbus.protocol')
```

---

## Error Handling

### Common Exceptions

- `ValueError`: Invalid parameters (group address out of range, etc.)
- `IOError`: Transport not connected
- `json.JSONDecodeError`: Invalid MQTT payload
- `asyncio.CancelledError`: Task cancelled
- `MqttError`: MQTT connection/operation failed

### Example Error Handling

```python
from cbus.common import check_ga

try:
    await protocol.lighting_group_on(300, Application.LIGHTING)
except ValueError as e:
    print(f"Invalid group address: {e}")
except IOError as e:
    print(f"Connection error: {e}")
```

---

## Type Hints Reference

```python
from typing import Union, Iterable, Optional, Dict, Tuple
from cbus.common import Application

# Common type aliases
GroupAddress = int  # 0-255
ApplicationAddress = Union[int, Application]
GroupAddresses = Union[int, Iterable[int]]
Level = int  # 0-255
Duration = int  # seconds
ConfirmationCode = bytes  # single byte

# Label structure
Labels = Dict[int, Tuple[str, Dict[int, str]]]
# {app_addr: (app_name, {group_addr: group_label})}
```

---

## Complete Example

```python
import asyncio
from cbus.protocol.pciprotocol import PCIProtocol
from cbus.common import Application
import logging

logging.basicConfig(level=logging.INFO)

class MyHandler(PCIProtocol):
    def on_lighting_group_on(self, source, group, app):
        print(f"Light {group} turned ON from source {source}")

    def on_lighting_group_off(self, source, group, app):
        print(f"Light {group} turned OFF from source {source}")

    def on_lighting_group_ramp(self, source, group, app, duration, level):
        print(f"Light {group} ramping to {level} over {duration}s")

async def main():
    loop = asyncio.get_event_loop()
    connection_lost = loop.create_future()

    # Create protocol
    protocol = MyHandler(
        timesync_frequency=300,
        connection_lost_future=connection_lost
    )

    # Connect to CNI
    transport, _ = await loop.create_connection(
        lambda: protocol,
        '192.168.1.100',
        10001
    )

    # Wait for connection to establish
    await asyncio.sleep(2)

    # Control lights
    await protocol.lighting_group_on(1, Application.LIGHTING)
    await asyncio.sleep(2)

    await protocol.lighting_group_ramp(1, Application.LIGHTING, 4, 128)
    await asyncio.sleep(5)

    await protocol.lighting_group_off(1, Application.LIGHTING)

    # Wait for connection loss
    await connection_lost

if __name__ == '__main__':
    asyncio.run(main())
```

---

**End of API Reference**

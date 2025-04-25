# C-Bus Protocol Documentation

This document outlines the C-Bus protocol implemented by the C-Bus Simulator. The protocol is based on the Clipsal C-Bus Serial Interface Protocol documentation.

## Protocol Overview

The C-Bus protocol is a command-based protocol used to communicate with C-Bus networks via a PCI (PC Interface). Commands are sent as ASCII text strings terminated by carriage return and line feed characters (`\r\n`).

The simulator implements two operating modes:

1. **Basic Mode**: In this mode, all commands are echoed back to the client before being processed.
2. **Smart Mode**: In this mode, commands are not echoed, and a `+` character is used to indicate the PCI is ready to receive commands.

## Command Format

Most C-Bus commands follow this general format:

```
[#]<source_addr>//<network_id>A<application_id><command><parameters>
```

Where:
- `#` (optional): Request confirmation of command receipt
- `source_addr`: Source address (0-255)
- `network_id`: Network address (0-255)
- `application_id`: Application address (0-255)
- `command`: Single character command code
- `parameters`: Command-specific parameters

## Basic Commands

### Mode Selection

- `X`: Switch to Basic Mode
- `Y`: Switch to Smart Mode

### Reset

- `~~~`: Reset the PCI

## Application Commands

### Lighting Application (56)

Lighting commands use application code 56 and have the following formats:

#### Turn On

```
[#]<source_addr>//<network_id>A56N<group_id>
```

Example: `#3//254A56N1` - Turn on group 1 on network 254, with source address 3 and request confirmation

#### Turn Off

```
[#]<source_addr>//<network_id>A56F<group_id>
```

Example: `#3//254A56F1` - Turn off group 1 on network 254, with source address 3 and request confirmation

#### Ramp

```
[#]<source_addr>//<network_id>A56R<group_id>D<duration>
```

Example: `#3//254A56R1D5` - Ramp group 1 on network 254 over 5 seconds, with source address 3 and request confirmation

#### Terminate Ramp

```
[#]<source_addr>//<network_id>A56T<group_id>
```

Example: `#3//254A56T1` - Terminate ramp for group 1 on network 254, with source address 3 and request confirmation

#### Status Request

```
[#]<source_addr>//<network_id>A56G<group_id>
```

Example: `#3//254A56G1` - Request status of group 1 on network 254, with source address 3 and request confirmation

### Temperature Broadcast (202)

Temperature commands use application code 202 and have the following format:

```
[#]<source_addr>//<network_id>A202B<zone_id>T<temperature>
```

Example: `#3//254A202B1T225` - Broadcast temperature of 22.5°C for zone 1 on network 254, with source address 3 and request confirmation

### Clock Application (223)

Clock commands use application code 223 and have the following format:

```
[#]<source_addr>//<network_id>A223T<hh><mm><ss><DD><MM><YY>W<day>
```

Example: `#3//254A223T102030150322W1` - Set clock to 10:20:30, 15/03/2022, Monday, with source address 3 and request confirmation

## PCI Management Commands

### Identify

```
[#]<source_addr>//<network_id>I<unit_address>A<attribute>
```

Example: `#3//254I0A0` - Request identification of unit 0, attribute 0 (interface type), with source address 3 and request confirmation

### MMI Request

```
[#]<source_addr>//<network_id>MMI<attribute>
```

Example: `#3//254MMI0` - Request MMI attribute 0, with source address 3 and request confirmation

## Responses

### Command Confirmation

When a command includes the `#` prefix, the PCI will send a confirmation response:

- `.` followed by a confirmation code (hex): Command accepted
- `!` followed by a confirmation code (hex): Command rejected

Example: `.81+`

### Status Responses

Status responses have different formats depending on the application. For lighting:

- `<source_addr>//<network_id>A56N<group_id>`: Group is ON
- `<source_addr>//<network_id>A56F<group_id>`: Group is OFF
- `<source_addr>//<network_id>A56L<group_id>=<level>`: Group is at the specified level

Example: `5//254A56N1` - Group 1 is ON, reported by source address 5

### Identify Responses

```
<source_addr>//<network_id>IC<unit_address>A<attribute>="<value>"
```

Example: `5//254IC0A0="5500CN"` - Unit 0 has interface type "5500CN", reported by source address 5

## Error Responses

Error responses begin with `!` followed by an error message:

```
!<error_message>
```

Example: `!Unknown command: XYZ`

## Common Values

### Application IDs

- 56: Lighting
- 202: Temperature Broadcast
- 223: Clock

### Confirmation Codes

Confirmation codes range from 0x80 to 0xFF (128-255). The PCI cycles through these codes for different commands.

### Network IDs

Network IDs typically range from 0 to 255, with 254 being a common default.

### Source Addresses

Source addresses typically range from 0 to 255, with special meanings for some values:
- 0: Reserved
- 1-250: Regular devices
- 251-255: Special purposes 
# C-Bus Proxy Capture Analysis - 2026-04-26

Captured via `cbus-proxy` intercepting traffic between cmqttd and the CNI.

## Network Configuration

| Parameter | Value |
|---|---|
| Network Name | Grenache Way |
| CNI Address | 192.168.1.21:10001 |
| CNI Unit Address | 16 (0x10) |
| CNI Type | PC_CNIED (PC CNI Ethernet) |
| CNI Firmware | 5.5.00 |
| Proxy Listen | 0.0.0.0:10001 |

## Capture Summary

| Metric | Value |
|---|---|
| Duration | 12:42:16 - 12:54:45 (12 min 29 sec) |
| Total Packets | 1,465 |
| Client -> CNI | 499 |
| CNI -> Client | 966 |
| Client Sessions | 3 (cmqttd reconnect cycle) |
| Confirmations | 426 (all SUCCESS, 0 errors) |

### Packet Type Breakdown

| Type | Count | Notes |
|---|---|---|
| InvalidPacket | 615 | Parser limitations (see below) |
| ConfirmationPacket | 426 | All successful (g. through z.) |
| PointToPointPacket | 408 | Unit interrogation + status reports |
| SmartConnectShortcutPacket | 5 | Connection initialization |
| ResetPacket | 1 | PCI reset during init |
| PCIErrorPacket | 1 | Buffer full during first connect attempt |

## Device Inventory

29 units discovered on the network:

| Unit | Address | Type Code | Description | Firmware |
|---|---|---|---|---|
| 0 | 0x00 | *(unknown)* | *(type name not captured)* | 2.7.00 |
| 1 | 0x01 | RELDN12 | 12-Channel Relay Dimmer | 2.7.00 |
| 3 | 0x03 | DIMDN8 | 8-Channel Leading Edge Dimmer | 2.7.00 |
| 4 | 0x04 | KEYE1 | eDLT 1-Gang Key Input | - |
| 5 | 0x05 | KEYGL5 | 5-Gang Key Input | 5.5.00 |
| 14 | 0x0E | *(unknown)* | *(type name not captured)* | 2.5.00 |
| 15 | 0x0F | KEYE2 | eDLT 2-Gang Key Input | 2.5.00 |
| 16 | 0x10 | PC_CNIED | PC CNI (Ethernet Interface) | 5.5.00 |
| 17 | 0x11 | KEYE1 | eDLT 1-Gang Key Input | 2.5.00 |
| 18 | 0x12 | KEYE2 | eDLT 2-Gang Key Input | 2.5.00 |
| 19 | 0x13 | DIMDN8 | 8-Channel Leading Edge Dimmer | - |
| 20 | 0x14 | KEYE2 | eDLT 2-Gang Key Input | 2.5.00 |
| 21 | 0x15 | *(unknown)* | *(type name not captured)* | 2.5.00 |
| 22 | 0x16 | KEYE2 | eDLT 2-Gang Key Input | 2.5.00 |
| 23 | 0x17 | KEYE3 | eDLT 3-Gang Key Input | 2.5.00 |
| 24 | 0x18 | KEYE2 | eDLT 2-Gang Key Input | - |
| 25 | 0x19 | KEYE3 | eDLT 3-Gang Key Input | 2.5.00 |
| 26 | 0x1A | *(unknown)* | *(type name not captured)* | 2.5.00 |
| 27 | 0x1B | KEYE2 | eDLT 2-Gang Key Input | 2.5.00 |
| 28 | 0x1C | KEYE3 | eDLT 3-Gang Key Input | 2.5.00 |
| 29 | 0x1D | *(unknown)* | *(type name not captured)* | 2.5.00 |
| 30 | 0x1E | KEYE1 | eDLT 1-Gang Key Input | 2.5.00 |
| 31 | 0x1F | KEYE3 | eDLT 3-Gang Key Input | 2.5.00 |
| 32 | 0x20 | KEYE1 | eDLT 1-Gang Key Input | - |
| 33 | 0x21 | KEYE1 | eDLT 1-Gang Key Input | 2.5.00 |
| 34 | 0x22 | *(unknown)* | *(type name not captured)* | 2.5.00 |
| 35 | 0x23 | SENPIROA | PIR Occupancy Sensor | 2.4.00 |
| 36 | 0x24 | KEYE1 | eDLT 1-Gang Key Input | 2.5.00 |
| 37 | 0x25 | KEYE2 | eDLT 2-Gang Key Input | - |

### Device Type Summary

| Type | Count | Description |
|---|---|---|
| KEYE2 | 8 | eDLT 2-Gang Key Input |
| KEYE1 | 6 | eDLT 1-Gang Key Input |
| KEYE3 | 4 | eDLT 3-Gang Key Input |
| *(unknown)* | 5 | Type name not captured in session |
| DIMDN8 | 2 | 8-Channel Leading Edge Dimmer |
| RELDN12 | 1 | 12-Channel Relay Dimmer |
| KEYGL5 | 1 | 5-Gang Key Input |
| PC_CNIED | 1 | PC CNI (Ethernet Interface) |
| SENPIROA | 1 | PIR Occupancy Sensor |

Unit 2 is absent from the network (gap between units 1 and 3).

## Lighting Status at Capture Time

Application 56 (0x38) - Lighting. 42 groups configured across 3 status blocks.

### Groups ON (11)

| Group | Decimal |
|---|---|
| 14, 16, 20, 21, 22, 24, 26, 32, 34, 35, 38 | |

### Groups OFF (31)

Groups 0-13, 15, 17-19, 23, 25, 27-31, 33, 36, 37, 39, 42, 43

## cmqttd Connection Protocol

cmqttd connects, interrogates, disconnects, and reconnects with progressively more
complete initialization. Three sessions were captured:

### Session 1 (12:42:56 - 12:43:00, 4 seconds)

Quick connect, partial init, hit a PCI error (buffer full), disconnected.

### Session 2 (12:43:53 - 12:43:55, 2 seconds)

Clean connect with confirmation codes. Read CNI type name, firmware,
output summary from unit 1. Disconnected.

### Session 3 (12:50:00 - ongoing, main session)

Full interrogation of all 29 units. 479 commands sent, 426 confirmations received.

## Protocol Sequence (cmqttd Initialization)

### Phase 1: Connection Setup

```
CLIENT: null\r          # Wake PCI from sleep
CLIENT: \r              # Empty line sync
CLIENT: ||\r            # SMART+CONNECT shortcut
CLIENT: @1A2001\r       # Device Management: set interface options byte 1
```

The `@` prefix indicates a Device Management command sent directly to the attached
PCI/CNI (not addressed to a specific unit on the bus).

### Phase 2: CNI Identification

```
CLIENT: \4610002101g\r  # PP to unit 16: read Type Name (attr 0x01)
CNI:    g.              # Confirmation: success
CNI:    890150435F434E49454421  # Reply: "PC_CNIED"
```

The `\` prefix indicates a Point-to-Point command. Format:
- `\46` = PP header (extended message, 0x46)
- `10` = destination unit address
- `00` = destination point
- `2101` = CAL: read attribute 0x01 (Type Name)
- `g` = confirmation code (g-z cycling)

### Phase 3: Status Request

```
CLIENT: \05FF00FAFF00h\r   # PM broadcast: request all status
CNI:    h.                  # Confirmation: success
CNI:    86101000F900FF00... # Binary Status Report (block 0)
CNI:    86101000F900FF58... # Binary Status Report (block 88)
CNI:    86101000F700FFB0... # Binary Status Report (block 176)
```

The `\05` prefix is a Point-to-Multipoint command:
- `05` = PM header
- `FF00` = destination (broadcast)
- `FAFF00` = Status Request SAL: request binary levels for all applications

### Phase 4: Unit Interrogation

For each discovered unit, cmqttd reads a standard set of attributes via PP commands.
The query sequence per unit varies by device type but typically includes:

```
\46UU002101cc     # Read Type Name (attr 0x01)
\46UU0021021A2102cc  # Read Firmware Version (attr 0x02, chained)
\46UU002104cc     # Read Serial Number (attr 0x04)
\46UU001A2306cc   # Read Output Summary (attr 0x23, 6 bytes)
\46UU001A2A06cc   # Read GAV Store (attr 0x2A, 6 bytes)
\46UU001AF201cc   # Read Installed Applications (attr 0xF2)
\46UU001A210Ccc   # Read Identify block (attr 0x21, 12 bytes)
\46UU001A500Ccc   # Read attr 0x50 (12 bytes)
\46UU001A5C04cc   # Read attr 0x5C (4 bytes)
\46UU002110cc     # Read Terminal Levels (attr 0x10)
```

Where `UU` = unit address (hex), `cc` = rolling confirmation code (g-z).

### Phase 5: Periodic Status Polling

After interrogation, cmqttd re-requests binary status reports every few minutes.
The CNI also sends unsolicited status updates (from unit 20/0x14) containing
Lighting App 38 state for all 256 groups in 3 blocks (0, 88, 176).

## Confirmation Code Protocol

C-Bus uses rolling single-character confirmation codes (g through z, 20 codes).
Each command sent by the client includes a confirmation code character appended
before the `\r`. The CNI responds with either:

- `X.` (success) - where X is the confirmation code character
- `X#` (checksum error)
- `X!` (unrecognized/rejected)

This allows the client to match responses to commands even with interleaved traffic.
All 426 confirmations in this capture were successful.

## Parser Observations

615 packets (42%) were marked InvalidPacket by the cbus library parser. Root causes:

| Error | Count | Notes |
|---|---|---|
| Checksum strict mode | ~400 | Parser validates checksums that the CNI accepted |
| Invalid DestinationAddressType | ~20 | Device Management responses use address types 1,2,7 not in parser enum |
| Non-base16 input | ~5 | Reset sequences contain `~` (0x7E) mixed with hex |
| Routing data errors | 2 | PM messages with unexpected routing |
| Other | ~10 | Various edge cases |

The high InvalidPacket rate indicates the cbus library's packet decoder does not
handle the full range of Device Management CAL responses. The CNI accepted all
commands (100% confirmation success rate), so the packets themselves are valid
C-Bus protocol - the parser is incomplete for these packet types.

### Key gaps in the parser:

1. **Device Management responses** (address types 1, 2, 7) are not decoded
2. **Checksum validation** is too strict - the parser computes checksums differently
   than what the CNI sends for short-form CAL commands
3. **Reset/init sequences** (`~~~`, `***`) are not cleanly separated from subsequent data
4. **Chained CAL commands** (e.g., `21021A2102` = read attr 2 then read attr 2 again)
   are not fully parsed

---

## Unit 5 (0x05) KEYGL5 - 5-Gang Key Input Deep Dive

Captured during a dedicated unit detail load via the C-Bus Toolkit.

### Identity

| Field | Value |
|---|---|
| Type Code | KEYGL5 |
| Description | 5-Gang Key Input Unit |
| Unit Address | 5 (0x05) |
| Firmware | 01.05.00 (extended), 5.5.00 (short) |
| Serial Number | FF:FF:FF:00:00:18:B3:F6:82:A4:00:01 |
| Unique ID | 000018B3F682 |
| Manufacturer Code | 18B3F682 |
| Parameter Area | 0x40 (64) |

### Installed Applications

| App ID | Decimal | Name |
|---|---|---|
| 0x38 | 56 | Lighting |
| 0x19 | 25 | Trigger Control |
| 0x1B | 27 | Enable Control |
| 0x18 | 24 | Heating |
| 0x21 | 33 | Error Reporting |

The unit has 5 applications installed. Lighting (0x38) is the primary application
with config byte 0xFF (all groups enabled).

### Terminal Levels (attr 0x10)

```
Input 0: 0x80 (128) - active
Input 1: 0x00 (0)   - inactive
Input 2: 0x00 (0)   - inactive
Input 3: 0xFF (255) - active/high
```

### Key Group Assignments

The key mapping data from the extended CAL reads shows the group addresses
this unit controls. Extracted from attr 0x01 response block:

```
Raw mapping: 32 00 02 05 00 FF 16 10 0E 00 10 19 00 10 1B 00
             10 21 00 10 18 00 02 00 FF FF FF 02 00 FF FF FF
```

Referenced groups: 5, 14 (0x0E), 22 (0x16), 25 (0x19), 27 (0x1B),
33 (0x21), 50 (0x32)

### Key Programming Data

The unit's 5 keys are programmed with specific actions. Each key programming
block defines the key behavior (toggle, ramp, scene recall, etc.):

```
Block 1: 02 33 02 01 00 00 1B 0F 10 01 FF FF 19 3F 00 00
Block 2: 02 33 02 01 00 00 19 0F 10 01 FF FF 19 3E 00 00
Block 3: 02 33 02 01 00 00 21 0F 10 01 FF FF 19 1C 00 26
Block 4: 06 30 26 25 00 00 00 1A 1B 01 FF 00 00 FF FF
```

Key programming structure (per block):
- Byte 0: Key function type (0x02 = toggle/on-off, 0x06 = scene/trigger)
- Byte 1: Primary group address
- Byte 2-3: Action parameters
- Remaining: Associated groups, enable control, trigger actions

### GAV/Zone Data (attr 0x20)

```
Raw: 05 FF FF 9B 19 2D 82 29 E4 FF 92 3A
```

### Group Address Table (attr 0x2C)

```
Raw: F3 79 E7 9E 79 FF FF FF FF FF FF FF
```

This is a bitmap of which group addresses the unit participates in.
Each bit corresponds to a group number. Active bits indicate the unit
is programmed to respond to or generate events for that group.

### Interrogation Protocol for Key Input Units

The toolkit reads the following attributes when loading unit details:

1. `2104` - Serial Number (attr 0x04)
2. `1A200C` - GAV/Zone data (attr 0x20, 12 bytes)
3. `2110` - Terminal Levels (attr 0x10)
4. `1A210C` - Identify block (attr 0x21, 12 bytes)
5. `1A3E01` - Parameter area number (attr 0x3E, 1 byte)
6. `\46050900A400411000` - Extended PP: read application config from specific point
7. `1A0102` - Application list (attr 0x01, 2 bytes)
8. `1AFA2C` - Installed applications (attr 0xFA, 44 bytes)
9. `1AFB09` - Extended firmware version (attr 0xFB, 9 bytes)
10. Then a full read of all key programming blocks via extended CAL reads

The unit responds with its full configuration across multiple response packets,
including key programming, group assignments, and application configurations.
Many responses use extended CAL (0x91 prefix) with 16+ byte payloads spanning
the unit's full programming memory.

---

## C-Bus Toolkit Write Protocol (Label Change)

Captured by changing an eDLT label from "Lounge" to "Lounge2" and selecting
"Update all items on device" in the C-Bus Toolkit.

### Write Session Commands

6 commands were sent by the toolkit during the write operation:

| # | Conf | Command | Description |
|---|------|---------|-------------|
| 1 | l | `\46050900A400410000` | PP WRITE to unit 5: param 0x00, data [41 00 00] |
| 2 | m | `A400411600` | DM WRITE to CNI: param 0x00, data [41 16 00] |
| 3 | n | `\05DF000E0207EA041A...` | Clock sync: 2026-04-26 13:34:36 |
| 4 | o | `\05DF000E0207EA041A...` | Clock sync: 2026-04-26 13:35:22 |
| 5 | o | `\05DF000E0207EA041A...` | Clock sync: 2026-04-26 13:39:36 |
| 6 | p | `\05DF000E0207EA041A...` | Clock sync: 2026-04-26 13:40:22 |

### WRITE CAL Protocol

The C-Bus Toolkit uses **WRITE CAL** commands (0xA0-0xBF range) to program units.
This is the write counterpart to IDENTIFY (0x21) and RECALL (0x1A) reads.

```
WRITE CAL format:
  Header byte: 0xA0 | length   (length includes param byte + data)
  Param byte:  parameter address being written
  Data bytes:  new value to write

Example: A4 00 41 00 00
  A4 = WRITE, length=4 (4 bytes follow)
  00 = parameter address 0x00
  41 00 00 = new value (3 bytes)
```

### PP WRITE (to bus units)

Writes to a unit on the bus use PP addressing with bridge routing:

```
\46 UU 09 00 [WRITE_CAL]
  46 = PP flags (addr_type=6, priority=1)
  UU = target unit address
  09 = bridge marker (BRIDGE_LENGTHS[0x09]=0, non-bridged)
  00 = local point address (point 0)
  [WRITE_CAL] = A4 PP DD DD DD...
```

Example: `\46050900A400410000` writes to unit 5, point 0, parameter 0x00.

### DM WRITE (to CNI itself)

Writes to the CNI's own parameters use bare WRITE CAL without PP framing:

```
[WRITE_CAL]
  A4 00 41 16 00
```

No `\` prefix, no unit addressing. The CNI processes the write directly.

### Clock Sync During Writes

The toolkit sends clock sync commands (PM app 0xDF) periodically during
and after write operations. These sync the C-Bus network clock.

```
Clock SAL format (combined time+date):
  \05 DF 00 0E 02 YYYY MM DD DOW HH ?? HH MM SS FF CC
  05 = PM flags
  DF = Clock application
  00 = routing
  0E = combined time+date SAL command
  02 = sub-command (date+time)
  YYYY = year (big-endian, e.g. 07EA = 2026)
  MM = month, DD = day, DOW = day of week
  HH = hour (13 = 0x0D)
  ?? = unknown flag byte (always 0x01)
  HH MM SS = time (hour, minute, second)
  FF = terminator (0xFF)
  CC = checksum
```

### Observations

1. **Labels ARE written to the unit**: A subsequent capture with "sync changes
   only" revealed the full write sequence (see below). Labels are sent as
   DM WRITE commands to parameter 0x01 with the label text in ASCII.

2. **Two-step write**: The toolkit writes to both the target unit (PP WRITE)
   AND the CNI (DM WRITE). The CNI write may update its internal mapping
   or project state.

3. **Bridge addressing for writes**: PP WRITEs use bridge marker 0x09
   (vs 0x00 for reads). This may be required for write operations to ensure
   reliable delivery, or it may relate to the point/sub-address within
   the unit.

4. **Clock sync**: The toolkit keeps the network clock in sync, sending
   time updates approximately every 60 seconds during the session.

---

## Full eDLT Write Sequence ("Sync Changes Only")

Captured by changing a label to "Lounge4" and selecting "Sync changes only"
in the C-Bus Toolkit. This revealed the complete write protocol.

### Write Sequence (chronological)

The toolkit writes unit configuration as a series of **bare DM CAL WRITE
commands** (no PP framing), interleaving writes to parameter 0x00 (config)
and parameter 0x01 (data). This is a register-style protocol where param
0x00 selects the target address/context and param 0x01 carries the payload.

```
Phase 1: Setup
  [n] PP WRITE unit 5 [direct]: param=0x21 data=[00 38 FF]
      Set identify context: app=0x38 (Lighting), reset marker=0xFF
  [o] PP WRITE unit 5 [bridged]: param=0x00 data=[41 A0 00]
      Initialize write session for unit 5

Phase 2: Configuration writes (bare DM CAL, no PP framing)
  [p] WRITE param=0x01 data=[42 00 00 00 00 00 00 00 00 00 00 00 00]
      Clear/initialize data buffer (13 zero bytes)
  [q] WRITE param=0x00 data=[41 AC 00]
      Set write address: 0xAC (172)
  [r] WRITE param=0x01 data=[42 00 00 00 00]
      Write 4 zero bytes to address 0xAC
  [s] WRITE param=0x00 data=[41 2D 02]
      Set write address: 0x2D, context 0x02
  [t] WRITE param=0x01 data=[42 3D]
      Write 0x3D ('=') to address 0x2D
  [u] WRITE param=0x00 data=[41 60 02]
      Set write address: 0x60, context 0x02
  [v] WRITE param=0x01 data=[42 FF]
      Write 0xFF to address 0x60
  [w] WRITE param=0x00 data=[41 40 1F]
      Set write address: 0x40, context 0x1F

Phase 3: LABEL WRITE
  [x] WRITE param=0x01 data=[42 4C 6F 75 6E 67 65 34 00]
      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      Write "Lounge4" (null-terminated ASCII) to current address
      0x42 prefix = key/point identifier 'B'

Phase 4: Post-label configuration
  [y] WRITE param=0x00 data=[41 02 00]
      Set write address: 0x02
  [z] WRITE param=0x01 data=[42 96 AA]
      Write 2 bytes to address 0x02
  [g] WRITE param=0x00 data=[41 06 00]
      Set write address: 0x06
  [h] WRITE param=0x01 data=[42 E9 F7 65 09]
      Write 4 bytes to address 0x06

Phase 5: Finalize
  [i] PM ENABLE: A3 00 06 01
      Enable control command to finalize changes
  [j] IDENTIFY unit 5: attr=0x10 (terminal levels - verify write)
  [k] IDENTIFY unit 5: attr=0x04 (serial number - verify identity)
  [l] PP WRITE unit 5 [bridged]: param=0x00 data=[41 10 00]
      Final write marker
  [m-o] RECALL attrs 0x01, 0xFA, 0xFB (read back to verify)
```

### WRITE Protocol Details

#### Register-Style Addressing

The toolkit uses a two-register write protocol:

- **Parameter 0x00** (address register): Sets the target memory address
  within the unit. Data format: `41 AA CC` where AA = address, CC = context.
- **Parameter 0x01** (data register): Writes data to the previously set
  address. Data format: `42 DD DD DD...` where 0x42 is a constant prefix.

Each write operation is two commands: first set the address (param 0x00),
then write the data (param 0x01).

#### Label Encoding

Labels are written as null-terminated ASCII strings:
```
WRITE param=0x01: 42 4C 6F 75 6E 67 65 34 00
                  ^^ ^^^^^^^^^^^^^^^^^^^^^^ ^^
                  prefix  "Lounge4"         null terminator
```

The `0x42` prefix byte ('B') appears on all data writes and likely
identifies the data register or point within the unit.

#### Confirmation Flow

Each write command gets a confirmation from the CNI (`x.` = success).
The unit also sends ACKNOWLEDGE (0x32) responses via PP packets:
```
86 05 10 01 00 32 00 41 F1   (ACK for param 0x00 writes)
86 05 10 01 00 32 01 42 EF   (ACK for param 0x01 writes)
```

The ACK contains the parameter address (0x00 or 0x01) and the point
identifier (0x41 or 0x42), confirming the unit received the write.

#### Write Session Structure

1. **Initialize**: PP WRITE to set identify context and start session
2. **Bulk writes**: Series of bare DM WRITE commands (address + data pairs)
3. **Finalize**: Enable control command + verification reads
4. **Verify**: IDENTIFY/RECALL to read back written configuration

# C-Bus Protocol Analyzer & Proxy

The C-Bus proxy is a transparent interceptor that sits between cmqttd and your real CNI (C-Bus Network Interface), logging and analyzing all communication in both directions.

## Features

- **Transparent Proxy**: Acts exactly like a CNI, forwarding all commands and responses
- **Multi-Client Support**: Multiple applications can connect simultaneously and all receive CNI responses
- **Detailed Packet Analysis**: Breaks down each packet and explains its contents
- **Colored Output**: Easy-to-read colored terminal output for different packet types
- **Confirmation Tracking**: Tracks confirmation codes and matches them to commands
- **Session Statistics**: Provides summary of packets processed and errors encountered
- **Real-time Monitoring**: See exactly what's happening on your C-Bus network
- **Client Identification**: Each client connection is tagged in the logs for easy tracking

## Architecture

### Single CNI, Multiple Clients
```
┌─────────┐                              
│ Client 1│─┐                           
└─────────┘ │    TCP    ┌───────────┐     TCP      ┌─────────┐
┌─────────┐ ├──────────▶│   Proxy   │ ────────────▶│   CNI   │
│ Client 2│─┤◀──────────│           │◀──────────── │         │
└─────────┘ │           └───────────┘              └─────────┘
┌─────────┐ │                 │
│ Client N│─┘                 ▼
└─────────┘             Detailed Logs
```

The proxy maintains a single connection to the CNI and broadcasts all CNI responses to every connected client. This allows multiple cmqttd instances or other C-Bus applications to monitor the same network simultaneously.

## Quick Start

### Using Docker Compose (with cmqttd)

From the parent directory:

1. Set up your environment variables:
   ```bash
   # Edit .env file
   CNI_HOST=192.168.1.100  # Your real CNI IP address
   CNI_PORT=10001          # Your real CNI port (default: 10001)
   ```

2. Start the proxy and cmqttd:
   ```bash
   cd cbus-proxy
   docker-compose up
   ```

### Using Docker (Standalone Proxy)

From this directory:

1. Build and run the standalone proxy:
   ```bash
   # Set your CNI address
   export CNI_HOST=192.168.1.100
   export CNI_PORT=10001
   
   # Run with docker-compose
   docker-compose -f docker-compose.standalone.yml up
   ```

Or manually:

```bash
# Build the image
docker build -f Dockerfile.standalone -t cbus-proxy .

# Run the proxy
docker run -it --rm \
  -p 10001:10001 \
  cbus-proxy \
  --target-host 192.168.1.100 \
  --target-port 10001
```

### Using Python Directly

From this directory:

```bash
# Run the convenience script
./run-proxy.sh 192.168.1.100

# Or manually from the parent directory
cd ..
python -m cbus-proxy --target-host 192.168.1.100 --target-port 10001
```

## Command Line Options

```
usage: python -m cbus-proxy [-h] [--listen-host LISTEN_HOST] [--listen-port LISTEN_PORT]
                           --target-host TARGET_HOST [--target-port TARGET_PORT]

C-Bus Protocol Analyzer and Proxy

options:
  -h, --help            show this help message and exit
  --listen-host LISTEN_HOST
                        Host to listen on (default: 0.0.0.0)
  --listen-port LISTEN_PORT
                        Port to listen on (default: 10001)
  --target-host TARGET_HOST
                        Target CNI host/IP
  --target-port TARGET_PORT
                        Target CNI port (default: 10001)
```

## Understanding the Output

### Packet Header

Each packet is numbered and shows the direction:
- `CLIENT→CNI`: Commands from cmqttd to the CNI
- `CNI→CLIENT`: Responses from CNI to cmqttd

### Raw Data Display

Shows the hex representation and ASCII interpretation:
```
5C 30 35 46 46 33 38 30 30 37 39 36 34 67 0D    | \05FF38007964g.
```

### Packet Analysis

The proxy decodes and explains each packet type:

#### Example: Lighting ON Command with Client Identification
```
━━━ Packet #1 CLIENT→CNI [Client(192.168.1.10:54321)] ━━━
Raw Data:
5C 30 35 46 46 33 38 30 30 37 39 36 34 67 0D    | \05FF38007964g.

Packet Type: PointToMultipointPacket
Source Address: 255 (0xFF)
Confirmation Code: 103 (0x67, 'g')
━━ Lighting ON Command ━━
  Application: Lighting App 38
  Group: 100 (0x64)
```

#### Example: Confirmation Response
```
━━━ Packet #2 CNI→CLIENT ━━━
Raw Data:
67 2E                                            | g.

Packet Type: ConfirmationPacket
Confirmation Code: 103 (0x67, 'g')
Status: SUCCESS
Confirms: Light ON Group 100 (sent 0.023s ago)
```

#### Example: Level Status Report
```
━━ Level Status Report ━━
  Application: Lighting App 38
  Block Start: Group 64 (0x40)
  Levels:
    Group  64: 255 (0xFF) = 100.0%
    Group  65:   0 (0x00) =   0.0%
    Group  66: 128 (0x80) =  50.2%
```

### Color Coding

- **Cyan**: Client to CNI packets
- **Yellow**: CNI to client packets
- **Green**: Successful operations
- **Red**: Errors or failures
- **Magenta**: Important fields
- **Blue**: Raw data

## Use Cases

### Debugging C-Bus Issues

1. See exactly what commands are being sent
2. Verify confirmations are received
3. Check timing between commands and responses
4. Identify communication errors

### Protocol Learning

1. Understand C-Bus packet structure
2. See how different commands are encoded
3. Learn the confirmation system
4. Analyze status reports

### Development

1. Test new C-Bus implementations
2. Verify command formatting
3. Debug timing issues
4. Analyze protocol behavior

## Session Summary

At the end of a session (Ctrl+C), the proxy displays statistics:
```
━━━ Session Summary ━━━
Total Packets: 157
Errors: 2
Unconfirmed Commands: 1
  - Light ON Group 50 (code 104, waiting 45.2s)

━━━ Client Statistics ━━━
Total clients served: 3
```

## Troubleshooting

### Connection Refused
- Verify the CNI IP address and port are correct
- Check network connectivity to the CNI
- Ensure no firewall is blocking the connection

### Packet Decode Errors
- The proxy will display the raw data even if decoding fails
- Check for protocol version mismatches
- Verify the CNI is operating correctly

### Missing Confirmations
- Some commands may not require confirmation
- Check the session summary for unconfirmed commands
- Network issues may cause confirmations to be lost

## Integration with Existing Setup

To use the proxy with your existing cmqttd setup:

1. Note your current CNI connection settings
2. Start the proxy pointing to your real CNI
3. Update cmqttd to connect to the proxy instead
4. All functionality remains the same, with added logging

The proxy is completely transparent - cmqttd won't know it's connected to a proxy instead of the real CNI.

## File Structure

```
cbus-proxy/
├── README.md               # This file
├── __init__.py            # Package initialization
├── __main__.py            # Module entry point
├── proxy.py               # Main proxy implementation
├── run-proxy.sh           # Convenience run script
├── Dockerfile             # Docker image (requires parent context)
├── Dockerfile.standalone  # Standalone Docker image
├── docker-compose.yml     # Full setup with cmqttd
└── docker-compose.standalone.yml  # Proxy only
```

## Multi-Client Usage

The proxy now supports multiple simultaneous client connections. This is useful for:

1. **Multiple cmqttd Instances**: Run multiple MQTT bridges for redundancy
2. **Monitoring Tools**: Connect diagnostic tools while cmqttd is running
3. **Development**: Test multiple applications against the same C-Bus network
4. **Load Distribution**: Spread processing across multiple client applications

### Connection Management

- The proxy maintains a persistent connection to the CNI
- Clients can connect and disconnect at any time
- All connected clients receive all CNI responses
- Each client's commands are forwarded to the CNI
- Client connections are logged with their address for identification

### Example Multi-Client Setup

```bash
# Terminal 1: Start the proxy
./run-proxy.sh 192.168.1.100

# Terminal 2: Connect cmqttd
docker run --rm -it cmqttd --tcp-addr=localhost --tcp-port=10001

# Terminal 3: Connect a monitoring tool
python -m cbus.tools.monitor --tcp-addr=localhost --tcp-port=10001

# Terminal 4: Connect another cmqttd instance
docker run --rm -it cmqttd --tcp-addr=localhost --tcp-port=10001
```

All three clients will receive the same CNI responses, and the proxy logs will show which client sent each command. 
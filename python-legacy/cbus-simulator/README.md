# C-Bus Simulator

> ⚠️ **Work-in-progress:** Parsing and state-management internals are still evolving. APIs may change without notice while convergence with the main `cbus` project continues.

A Python-based simulator for testing C-Bus PCI (Protocol Control Interface) applications without actual C-Bus hardware.

## Overview

This simulator emulates a Clipsal C-Bus 5500CN Ethernet PCI on port 10001 (by default), allowing software development and testing without physical C-Bus hardware.

## Features

- Simulates basic C-Bus lighting commands
- Can be run standalone or in Docker
- Configurable via JSON configuration file
- Supports testing with example clients
- Implements C-Bus protocol commands and responses including proper confirmation handling

## Protocol Notes

### C-Bus Confirmation Protocol

The C-Bus protocol includes a confirmation mechanism for commands that works as follows:

1. When a client sends a command requiring confirmation, it appends a specific ASCII character as a confirmation code to the end of the command.
2. Valid confirmation codes are the characters in the set: `hijklmnopqrstuvwxyzg`
3. The server responds with:
   - The same confirmation code character
   - A status indicator (`.` for success, `!` for failure)
   - Followed by the command terminator (CR+LF)

For example, if a client sends a command ending with the confirmation code `h`, and the command succeeds, the server responds with:
- The ASCII characters: `h.` followed by CR+LF

This allows clients to match responses to the commands they sent, even in an asynchronous communication environment. The limited set of confirmation codes (20 characters) means that in high-traffic environments, codes may need to be reused, requiring proper tracking of which codes are in use at any given time.

## Getting Started

### Running Locally

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the simulator:
   ```
   python run_simulator.py
   ```

   Optional parameters:
   ```
   python run_simulator.py --port 10001 --host 0.0.0.0 --config config/simulator-config.json --verbose
   ```

### Running with Docker

1. Build and start the container:
   ```
   docker-compose up -d
   ```

2. View logs:
   ```
   docker logs -f cbus-simulator
   ```

## Configuration

Configure the simulator using the JSON configuration file located at `config/simulator-config.json`.

Example configuration:
```json
{
  "device": {
    "serial_number": "00000000",
    "type": "5500CN",
    "firmware_version": "1.0.0"
  },
  "networks": [
    {
      "network_id": 254,
      "name": "Default Network",
      "applications": [
        {
          "application_id": 56,
          "type": "lighting",
          "groups": [
            {"group_id": 1, "name": "Living Room"},
            {"group_id": 2, "name": "Kitchen"}
          ]
        }
      ]
    }
  ]
}
```

## Testing

Run the included tests to verify functionality:

```
python -m unittest discover tests
```

## License

This project is licensed under the GNU LGPL3+ License - see the LICENSE file for details. 
# C-Bus Simulator

A Python-based simulator for testing C-Bus PCI (Protocol Control Interface) applications without actual C-Bus hardware.

## Overview

This simulator emulates a Clipsal C-Bus 5500CN Ethernet PCI on port 10001 (by default), allowing software development and testing without physical C-Bus hardware.

## Features

- Simulates basic C-Bus lighting commands
- Can be run standalone or in Docker
- Configurable via JSON configuration file
- Supports testing with example clients

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
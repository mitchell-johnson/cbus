# C-Bus Library Documentation Index

## Overview

This documentation provides a comprehensive analysis of the C-Bus library (libcbus), a pure Python implementation for interfacing with Clipsal C-Bus home automation systems. The library enables communication with C-Bus networks without proprietary dependencies and includes an MQTT bridge for integration with modern home automation platforms like Home Assistant.

## Documentation Structure

### Core Documentation

#### 1. [Comprehensive Architecture Documentation](COMPREHENSIVE_ARCHITECTURE.md)
This document provides a complete overview of the library architecture, including:
- System components and their relationships
- Protocol stack layers
- Core component descriptions
- Security and reliability features
- Configuration options

#### 2. [Detailed Flow Diagrams](DETAILED_FLOW_DIAGRAMS.md)
Visual representations of system behavior through:
- System initialization sequences
- Packet processing flows
- Command execution patterns
- Event handling mechanisms
- Error recovery procedures
- Integration workflows

#### 3. [Protocol Deep Dive](PROTOCOL_DEEP_DIVE.md)
Technical analysis of the C-Bus protocol implementation:
- Packet structure analysis
- Command encoding details
- Application layer protocols
- Confirmation system mechanics
- Buffer management strategies
- State machine implementations

### Reference Documentation

#### 4. [API Reference](API_REFERENCE.md) ✨ NEW
Complete API documentation including:
- Core Protocol (PCIProtocol class)
  - Constructor parameters
  - All public methods with examples
  - Event handlers
- MQTT Gateway (CBusHandler, MqttClient)
- Packet Types (PM, PP, Confirmation, etc.)
- Application protocols (Lighting, Clock, Temperature)
- Common utilities and helper functions
- Type hints reference
- Complete working examples

#### 5. [Code Review - Detailed Analysis](CODE_REVIEW_DETAILED.md) ✨ NEW
Comprehensive code review covering:
- Code quality analysis and metrics
- Potential bugs and issues (Critical, Medium, Low priority)
- Testing analysis and coverage gaps
- Documentation inconsistencies
- Security considerations
- Performance analysis
- Specific file-level issues
- Recommendations priority matrix
- Overall assessment and grading

### User Guides

#### 6. [Troubleshooting Guide](TROUBLESHOOTING.md) ✨ NEW
Detailed troubleshooting for common issues:
- Connection problems (CNI/PCI, Serial, Network)
- MQTT issues (Broker connection, Home Assistant integration)
- Command failures and confirmations
- Performance issues (latency, memory, CPU)
- Docker-specific problems
- Debugging tools and techniques
- Common error messages explained

### Developer Documentation

#### 7. [Contributing Guide](CONTRIBUTING.md) ✨ NEW
Guidelines for contributing to the project:
- Development environment setup
- Code style guide and conventions
- Type hints and docstring requirements
- Testing requirements and examples
- Documentation standards
- Pull request process
- Release process (for maintainers)
- Community guidelines

## Quick Start Guide

### Installation

```bash
# Clone the repository
git clone https://github.com/mitchell-johnson/cbus.git
cd cbus

# Install dependencies
pip install -r requirements.txt

# For testing
pip install -r requirements-tests.txt
```

### Docker Deployment

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env with your settings

# Start the container
docker-compose up -d
```

### Basic Usage

For detailed examples, see the [API Reference](API_REFERENCE.md).

```python
# Example: Control a light via C-Bus
from cbus.protocol.pciprotocol import PCIProtocol
from cbus.common import Application

async def control_light():
    # Create protocol instance
    protocol = PCIProtocol()

    # Turn on light at group address 1
    await protocol.lighting_group_on(1, Application.LIGHTING)

    # Dim light to 50% over 4 seconds
    await protocol.lighting_group_ramp(1, Application.LIGHTING, 4, 128)

    # Turn off light
    await protocol.lighting_group_off(1, Application.LIGHTING)
```

For troubleshooting, see the [Troubleshooting Guide](TROUBLESHOOTING.md).

## Key Concepts

### 1. **Protocol Layers**
- **Transport**: Serial/TCP communication
- **Protocol**: C-Bus packet encoding/decoding
- **Application**: Lighting, clock, temperature control
- **Integration**: MQTT bridge for home automation

### 2. **Packet Types**
- **PM (Point-to-Multipoint)**: Broadcast messages
- **PP (Point-to-Point)**: Direct device communication
- **Confirmation**: Command acknowledgments
- **Status**: Device state queries

### 3. **Applications**
- **Lighting (0x30-0x5F)**: Light control with dimming
- **Clock (0xDF)**: Time synchronization
- **Temperature (0x19)**: Climate control
- **Status (0xFF)**: State queries

### 4. **MQTT Integration**
- Home Assistant auto-discovery
- JSON command schema
- State synchronization
- Binary sensor support

## Architecture Highlights

### System Flow
```
C-Bus Device → PCI Hardware → libcbus → MQTT → Home Assistant
```

### Key Components

1. **PCIProtocol**: Core protocol handler
   - Connection management
   - Packet processing
   - Confirmation handling
   - Event dispatching

2. **cmqttd**: MQTT bridge daemon
   - C-Bus to MQTT translation
   - Home Assistant integration
   - State synchronization
   - Device discovery

3. **Packet System**: Modular packet handling
   - Type-specific decoders
   - Checksum validation
   - Buffer management
   - Error recovery

### Reliability Features

1. **Confirmation System**
   - Automatic retry (3 attempts)
   - Timeout handling (30s default)
   - Code pool management

2. **Connection Management**
   - Automatic reconnection
   - State cleanup
   - Memory leak prevention

3. **Synchronization**
   - Periodic state sync (300s default)
   - Clock synchronization
   - Missed event recovery

## Performance Characteristics

- **Latency**: < 200ms typical end-to-end
- **Throughput**: 10 commands/second (configurable)
- **Memory**: Efficient buffer management
- **Scalability**: Supports 256 groups per application

## Development Guidelines

### Code Structure
```
cbus/
├── protocol/          # Protocol implementation
│   ├── application/   # App-specific protocols
│   ├── cal/          # Common Application Language
│   └── *.py          # Packet types
├── daemon/           # MQTT bridge
├── toolkit/          # Utilities
└── common.py         # Constants and helpers
```

### Testing
```bash
# Run tests
pytest

# With coverage
pytest --cov=cbus
```

### Contributing

See the [Contributing Guide](CONTRIBUTING.md) for detailed information on:
1. Development environment setup
2. Code style guidelines (PEP 8 with modifications)
3. Type hints and docstring requirements
4. Testing requirements and examples
5. Documentation standards
6. Pull request process
7. Release process (for maintainers)

## Troubleshooting

For comprehensive troubleshooting information, see the [Troubleshooting Guide](TROUBLESHOOTING.md).

### Quick Diagnostics

1. **Connection failures** → See [Connection Issues](TROUBLESHOOTING.md#connection-issues)
2. **MQTT issues** → See [MQTT Problems](TROUBLESHOOTING.md#mqtt-problems)
3. **Command failures** → See [Command Failures](TROUBLESHOOTING.md#command-failures)
4. **Performance issues** → See [Performance Issues](TROUBLESHOOTING.md#performance-issues)
5. **Docker problems** → See [Docker Issues](TROUBLESHOOTING.md#docker-issues)

### Debug Logging

```bash
# Enable debug logging
export CMQTTD_VERBOSITY=DEBUG
```

For more debugging tools, see [Debugging Tools](TROUBLESHOOTING.md#debugging-tools).

## References

- [C-Bus Protocol Documentation](https://updates.clipsal.com/ClipsalSoftwareDownload/DL/downloads/OpenCBus/OpenCBusProtocolDownloads.html)
- [Home Assistant MQTT Light](https://www.home-assistant.io/integrations/light.mqtt/)
- [Project Repository](https://github.com/mitchell-johnson/cbus)

## Documentation Quick Links

### For Users
- **Getting Started**: See [Quick Start Guide](#quick-start-guide) above
- **Using the API**: [API Reference](API_REFERENCE.md)
- **Having Problems?**: [Troubleshooting Guide](TROUBLESHOOTING.md)
- **Understanding the System**: [Comprehensive Architecture](COMPREHENSIVE_ARCHITECTURE.md)

### For Developers
- **Want to Contribute?**: [Contributing Guide](CONTRIBUTING.md)
- **Understanding the Code**: [Code Review](CODE_REVIEW_DETAILED.md)
- **Protocol Details**: [Protocol Deep Dive](PROTOCOL_DEEP_DIVE.md)
- **System Flows**: [Detailed Flow Diagrams](DETAILED_FLOW_DIAGRAMS.md)

### For Maintainers
- **Code Quality**: [Code Review Analysis](CODE_REVIEW_DETAILED.md)
- **Release Process**: [Contributing Guide - Release Process](CONTRIBUTING.md#release-process)

## Summary

The C-Bus library provides a robust, pure-Python solution for C-Bus integration. Its architecture emphasizes:

- **Reliability** through retry mechanisms and state synchronization
- **Performance** via async operations and efficient buffering
- **Extensibility** with modular packet handling
- **Integration** through MQTT and Home Assistant support

The comprehensive documentation provided here offers deep insights into the implementation details, architectural decisions, and operational characteristics of the system.

### Documentation Statistics

| Category | Documents | Status |
|----------|-----------|--------|
| **Core Architecture** | 3 | ✅ Complete |
| **Reference** | 2 | ✅ Complete |
| **User Guides** | 1 | ✅ Complete |
| **Developer Guides** | 1 | ✅ Complete |
| **Total** | **7** | **All Complete** |

**Last Updated:** 2025-10-22 
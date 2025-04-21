# CBus Simulator

This document explains how to use the CBus simulator which has been separated from the main service.

## Files Structure

- `docker-compose.yml` - Contains the configuration for the main CBus service
- `docker-compose.simulator.yml` - Contains the configuration for the simulator service
- `run-services.sh` - Helper script to manage both services

## Using the Simulator

The simulator has been set up to run independently from the main service, but can still communicate with it through the network.

### Starting and Stopping Services

You can use the provided `run-services.sh` script to manage both services:

```bash
# Start both services
./run-services.sh start

# Start only the main service
./run-services.sh main

# Start only the simulator
./run-services.sh simulator

# Stop all services
./run-services.sh stop

# Restart all services
./run-services.sh restart
```

### Simulator Configuration

The simulator is configured with the following settings:

- MQTT Server: 192.168.1.32
- CNI Address: 192.168.1.21:10001
- CBus Network: Home
- TLS Disabled (MQTT_USE_TLS=0)
- Simulator Port: 10001

If you need to change any of these settings, edit the `docker-compose.simulator.yml` file.

## Troubleshooting

If you encounter issues with the simulator:

1. Check logs using: `docker-compose -f docker-compose.simulator.yml logs cbus-simulator`
2. Ensure the main service is running if you're trying to communicate between them
3. Verify that ports are not already in use (especially 10001)

## Customizing the Simulator

The simulator uses a configuration file at `config/simulator-config.json`. Edit this file to change the simulated devices, networks, and applications. 
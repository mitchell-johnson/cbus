#!/bin/bash

# Default values
SIMULATOR_PORT=${SIMULATOR_PORT:-10001}
CONFIG_FILE=${CONFIG_FILE:-/app/config/simulator-config.json}

echo "Starting C-Bus Simulator with configuration:"
echo "  Port: $SIMULATOR_PORT"
echo "  Config file: $CONFIG_FILE"

# Run the Python simulator
exec python /app/run_simulator.py --port $SIMULATOR_PORT --config $CONFIG_FILE

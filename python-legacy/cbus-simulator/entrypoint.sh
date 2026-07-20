#!/bin/bash

# Default values
SIMULATOR_PORT=${SIMULATOR_PORT:-10001}
CONFIG_FILE=${CONFIG_FILE:-/app/config/simulator-config.json}
VERBOSE=${VERBOSE:-false}

echo "Starting C-Bus Simulator with configuration:"
echo "  Port: $SIMULATOR_PORT"
echo "  Config file: $CONFIG_FILE"
echo "  Verbose logging: $VERBOSE"

# Prepare verbose flag if enabled
VERBOSE_FLAG=""
if [ "$VERBOSE" = "true" ]; then
    VERBOSE_FLAG="--verbose"
fi

# Run the Python simulator with appropriate options
exec python /app/run_simulator.py --port $SIMULATOR_PORT --config $CONFIG_FILE $VERBOSE_FLAG

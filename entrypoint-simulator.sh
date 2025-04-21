#!/bin/sh

# Set default values for required variables
SIMULATOR_PORT=${SIMULATOR_PORT:-10001}
SIMULATOR_CONFIG=${SIMULATOR_CONFIG:-/app/config/simulator-config.json}
BIND_ADDRESS="0.0.0.0"

# Print configuration
echo "Starting C-Bus simulator"
echo "Simulator port: ${SIMULATOR_PORT}"
echo "Simulator config: ${SIMULATOR_CONFIG}"
echo "Binding to: ${BIND_ADDRESS}:${SIMULATOR_PORT}"

# Create a simple TCP server that listens on the specified port
# This is a placeholder for the actual simulator implementation
# You would replace this with your own simulator code

# Start the simulator
echo "Simulator listening on ${BIND_ADDRESS}:${SIMULATOR_PORT}"
nc -l -p ${SIMULATOR_PORT} -k

# Keep the container running
exec "$@" 
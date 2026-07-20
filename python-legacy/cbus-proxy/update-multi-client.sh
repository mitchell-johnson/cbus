#!/bin/bash
# Quick update script for multi-client proxy update

echo "Updating C-Bus Proxy to multi-client version..."
echo "=============================================="
echo ""

# Stop any running proxy
echo "Stopping existing proxy containers..."
docker-compose -f docker-compose.yml down 2>/dev/null
docker-compose -f docker-compose.standalone.yml down 2>/dev/null

# Rebuild the image
echo "Rebuilding proxy image..."
docker build -f Dockerfile.standalone -t cbus-proxy-standalone .

# Start the proxy
echo "Starting multi-client proxy..."
docker run -it --rm \
  --name cbus-proxy \
  -p 10001:10001 \
  -e CNI_HOST=${CNI_HOST:-192.168.1.100} \
  -e CNI_PORT=${CNI_PORT:-10001} \
  cbus-proxy-standalone \
  --target-host ${CNI_HOST:-192.168.1.100} \
  --target-port ${CNI_PORT:-10001} 
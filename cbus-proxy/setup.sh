#!/bin/bash
# Setup script for C-Bus Proxy

echo "C-Bus Proxy Setup"
echo "================="
echo ""

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cat > .env << 'EOF'
# C-Bus Proxy Configuration
# Update these settings to match your CNI

# Target CNI Configuration
CNI_HOST=192.168.1.100    # IP address of your real CNI
CNI_PORT=10001            # Port of your real CNI (default: 10001)

# Proxy Configuration (optional)
PROXY_PORT=10001          # Port for the proxy to listen on
EOF
    echo "Created .env file. Please edit it with your CNI settings."
else
    echo ".env file already exists."
fi

echo ""
echo "Next steps:"
echo "1. Edit .env file with your CNI IP address and port"
echo "2. Run: docker-compose -f docker-compose.standalone.yml up"
echo "   Or for full setup with cmqttd: docker-compose up" 
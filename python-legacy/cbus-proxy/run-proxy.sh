#!/bin/bash
# run-proxy.sh - Start the C-Bus Protocol Analyzer Proxy

# Default values
DEFAULT_LISTEN_HOST="0.0.0.0"
DEFAULT_LISTEN_PORT="10001"
DEFAULT_TARGET_PORT="10001"

# Check if target host is provided
if [ -z "$1" ]; then
    echo "Usage: $0 TARGET_HOST [TARGET_PORT] [LISTEN_PORT]"
    echo ""
    echo "Example:"
    echo "  $0 192.168.1.100              # Uses default ports (10001)"
    echo "  $0 192.168.1.100 10001 10002  # Custom ports"
    echo ""
    echo "Environment variables:"
    echo "  CNI_HOST     - Target CNI host (alternative to command line)"
    echo "  CNI_PORT     - Target CNI port (default: 10001)"
    echo "  PROXY_PORT   - Proxy listen port (default: 10001)"
    exit 1
fi

# Get parameters from command line or environment
TARGET_HOST="${1:-$CNI_HOST}"
TARGET_PORT="${2:-${CNI_PORT:-$DEFAULT_TARGET_PORT}}"
LISTEN_PORT="${3:-${PROXY_PORT:-$DEFAULT_LISTEN_PORT}}"

# Ensure we're in the right directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if running in Docker or native Python
if [ -f /.dockerenv ]; then
    # Running in Docker
    python -m cbus-proxy.proxy \
        --listen-host "$DEFAULT_LISTEN_HOST" \
        --listen-port "$LISTEN_PORT" \
        --target-host "$TARGET_HOST" \
        --target-port "$TARGET_PORT"
else
    # Running natively - check if we need to go to parent directory
    if [ ! -d "../cbus" ]; then
        echo "Error: Cannot find cbus library. Make sure you're running from the cbus-proxy directory."
        exit 1
    fi
    
    # Go to parent directory where cbus library is
    cd ..
    
    # Check for virtual environment
    if [ -d ".venv" ]; then
        echo "Activating virtual environment..."
        source .venv/bin/activate
    elif [ -d "venv" ]; then
        echo "Activating virtual environment..."
        source venv/bin/activate
    fi
    
    # Check if colorama is installed
    if ! python -c "import colorama" 2>/dev/null; then
        echo "Installing colorama for colored output..."
        pip install colorama
    fi
    
    # Check if cbus is installed
    if ! python -c "import cbus" 2>/dev/null; then
        echo "Installing cbus library..."
        pip install -e .
    fi
    
    # Run the proxy
    echo "Starting C-Bus Protocol Analyzer Proxy..."
    echo "Listening on: $DEFAULT_LISTEN_HOST:$LISTEN_PORT"
    echo "Forwarding to: $TARGET_HOST:$TARGET_PORT"
    echo ""
    
    python -m cbus-proxy.proxy \
        --listen-host "$DEFAULT_LISTEN_HOST" \
        --listen-port "$LISTEN_PORT" \
        --target-host "$TARGET_HOST" \
        --target-port "$TARGET_PORT"
fi 
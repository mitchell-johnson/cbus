#!/bin/bash

# Function to display help
function show_help {
  echo "Usage: ./run-services.sh [OPTIONS] COMMAND"
  echo ""
  echo "Commands:"
  echo "  start       Start both the main service and simulator"
  echo "  stop        Stop both services"
  echo "  restart     Restart both services"
  echo "  main        Start only the main cbus service"
  echo "  simulator   Start only the simulator service"
  echo ""
  echo "Options:"
  echo "  -h, --help  Show this help message"
}

# Start the main service
function start_main {
  echo "Starting the main cbus service..."
  docker-compose up -d
}

# Start the simulator service
function start_simulator {
  echo "Starting the simulator service..."
  docker-compose -f docker-compose.simulator.yml up -d
}

# Stop the main service
function stop_main {
  echo "Stopping the main cbus service..."
  docker-compose down
}

# Stop the simulator service
function stop_simulator {
  echo "Stopping the simulator service..."
  docker-compose -f docker-compose.simulator.yml down
}

# Process command line arguments
if [ $# -eq 0 ]; then
  show_help
  exit 0
fi

case "$1" in
  -h|--help)
    show_help
    exit 0
    ;;
  start)
    start_main
    start_simulator
    ;;
  stop)
    stop_simulator
    stop_main
    ;;
  restart)
    stop_simulator
    stop_main
    start_main
    start_simulator
    ;;
  main)
    start_main
    ;;
  simulator)
    start_simulator
    ;;
  *)
    echo "Unknown command: $1"
    show_help
    exit 1
    ;;
esac

exit 0 
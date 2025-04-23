#!/usr/bin/env python3
"""
C-Bus Simulator Server

This module implements a TCP server that mimics a C-Bus PCI Ethernet interface.
It accepts connections from clients and processes C-Bus commands.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Dict, List, Optional

from simulator.protocol import PCISimulatorProtocol
from simulator.state import SimulatorState

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Default values - use port 10002 for local testing to avoid conflicts with Docker
DEFAULT_PORT = int(os.environ.get('SIMULATOR_PORT', 10002))

# Use a flexible config file path for different environments
if os.path.exists('/app/config/simulator-config.json'):
    DEFAULT_CONFIG_PATH = '/app/config/simulator-config.json'  # Docker path
elif os.path.exists('config/simulator-config.json'):
    DEFAULT_CONFIG_PATH = 'config/simulator-config.json'  # Local path
else:
    DEFAULT_CONFIG_PATH = os.environ.get('CONFIG_FILE', 'config/simulator-config.json')

class CBusSimulatorServer:
    """
    A TCP server that simulates a C-Bus PCI interface.
    """
    
    def __init__(self, host: str = '0.0.0.0', port: int = DEFAULT_PORT, config_path: Optional[str] = DEFAULT_CONFIG_PATH):
        """
        Initialize the C-Bus simulator server.
        
        Args:
            host: The host address to bind to
            port: The port to listen on
            config_path: Path to the simulator configuration file
        """
        self.host = host
        self.port = port
        self.config_path = config_path
        self.server = None
        self.clients: List[PCISimulatorProtocol] = []
        self.state = SimulatorState()
        
        # Load configuration if provided
        if config_path:
            self.load_configuration(config_path)
    
    def load_configuration(self, config_path: str) -> None:
        """
        Load configuration from a JSON file.
        
        Args:
            config_path: Path to the configuration file
        """
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                # Apply configuration to the simulator state
                logger.info(f"Loading configuration from {config_path}")
                self.state.apply_configuration(config)
                logger.info("Configuration loaded successfully")
            else:
                logger.warning(f"Configuration file not found: {config_path}")
                logger.info("Using default configuration")
                # Default configuration is automatically applied by SimulatorState
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
    
    async def start(self) -> None:
        """
        Start the simulator server.
        """
        try:
            self.server = await asyncio.start_server(
                self.handle_client,
                self.host,
                self.port
            )
            
            logger.info(f"C-Bus Simulator server started on {self.host}:{self.port}")
            
            # Setup signal handlers for graceful shutdown
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_event_loop().add_signal_handler(
                    sig, lambda: asyncio.create_task(self.shutdown())
                )
            
            async with self.server:
                await self.server.serve_forever()
        except OSError as e:
            if e.errno == 48:  # Address already in use
                logger.error(f"Port {self.port} is already in use. Try using a different port.")
                # Try a different port
                new_port = self.port + 1
                logger.info(f"Attempting to start server on port {new_port}...")
                self.port = new_port
                await self.start()
            else:
                logger.error(f"Server error: {e}")
                await self.shutdown()
        except Exception as e:
            logger.error(f"Server error: {e}")
            await self.shutdown()
    
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """
        Handle a new client connection.
        
        Args:
            reader: Stream reader for client data
            writer: Stream writer for sending data to client
        """
        addr = writer.get_extra_info('peername')
        logger.info(f"New client connection from {addr}")
        
        # Create a protocol handler for this client
        protocol = PCISimulatorProtocol(reader, writer, self.state)
        self.clients.append(protocol)
        
        try:
            await protocol.process_client()
        except Exception as e:
            logger.error(f"Error handling client {addr}: {e}")
        finally:
            # Clean up when client disconnects
            if protocol in self.clients:
                self.clients.remove(protocol)
            
            logger.info(f"Client {addr} disconnected")
            writer.close()
            await writer.wait_closed()
    
    async def shutdown(self) -> None:
        """
        Gracefully shut down the server.
        """
        logger.info("Shutting down C-Bus Simulator server...")
        
        # Close all client connections
        for client in self.clients:
            client.writer.close()
        
        # Close server
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        logger.info("Server shutdown complete")
        asyncio.get_event_loop().stop()

async def main() -> None:
    """
    Main entry point for the C-Bus simulator.
    """
    # Get configuration from environment variables
    port = int(os.environ.get('SIMULATOR_PORT', DEFAULT_PORT))
    config_path = os.environ.get('SIMULATOR_CONFIG', DEFAULT_CONFIG_PATH)
    
    # Create and start the server
    server = CBusSimulatorServer(port=port, config_path=config_path)
    await server.start()

if __name__ == "__main__":
    asyncio.run(main()) 
#!/usr/bin/env python3
"""
C-Bus Simulator Runner

A simple script to run the C-Bus simulator with command-line options.
"""

import argparse
import asyncio
import os
import sys
import logging
from simulator.server import CBusSimulatorServer

def setup_logging(verbose=False):
    """Set up logging with appropriate level"""
    # Check for environment variable override
    env_log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    
    # Map string log level to logging constants
    log_level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    
    # Determine log level from environment or verbose flag
    if verbose:
        log_level = logging.DEBUG
    else:
        log_level = log_level_map.get(env_log_level, logging.INFO)
    
    # Configure colorized logging if available
    try:
        import colorlog
        
        handler = colorlog.StreamHandler()
        handler.setFormatter(colorlog.ColoredFormatter(
            '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        ))
        
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.handlers = []  # Remove existing handlers
        root_logger.addHandler(handler)
        
        # Print log level being used
        print(f"Logging configured with level: {logging.getLevelName(log_level)}")
        
    except ImportError:
        # Fall back to standard logging
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        print(f"Logging configured with level: {logging.getLevelName(log_level)}")

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='C-Bus Simulator')
    
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=int(os.environ.get('SIMULATOR_PORT', 10001)),
        help='TCP port to listen on (default: 10001)'
    )
    
    parser.add_argument(
        '--host', '-H',
        type=str,
        default=os.environ.get('SIMULATOR_HOST', '0.0.0.0'),
        help='Host address to bind to (default: 0.0.0.0)'
    )
    
    parser.add_argument(
        '--config', '-c',
        type=str,
        help='Path to configuration file'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    return parser.parse_args()

async def main():
    """Main entry point"""
    args = parse_args()
    
    # Set up logging
    setup_logging(args.verbose)
    
    # Create and start the server
    server = CBusSimulatorServer(
        host=args.host,
        port=args.port,
        config_path=args.config
    )
    
    try:
        await server.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await server.shutdown()

if __name__ == "__main__":
    # Entry point for `python run_simulator.py` usage
    try:
        from asyncio import run as _arun
        _arun(main())
    except KeyboardInterrupt:
        print("\nExited by user")
        sys.exit(0)

# Provide synchronous wrapper for console_scripts
def cli():
    """Wrapper used by the setuptools console
aUTO-generated entry point."""
    try:
        from asyncio import run as _arun
        _arun(main())
    except KeyboardInterrupt:
        print("\nExited by user") 
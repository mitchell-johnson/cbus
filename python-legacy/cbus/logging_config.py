#!/usr/bin/env python
# cbus/logging_config.py - Centralized logging configuration for C-Bus
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
"""
Centralized logging configuration for the C-Bus library.

This module provides a unified way to configure logging across all C-Bus
components using the CMQTTD_VERBOSITY environment variable.
"""

import logging
import os
import sys

# Valid log levels
VALID_LOG_LEVELS = {
    'CRITICAL': logging.CRITICAL,
    'ERROR': logging.ERROR,
    'WARNING': logging.WARNING,
    'INFO': logging.INFO,
    'DEBUG': logging.DEBUG
}

def configure_logging(logger_name='cbus', default_level='INFO'):
    """
    Configure logging for the C-Bus library.
    
    Reads the CMQTTD_VERBOSITY environment variable to set the logging level.
    If not set, uses the default_level.
    
    :param logger_name: Name of the logger to configure (default: 'cbus')
    :param default_level: Default logging level if env var not set (default: 'INFO')
    :return: Configured logger instance
    """
    # Get verbosity from environment, fallback to default
    verbosity = os.environ.get('CMQTTD_VERBOSITY', default_level).upper()
    
    # Validate the verbosity level
    if verbosity not in VALID_LOG_LEVELS:
        print(f"Warning: Invalid CMQTTD_VERBOSITY '{verbosity}', using '{default_level}'", 
              file=sys.stderr)
        verbosity = default_level
    
    # Configure the logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(VALID_LOG_LEVELS[verbosity])
    
    # Only add handler if logger doesn't have handlers already
    if not logger.handlers:
        # Create console handler with formatter
        handler = logging.StreamHandler()
        handler.setLevel(VALID_LOG_LEVELS[verbosity])
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(handler)
    
    # Also configure the root logger if needed
    if logger_name == 'cbus':
        # Configure root logger to prevent duplicate logs
        root_logger = logging.getLogger()
        if not root_logger.handlers:
            root_logger.setLevel(VALID_LOG_LEVELS[verbosity])
    
    return logger

def get_configured_logger(name='cbus'):
    """
    Get a logger instance with centralized configuration applied.
    
    :param name: Logger name (default: 'cbus')
    :return: Configured logger instance
    """
    # Ensure logging is configured
    configure_logging(name)
    return logging.getLogger(name) 
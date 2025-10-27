#!/usr/bin/env python
# cbus/constants.py - Configuration constants for C-Bus protocol
# Copyright 2024 Mitchell Johnson
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
Configuration constants for C-Bus protocol implementation.

This module centralizes all magic numbers and configuration values used
throughout the codebase to improve maintainability and documentation.
"""

# Confirmation Code Management
# -----------------------------
# Maximum time (in seconds) to wait for a confirmation response before timing out
CONFIRMATION_TIMEOUT_SECONDS = 30.0

# Maximum number of times to retry sending a packet if no confirmation received
MAX_PACKET_RETRIES = 3

# Time interval (in seconds) between retry attempts
PACKET_RETRY_INTERVAL_SECONDS = 1.0

# Threshold for warning about high pending confirmation count
PENDING_CONFIRMATION_WARNING_THRESHOLD = 20

# Force cleanup when confirmation code pool exceeds this utilization percentage
CONFIRMATION_CODE_FORCE_CLEANUP_THRESHOLD = 0.9  # 90%

# Percentage of oldest codes to release during force cleanup
CONFIRMATION_CODE_FORCE_CLEANUP_PERCENTAGE = 0.25  # 25%


# Packet Transmission
# -------------------
# Delay (in seconds) before sending packet to accommodate slow CNI hardware
# The CNI can be slow to process commands, this delay prevents buffer overruns
PACKET_SEND_DELAY_SECONDS = 0.1


# Time Synchronization
# --------------------
# Default interval (in seconds) between time sync packets sent to C-Bus network
# Set to 0 to disable time synchronization
DEFAULT_TIMESYNC_FREQUENCY_SECONDS = 10


# Periodic Task Throttling
# ------------------------
# Default period (in seconds) for throttling C-Bus commands
# Prevents flooding the CNI with too many commands at once
DEFAULT_THROTTLE_PERIOD_SECONDS = 0.2


# Status Request Configuration
# ----------------------------
# Size of each status request block (number of group addresses per request)
# C-Bus typically returns status in blocks of 32 group addresses
STATUS_REQUEST_BLOCK_SIZE = 32

# Maximum group address value (0-255 are valid)
MAX_GROUP_ADDRESS = 255


# Connection Management
# ---------------------
# Maximum consecutive failures before logging system instability warning
MAX_CONSECUTIVE_FAILURES = 10


# Memory Management
# -----------------
# Maximum size for pending confirmations dictionary before forcing cleanup
MAX_PENDING_CONFIRMATIONS = 50

# Maximum size for groupDB dictionary before implementing LRU eviction
# Set to 0 for unlimited (will grow with all discovered groups)
MAX_GROUPDB_SIZE = 1000  # 0 = unlimited


# MQTT Configuration
# ------------------
# Default MQTT port for TLS connections
MQTT_DEFAULT_TLS_PORT = 8883

# Default MQTT port for plain TCP connections
MQTT_DEFAULT_PLAIN_PORT = 1883

# Default MQTT keepalive interval in seconds
MQTT_DEFAULT_KEEPALIVE_SECONDS = 60


# Logging
# -------
# Default verbosity level when CMQTTD_VERBOSITY environment variable not set
DEFAULT_LOG_LEVEL = 'INFO'


# Network Timeouts
# ----------------
# Timeout for MQTT subscribe operations in seconds
MQTT_SUBSCRIBE_TIMEOUT_SECONDS = 10.0

# Timeout for MQTT publish operations in seconds
MQTT_PUBLISH_TIMEOUT_SECONDS = 5.0


# Error Recovery
# --------------
# Delay (in seconds) before retrying after an error in background tasks
ERROR_RETRY_DELAY_SECONDS = 1.0

# Maximum time (in seconds) to wait for graceful task cancellation
TASK_CANCELLATION_TIMEOUT_SECONDS = 5.0

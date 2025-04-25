#!/usr/bin/env python3
"""
C-Bus Simulator State Management

This module maintains the state of the simulated C-Bus network, including
networks, applications, groups, and their levels.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Union

logger = logging.getLogger(__name__)

class SimulatorState:
    """
    Maintains the state of the simulated C-Bus network.
    """
    
    def __init__(self):
        """
        Initialize the simulator state with default values.
        """
        # Device information
        self.device_info = {
            "serial_number": "00000000",
            "type": "5500CN",
            "firmware_version": "1.0.0",
            "pci_version": "v3.7"
        }
        
        # Network configuration
        self.networks = {}
        
        # Default network
        self.default_network = {
            "name": "Default Network",
            "network_id": 254,
            "applications": {}
        }
        self.networks[254] = self.default_network
        
        # Default lighting application
        self.default_lighting = {
            "application_id": 56,
            "name": "Lighting",
            "groups": {}
        }
        self.default_network["applications"][56] = self.default_lighting
        
        # Add some default groups
        for i in range(1, 5):
            self.default_lighting["groups"][i] = {
                "group_id": i,
                "name": f"Group {i}",
                "level": 0,
                "last_updated": time.time()
            }
        
        # Simple direct access to light states for quick lookups
        self.light_states = {}
        for i in range(1, 5):
            self.light_states[i] = 0
        
        # Simulation settings
        self.simulation_settings = {
            "smart_mode": True,
            "default_source_address": 5,
            "delay_min_ms": 10,
            "delay_max_ms": 50,
            "packet_loss_probability": 0.0,
            "clock_drift_seconds_per_day": 0
        }
        
        # Current mode (basic or smart)
        self.smart_mode = True
        
        # PCI status
        self.pci_status = {
            "online": True,
            "last_reset": time.time(),
            "error_count": 0
        }
        
        # Unit information
        self.units = {}
        
        # Command history
        self.command_history = []
        self.max_command_history = 100
    
    def apply_configuration(self, config: Dict[str, Any]) -> None:
        """
        Apply configuration to the simulator state.
        
        Args:
            config: Configuration dictionary
        """
        # Device information
        if "device" in config:
            self.device_info.update(config["device"])
        
        # Reset networks
        self.networks = {}
        self.light_states = {}  # Reset light states
        
        # Configure networks
        if "networks" in config:
            for network_config in config["networks"]:
                network_id = network_config.get("network_id", 254)
                
                # Create network
                network = {
                    "name": network_config.get("name", f"Network {network_id}"),
                    "network_id": network_id,
                    "applications": {}
                }
                
                # Add applications
                for app_config in network_config.get("applications", []):
                    app_id = app_config.get("application_id")
                    if app_id is None:
                        continue
                    
                    # Create application
                    app = {
                        "application_id": app_id,
                        "name": app_config.get("name", f"Application {app_id}"),
                        "groups": {}
                    }
                    
                    # Add groups for the application
                    if "groups" in app_config:
                        for group_config in app_config["groups"]:
                            group_id = group_config.get("group_id")
                            if group_id is None:
                                continue
                            
                            # Initial level from config or default to 0
                            initial_level = group_config.get("initial_level", 0)
                            
                            # Create group
                            app["groups"][group_id] = {
                                "group_id": group_id,
                                "name": group_config.get("name", f"Group {group_id}"),
                                "level": initial_level,
                                "last_updated": time.time()
                            }
                            
                            # Also update the light_states for quick access
                            self.light_states[group_id] = initial_level
                    
                    network["applications"][app_id] = app
                
                self.networks[network_id] = network
        else:
            # No networks in config, use defaults
            self.networks[254] = self.default_network
            # Make sure light_states is initialized
            for i in range(1, 5):
                self.light_states[i] = 0
        
        # Configure units
        if "units" in config:
            for unit_config in config["units"]:
                unit_address = unit_config.get("unit_address")
                if unit_address is None:
                    continue
                
                self.units[unit_address] = {
                    "unit_address": unit_address,
                    "type": unit_config.get("type", "Unknown"),
                    "group_address": unit_config.get("group_address"),
                    "application_address": unit_config.get("application_address"),
                    "zone_address": unit_config.get("zone_address")
                }
        
        # Configure simulation settings
        if "simulation" in config:
            self.simulation_settings.update(config["simulation"])
            self.smart_mode = self.simulation_settings.get("smart_mode", True)
        
        logger.info(f"Configuration applied. {len(self.light_states)} light groups configured.")
    
    def get_group_level(self, network_id: int, application_id: int, group_id: int) -> int:
        """
        Get the current level of a group.
        
        Args:
            network_id: The network ID
            application_id: The application ID
            group_id: The group ID
        
        Returns:
            The current level (0-255) or 0 if group not found
        """
        # Fast path - check light_states first
        if group_id in self.light_states:
            return self.light_states[group_id]
            
        # Fall back to checking the network hierarchy
        try:
            return self.networks[network_id]["applications"][application_id]["groups"][group_id]["level"]
        except KeyError:
            logger.warning(f"Group not found: network={network_id}, app={application_id}, group={group_id}")
            return 0
    
    def set_group_level(self, network_id: int, application_id: int, group_id: int, level: int) -> bool:
        """
        Set the level of a group.
        
        Args:
            network_id: The network ID
            application_id: The application ID
            group_id: The group ID
            level: The level (0-255)
        
        Returns:
            True if successful, False otherwise
        """
        # Validate level
        level = max(0, min(255, level))
        
        try:
            # Update the network hierarchy
            if network_id in self.networks and application_id in self.networks[network_id]["applications"] and group_id in self.networks[network_id]["applications"][application_id]["groups"]:
                self.networks[network_id]["applications"][application_id]["groups"][group_id]["level"] = level
                self.networks[network_id]["applications"][application_id]["groups"][group_id]["last_updated"] = time.time()
                
                # Also update light_states for quick access
                self.light_states[group_id] = level
                
                # Get the group name for logging
                group_name = self.networks[network_id]["applications"][application_id]["groups"][group_id]["name"]
                logger.info(f"💡 {group_name} level set to {level}")
                
                return True
            else:
                # Group doesn't exist in the hierarchy, but we'll still track it in light_states
                logger.warning(f"Group {group_id} not found in network hierarchy, creating tracking entry")
                self.light_states[group_id] = level
                return True
        except Exception as e:
            logger.error(f"Error setting group level: {e}")
            return False
    
    def get_all_group_levels(self, network_id: int, application_id: int) -> Dict[int, int]:
        """
        Get all group levels for an application.
        
        Args:
            network_id: The network ID
            application_id: The application ID
        
        Returns:
            A dictionary mapping group IDs to their levels
        """
        result = {}
        
        # First, add all from the light_states (quick access)
        result.update(self.light_states)
        
        # Then check the network hierarchy for any missing
        try:
            if network_id in self.networks and application_id in self.networks[network_id]["applications"]:
                groups = self.networks[network_id]["applications"][application_id]["groups"]
                for group_id, group in groups.items():
                    if group_id not in result:
                        result[group_id] = group["level"]
        except KeyError:
            logger.warning(f"Application not found: network={network_id}, app={application_id}")
        
        return result
    
    def log_command(self, command: str, source: Optional[str] = None) -> None:
        """
        Log a command to the command history.
        
        Args:
            command: The command string
            source: The source of the command (e.g., client IP)
        """
        entry = {
            "command": command,
            "timestamp": time.time(),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source
        }
        
        self.command_history.append(entry)
        
        # Limit the size of the history
        if len(self.command_history) > self.max_command_history:
            self.command_history = self.command_history[-self.max_command_history:]
    
    def get_command_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get the command history.
        
        Args:
            limit: Maximum number of entries to return
        
        Returns:
            The command history
        """
        if limit is not None:
            return self.command_history[-limit:]
        return self.command_history
    
    def reset(self) -> None:
        """
        Reset the simulator state.
        """
        # Clear all group levels
        for network_id in self.networks:
            for app_id in self.networks[network_id]["applications"]:
                for group_id in self.networks[network_id]["applications"][app_id]["groups"]:
                    self.networks[network_id]["applications"][app_id]["groups"][group_id]["level"] = 0
        
        # Reset light_states
        for group_id in self.light_states:
            self.light_states[group_id] = 0
        
        # Update PCI status
        self.pci_status["last_reset"] = time.time()
        self.pci_status["error_count"] = 0
        
        logger.info("Simulator state reset") 
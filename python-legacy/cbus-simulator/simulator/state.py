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

from simulator.models import (
    Network,
    Application,
    Group,
    DeviceInfo,
    SimulationSettings,
    UnitInfo,
)

logger = logging.getLogger(__name__)

# AIDEV-NOTE: SimulatorState holds a lot of mutable nested data. Be cautious when mutating.
# Future improvement: migrate to @dataclass structures or pydantic models for validation.

class SimulatorState:
    """
    Maintains the state of the simulated C-Bus network.
    """
    
    def __init__(self):
        """
        Initialize the simulator state with default values.
        """
        # Device information (typed)
        self.device_info = DeviceInfo()
        
        # Simulation settings (typed)
        self.simulation_settings = SimulationSettings()
        
        # Network configuration (typed)
        self.networks: Dict[int, Network] = {}
        
        # Build default lighting application + network
        default_lighting_app = Application(application_id=56, name="Lighting")
        for gid in range(1, 5):
            default_lighting_app.groups[gid] = Group(group_id=gid, name=f"Group {gid}")

        default_network = Network(
            network_id=254,
            name="Default Network",
            applications={56: default_lighting_app},
        )

        self.networks[254] = default_network
        
        # Simple direct access to light states for quick lookups
        self.light_states: Dict[int, int] = {gid: 0 for gid in range(1, 5)}
        
        # Current mode (basic or smart)
        self.smart_mode = self.simulation_settings.smart_mode
        
        # PCI status
        self.pci_status = {
            "online": True,
            "last_reset": time.time(),
            "error_count": 0
        }
        
        # Unit information
        self.units: Dict[int, UnitInfo] = {}
        
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
            for key, value in config["device"].items():
                if hasattr(self.device_info, key):
                    setattr(self.device_info, key, value)
        
        # Reset networks
        self.networks = {}
        self.light_states = {}
        
        # Configure networks
        if "networks" in config:
            for net_cfg in config["networks"]:
                net_id = net_cfg.get("network_id", 254)
                network = Network(network_id=net_id, name=net_cfg.get("name", f"Network {net_id}"))

                # Applications
                for app_cfg in net_cfg.get("applications", []):
                    app_id = app_cfg.get("application_id")
                    if app_id is None:
                        continue
                    app = Application(application_id=app_id, name=app_cfg.get("name", f"Application {app_id}"))

                    # Groups
                    for grp_cfg in app_cfg.get("groups", []):
                        grp_id = grp_cfg.get("group_id")
                        if grp_id is None:
                            continue
                        initial_level = grp_cfg.get("initial_level", 0)
                        group = Group(group_id=grp_id, name=grp_cfg.get("name", f"Group {grp_id}"), level=initial_level)
                        app.groups[grp_id] = group
                        self.light_states[grp_id] = initial_level

                    network.applications[app_id] = app

                self.networks[net_id] = network
        else:
            # No networks in config, use defaults
            self.__init__()  # Reset to defaults
        
        # Configure units
        if "units" in config:
            for u_cfg in config["units"]:
                u_addr = u_cfg.get("unit_address")
                if u_addr is None:
                    continue
                self.units[u_addr] = UnitInfo(
                    unit_address=u_addr,
                    type=u_cfg.get("type", "Unknown"),
                    group_address=u_cfg.get("group_address"),
                    application_address=u_cfg.get("application_address"),
                    zone_address=u_cfg.get("zone_address"),
                )
        
        # Configure simulation settings
        if "simulation" in config:
            for key, value in config["simulation"].items():
                if hasattr(self.simulation_settings, key):
                    setattr(self.simulation_settings, key, value)
            self.smart_mode = self.simulation_settings.smart_mode
        
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
        net = self.networks.get(network_id)
        if net:
            app = net.applications.get(application_id)
            if app:
                grp = app.groups.get(group_id)
                if grp:
                    return grp.level
        logger.warning(
            "Group not found: network=%s, app=%s, group=%s", network_id, application_id, group_id
        )
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
        
        net = self.networks.get(network_id)
        if net:
            app = net.applications.get(application_id)
            if app:
                grp = app.groups.get(group_id)
                if grp:
                    grp.level = level
                    grp.last_updated = time.time()
                    self.light_states[group_id] = level
                    logger.info("💡 %s level set to %s", grp.name, level)
                    return True
        # Group not found; track anyway
        logger.warning("Group %s not found in hierarchy; tracking only in light_states", group_id)
        self.light_states[group_id] = level
        return True
    
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
        net = self.networks.get(network_id)
        if net:
            app = net.applications.get(application_id)
            if app:
                for gid, grp in app.groups.items():
                    result.setdefault(gid, grp.level)
        else:
            logger.warning("Application not found: network=%s app=%s", network_id, application_id)
        
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
        for net in self.networks.values():
            for app in net.applications.values():
                for grp in app.groups.values():
                    grp.level = 0
        
        # Reset light_states
        for group_id in self.light_states:
            self.light_states[group_id] = 0
        
        # Update PCI status
        self.pci_status["last_reset"] = time.time()
        self.pci_status["error_count"] = 0
        
        logger.info("Simulator state reset") 
#!/usr/bin/env python3
"""
C-Bus Lighting Application Handler

This module implements the lighting application functionality for the C-Bus simulator.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class LightingApplication:
    """
    Handles lighting application commands and state management.
    """
    
    # C-Bus lighting application code
    APPLICATION_ID = 56
    
    def __init__(self, state_manager):
        """
        Initialize the lighting application handler.
        
        Args:
            state_manager: The simulator state manager
        """
        self.state_manager = state_manager
    
    def handle_on(self, network_id: int, group_id: int, source_addr: int) -> bool:
        """
        Handle a lighting ON command.
        
        Args:
            network_id: The network ID
            group_id: The group ID
            source_addr: The source address
        
        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Handling lighting ON: network={network_id}, group={group_id}, source={source_addr}")
        return self.state_manager.set_group_level(network_id, self.APPLICATION_ID, group_id, 255)
    
    def handle_off(self, network_id: int, group_id: int, source_addr: int) -> bool:
        """
        Handle a lighting OFF command.
        
        Args:
            network_id: The network ID
            group_id: The group ID
            source_addr: The source address
        
        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Handling lighting OFF: network={network_id}, group={group_id}, source={source_addr}")
        return self.state_manager.set_group_level(network_id, self.APPLICATION_ID, group_id, 0)
    
    def handle_ramp(self, network_id: int, group_id: int, duration: int, level: int, source_addr: int) -> bool:
        """
        Handle a lighting RAMP command.
        
        Args:
            network_id: The network ID
            group_id: The group ID
            duration: The ramp duration in seconds
            level: The target level (0-255)
            source_addr: The source address
        
        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Handling lighting RAMP: network={network_id}, group={group_id}, duration={duration}, level={level}, source={source_addr}")
        return self.state_manager.set_group_level(network_id, self.APPLICATION_ID, group_id, level)
    
    def handle_terminate_ramp(self, network_id: int, group_id: int, source_addr: int) -> bool:
        """
        Handle a lighting TERMINATE RAMP command.
        
        Args:
            network_id: The network ID
            group_id: The group ID
            source_addr: The source address
        
        Returns:
            True if successful, False otherwise
        """
        # Get current level (ramp termination keeps the current level)
        current_level = self.state_manager.get_group_level(network_id, self.APPLICATION_ID, group_id)
        
        logger.debug(f"Handling lighting TERMINATE RAMP: network={network_id}, group={group_id}, source={source_addr}, current_level={current_level}")
        
        # Set the same level again (to update last_updated timestamp)
        return self.state_manager.set_group_level(network_id, self.APPLICATION_ID, group_id, current_level)
    
    def get_status(self, network_id: int, group_id: int) -> int:
        """
        Get the status of a lighting group.
        
        Args:
            network_id: The network ID
            group_id: The group ID
        
        Returns:
            The current level (0-255)
        """
        return self.state_manager.get_group_level(network_id, self.APPLICATION_ID, group_id)
    
    def get_all_groups(self, network_id: int) -> Dict[int, int]:
        """
        Get all lighting groups and their levels.
        
        Args:
            network_id: The network ID
        
        Returns:
            Dictionary mapping group IDs to their levels
        """
        return self.state_manager.get_all_group_levels(network_id, self.APPLICATION_ID) 
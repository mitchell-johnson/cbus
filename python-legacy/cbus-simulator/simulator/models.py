from __future__ import annotations

"""Typed dataclass models used by the C-Bus simulator.

Breaking out these definitions keeps `state.py` readable and allows
future static-type checking (e.g. with mypy/pytype).
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

__all__ = [
    "Group",
    "Application",
    "Network",
    "DeviceInfo",
    "SimulationSettings",
    "UnitInfo",
]


@dataclass
class Group:
    group_id: int
    name: str
    level: int = 0
    last_updated: float = field(default_factory=time.time)


@dataclass
class Application:
    application_id: int
    name: str
    groups: Dict[int, Group] = field(default_factory=dict)


@dataclass
class Network:
    network_id: int
    name: str
    applications: Dict[int, Application] = field(default_factory=dict)

    # Legacy dict-style compatibility
    def get(self, item, default=None):
        return getattr(self, item, default)


@dataclass
class DeviceInfo:
    serial_number: str = "00000000"
    type: str = "5500CN"
    firmware_version: str = "1.0.0"
    pci_version: str = "v3.7"

    def __getitem__(self, item):
        return getattr(self, item)

    def __setitem__(self, key, value):
        setattr(self, key, value)


@dataclass
class SimulationSettings:
    smart_mode: bool = True
    default_source_address: int = 5
    delay_min_ms: int = 10
    delay_max_ms: int = 50
    packet_loss_probability: float = 0.0
    clock_drift_seconds_per_day: int = 0

    # Allow legacy dict-style access
    def __getitem__(self, item):
        return getattr(self, item)

    def __setitem__(self, key, value):
        setattr(self, key, value)


@dataclass
class UnitInfo:
    unit_address: int
    type: str = "Unknown"
    group_address: Optional[int] = None
    application_address: Optional[int] = None
    zone_address: Optional[int] = None 
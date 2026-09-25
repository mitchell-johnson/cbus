"""Sensor threshold/margin guard spec (issue #11 box 1, bead cbus-h22).

Spec-first offline scaffold only. Pure occupancy-threshold helpers
grounded in the documented SENPILL dependency semantics (threshold,
margin, enable dependencies; see docs/sensors.md): hysteresis-zone
classification and enable-dependency checks over caller-supplied
numbers. No sensor reads, no bus calls, no endpoints, no credentials,
no vendor data invented or read.

Honesty boundary: zone arithmetic and dependency logic are structural.
Optical behavior, profile-specific ranges, and physical testing remain
open; every behavioral slot starts ``unassessed``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

UNASSESSED = "unassessed"
Number = Union[int, float]
ZONES = ("trigger", "clear", "deadband")


@dataclass(frozen=True)
class ZoneResult:
    zone: str
    behavioral_comparison: str = UNASSESSED


@dataclass(frozen=True)
class DependencyCheck:
    ok: bool
    note: str
    behavioral_comparison: str = UNASSESSED


def _num(name: str, value: Any) -> Number:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    return value


def classify_zone(threshold: Any, margin: Any, reading: Any) -> ZoneResult:
    """Classify a sensor reading into a hysteresis zone.

    ``margin`` must be >= 0. ``reading >= threshold + margin`` →
    trigger; ``reading <= threshold - margin`` → clear; otherwise →
    deadband. Zero margin classifies equality as trigger.
    """
    t, m = _num("threshold", threshold), _num("margin", margin)
    r = _num("reading", reading)
    if m < 0:
        raise ValueError("margin must be >= 0")
    if r >= t + m:
        return ZoneResult(zone="trigger")
    if r <= t - m:
        return ZoneResult(zone="clear")
    return ZoneResult(zone="deadband")


def check_enable_dependency(channel_enabled: Any, master_enabled: Any) -> DependencyCheck:
    """Check a sensor channel against its master enable (pure booleans).

    A channel enabled while its master is disabled violates the
    documented enable dependency. Non-bool inputs raise ``TypeError``.
    """
    if not isinstance(channel_enabled, bool):
        raise TypeError("channel_enabled must be bool")
    if not isinstance(master_enabled, bool):
        raise TypeError("master_enabled must be bool")
    if channel_enabled and not master_enabled:
        return DependencyCheck(
            ok=False, note="channel enabled while master disabled")
    return DependencyCheck(ok=True, note="enable dependency satisfied")

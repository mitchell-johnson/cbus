"""Thermostat settings guard spec (issue #11 box 8, bead cbus-9zz).

Spec-first offline scaffold only. Pure scalar-setting validators where
every range is a caller-supplied fact, never an embedded vendor limit.
No device I/O, no endpoints, no credentials, no vendor data invented
or read.

Honesty boundary: range conformance is structural arithmetic. Control
behavior, scheduling execution, and on-device effects require
per-profile physical acceptance and remain open; every behavioral slot
starts ``unassessed``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

UNASSESSED = "unassessed"
Number = Union[int, float]


@dataclass(frozen=True)
class SettingCheck:
    ok: bool
    note: str
    behavioral_comparison: str = UNASSESSED


def _num(name: str, value: Any) -> Number:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    return value


def check_setting(name: str, value: Any, spec: Any) -> SettingCheck:
    """Check one scalar setting against a caller-supplied range spec.

    ``spec`` is a dict with numeric ``min``/``max`` and optional
    positive numeric ``step`` (value must satisfy
    ``(value - min) % step == 0`` within float tolerance 1e-9).
    ``name`` must be a non-empty str. Out-of-range returns ok=False
    (no exception); malformed spec/name/value raise.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty str")
    v = _num("value", value)
    if not isinstance(spec, dict):
        raise TypeError("spec must be dict")
    try:
        lo, hi = spec["min"], spec["max"]
    except KeyError as exc:
        raise ValueError(f"spec missing {exc}") from exc
    lo, hi = _num("spec.min", lo), _num("spec.max", hi)
    if lo > hi:
        raise ValueError("spec.min must be <= spec.max")
    step = spec.get("step", None)
    if step is not None:
        step = _num("spec.step", step)
        if step <= 0:
            raise ValueError("spec.step must be > 0")
    if not lo <= v <= hi:
        return SettingCheck(ok=False, note=f"{name} out of range")
    if step is not None:
        remainder = (float(v) - float(lo)) % float(step)
        if not (remainder <= 1e-9 or float(step) - remainder <= 1e-9):
            return SettingCheck(ok=False, note=f"{name} off step")
    return SettingCheck(ok=True, note=f"{name} within range")


def check_heat_cool(
    heat: Any, cool: Any, min_deadband: Any
) -> SettingCheck:
    """Check heat/cool setpoint separation (pure arithmetic).

    Requires numeric ``heat`` <= ``cool`` with
    ``cool - heat >= min_deadband`` (>= 0). Violations return ok=False.
    """
    h, c = _num("heat", heat), _num("cool", cool)
    d = _num("min_deadband", min_deadband)
    if d < 0:
        raise ValueError("min_deadband must be >= 0")
    if h > c:
        return SettingCheck(ok=False, note="heat above cool")
    if c - h < d:
        return SettingCheck(ok=False, note="deadband too small")
    return SettingCheck(ok=True, note="heat/cool separated")

"""Timer duration guard spec (issue #11 box 3, bead cbus-0up).

Spec-first offline scaffold only. Pure timer-setting validators over
the documented eDLT timer modes (Toggle/Retrigger with target/expiry
levels, duration and ramp; see docs/edlt-timer.md). Caller supplies
the maximum duration bound; no vendor limits embedded. No timers
started, no bus calls, no endpoints, no credentials.

Honesty boundary: range/mode conformance is structural. Expiry timing
behavior and physical output effects require device acceptance and
remain open; every behavioral slot starts ``unassessed``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

UNASSESSED = "unassessed"
TIMER_MODES = ("toggle", "retrigger")
Number = Union[int, float]


@dataclass(frozen=True)
class TimerCheck:
    ok: bool
    note: str
    behavioral_comparison: str = UNASSESSED


def _num(name: str, value: Any) -> Number:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    return value


def _level(name: str, value: Any) -> Number:
    v = _num(name, value)
    if not 0 <= v <= 100:
        raise ValueError(f"{name} must be 0-100")
    return v


def check_timer(
    mode: Any,
    duration: Any,
    target: Any,
    expiry: Any,
    max_duration: Any,
) -> TimerCheck:
    """Check one timer configuration (no side effects).

    ``mode`` in Toggle/Retrigger; ``duration`` numeric with
    ``0 <= duration <= max_duration`` (caller bound, must be >= 0);
    ``target``/``expiry`` levels 0-100. Retrigger with zero duration
    returns ok=False (nothing to retrigger); toggle allows zero.
    Range violations return ok=False; malformed inputs raise.
    """
    if mode not in TIMER_MODES:
        raise ValueError(f"unknown timer mode: {mode!r}")
    d = _num("duration", duration)
    m = _num("max_duration", max_duration)
    if m < 0:
        raise ValueError("max_duration must be >= 0")
    t = _level("target", target)
    e = _level("expiry", expiry)
    _ = t, e
    if not 0 <= d <= m:
        return TimerCheck(ok=False, note="duration out of bounds")
    if mode == "retrigger" and d == 0:
        return TimerCheck(ok=False, note="retrigger needs duration > 0")
    return TimerCheck(ok=True, note=f"{mode} timer within bounds")

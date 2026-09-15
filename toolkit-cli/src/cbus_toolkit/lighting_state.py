"""Independent, bounded lighting SAL state for the synthetic PCI peer.

CBUS-QS issue 2.0 defines ON79, OFF01, ramp codes02..7A and full-scale
durations. Native CBusLightingApplication also defines TERMINATERAMP09.
The model interpolates continuously at that rate; it does not claim a device's
PWM quantization or power-loss behavior. Snapshots pause at capture time and
resume any remaining ramp from that point when loaded with a new clock.
"""
from __future__ import annotations

import math
import time


class LightingPacketError(ValueError):
    pass


RAMP_SECONDS = dict(zip(range(2, 123, 8), (0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900, 1020)))


def _number(value, low, high):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high and math.isfinite(value)
    except OverflowError:
        return False


def _key(application, group):
    if (not isinstance(application, int) or isinstance(application, bool) or not 48 <= application <= 95
            or not isinstance(group, int) or isinstance(group, bool) or not 0 <= group <= 254):
        raise LightingPacketError("Invalid lighting application or group")
    return application, group


class LightingState:
    def __init__(self, groups=None, *, clock=time.monotonic):
        self.clock = clock
        self.groups = {}
        now = self._now()
        for (application, group), level in (groups or {}).items():
            if not _number(level, 0, 255):
                raise LightingPacketError("Invalid initial lighting level")
            self.groups[_key(application, group)] = (float(level), float(level), now, 0.0)

    def _now(self):
        now = self.clock()
        if not _number(now, 0, float("inf")):
            raise LightingPacketError("Lighting clock must return a finite nonnegative number")
        return now

    @staticmethod
    def _sample(record, now):
        start, target, began, duration = record
        elapsed = max(0.0, now - began)
        if elapsed >= duration or duration == 0:
            return target, target, 0.0
        return start + (target - start) * elapsed / duration, target, duration - elapsed

    def level(self, application, group):
        return self._sample(self.groups[_key(application, group)], self._now())[0]

    def mmi_states(self, application):
        _key(application, 0)
        now = self._now()
        return {group: 1 if self._sample(record, now)[0] > 0 else 2
                for (app, group), record in self.groups.items() if app == application}

    def receive(self, application, payload):
        """Validate a complete SAL chain before changing explicitly known groups."""
        _key(application, 0)
        if not isinstance(payload, bytes) or not 2 <= len(payload) <= 32:
            raise LightingPacketError("Invalid lighting SAL length")
        commands = []
        offset = 0
        while offset < len(payload):
            opcode = payload[offset]
            size = 3 if opcode in RAMP_SECONDS else 2 if opcode in (1, 9, 121) else None
            if size is None or offset + size > len(payload):
                raise LightingPacketError("Unsupported or truncated lighting command")
            key = _key(application, payload[offset + 1])
            if key not in self.groups:
                raise LightingPacketError("Lighting group is not configured in this fixture")
            target = payload[offset + 2] if size == 3 else 0 if opcode == 1 else 255 if opcode == 121 else None
            commands.append((key, opcode, target))
            offset += size
        now = self._now()
        for key, opcode, target in commands:
            current = self._sample(self.groups[key], now)[0]
            if target is None:
                target = current
            duration = abs(target - current) * RAMP_SECONDS.get(opcode, 0) / 255
            self.groups[key] = (current if duration else float(target), float(target), now, duration)
        return len(commands)

    def snapshot(self):
        now = self._now()
        rows = []
        for (application, group), record in sorted(self.groups.items()):
            level, target, remaining = self._sample(record, now)
            rows.append({"application": application, "group": group, "level": level,
                         "target": target, "remaining": remaining})
        return {"format": "cbus-synthetic-lighting-v1", "groups": rows}

    @classmethod
    def from_snapshot(cls, snapshot, *, clock=time.monotonic):
        if (not isinstance(snapshot, dict) or set(snapshot) != {"format", "groups"}
                or snapshot["format"] != "cbus-synthetic-lighting-v1"
                or not isinstance(snapshot["groups"], list) or len(snapshot["groups"]) > 48 * 255):
            raise LightingPacketError("Invalid synthetic lighting snapshot")
        state = cls(clock=clock)
        now = state._now()
        for row in snapshot["groups"]:
            if not isinstance(row, dict) or set(row) != {"application", "group", "level", "target", "remaining"}:
                raise LightingPacketError("Invalid synthetic lighting group fields")
            key = _key(row["application"], row["group"])
            if (key in state.groups or not _number(row["level"], 0, 255) or not _number(row["target"], 0, 255)
                    or not _number(row["remaining"], 0, 1020)
                    or (row["remaining"] == 0) != (row["level"] == row["target"])):
                raise LightingPacketError("Invalid synthetic lighting group state")
            state.groups[key] = (float(row["level"]), float(row["target"]), now, float(row["remaining"]))
        return state

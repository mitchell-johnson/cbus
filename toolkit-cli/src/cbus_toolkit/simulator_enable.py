"""Independent synthetic Enable Control SET receiver; no client encoders."""
from __future__ import annotations

from copy import deepcopy


class EnablePacketError(ValueError):
    pass


def _integer(value, maximum=255):
    return type(value) is int and 0 <= value <= maximum


class EnableState:
    def __init__(self):
        self.variables = {}
        self.sequence = 0

    def receive(self, payload):
        if not isinstance(payload, bytes) or not 3 <= len(payload) <= 32 or len(payload) % 3:
            raise EnablePacketError("Invalid Enable Control SET payload length")
        operations = [payload[i:i+3] for i in range(0, len(payload), 3)]
        if any(operation[0] != 2 for operation in operations):
            raise EnablePacketError("Unsupported Enable Control opcode")
        for _opcode, variable, level in operations:
            self.sequence += 1
            previous = self.variables.get(variable, {"set_count": 0})
            self.variables[variable] = {"level": level, "set_count": previous["set_count"] + 1}
        return len(operations)

    def snapshot(self):
        return {"format": "cbus-synthetic-enable-v1", "sequence": self.sequence,
                "variables": [{"variable": variable, **deepcopy(value)} for variable, value in sorted(self.variables.items())]}

    @classmethod
    def from_snapshot(cls, snapshot):
        if (not isinstance(snapshot, dict) or set(snapshot) != {"format", "sequence", "variables"}
                or snapshot["format"] != "cbus-synthetic-enable-v1"
                or not _integer(snapshot["sequence"], (1 << 63) - 1)
                or not isinstance(snapshot["variables"], list) or len(snapshot["variables"]) > 256):
            raise EnablePacketError("Invalid synthetic Enable Control snapshot")
        state = cls()
        for row in snapshot["variables"]:
            if (not isinstance(row, dict) or set(row) != {"variable", "level", "set_count"}
                    or not _integer(row["variable"]) or row["variable"] in state.variables
                    or not _integer(row["level"]) or not _integer(row["set_count"], snapshot["sequence"])
                    or row["set_count"] < 1):
                raise EnablePacketError("Invalid synthetic Enable Control variable")
            state.variables[row["variable"]] = {"level": row["level"], "set_count": row["set_count"]}
        if sum(item["set_count"] for item in state.variables.values()) != snapshot["sequence"]:
            raise EnablePacketError("Inconsistent synthetic Enable Control operation count")
        state.sequence = snapshot["sequence"]
        return state

"""C-Gate Enable Control and explicit reads of its cached variable levels."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .applications import ApplicationError, NativeTrigger, _byte, action_selector
from .native import _token


@dataclass(frozen=True)
class EnableEvent:
    timestamp: str
    address: str
    oid: str
    value: int
    source_unit: int
    session_id: str | None
    command_id: str | None
    raw: str


def parse_enable_event(line):
    """Decode native702 Enable SET records; outgoing events are not receipts."""
    if not isinstance(line, str):
        raise ApplicationError("Native event must be text")
    if not re.search(r"\b702\s+.*\[enable\] set\b", line):
        return None
    match = re.fullmatch(r"(?:#e# )?([0-9]{8}-[0-9]{6}(?:\.[0-9]{3})?) 702 (\S+) (\S+) \[enable\] set value=([0-9]+) sourceUnit=([0-9]+)(?: (.*))?", line)
    if match is None:
        raise ApplicationError("Malformed native Enable Control event")
    timestamp, address, oid, value, source, tail = match.groups()
    value, source = _byte(int(value), "Enable event value"), _byte(int(source), "Enable event source unit")
    metadata = {}
    for token in (tail or "").split():
        key, separator, item = token.partition("=")
        if not separator or not key or not item or key in metadata:
            raise ApplicationError("Malformed native Enable Control event metadata")
        metadata[key] = item
    return EnableEvent(timestamp, address, oid, value, source, metadata.get("sessionId"), metadata.get("commandId"), line)


def encode_enable_set(variable, value):
    """Encode the Enable Control SET SAL operation from a numeric value."""
    token = action_selector(value)
    if not token.isdecimal():
        raise ApplicationError("Offline enable encoding requires a numeric value")
    return bytes((2, _byte(variable, "Enable variable"), int(token)))


class NativeEnable:
    def __init__(self, client):
        self.client = client
        # Native Trigger and Enable variables use the same DB Level schema and
        # GET response format. Reuse that validated lookup, never guess a tag.
        self._variables = NativeTrigger(client)

    def set(self, address, value, *, force=False):
        address = _token(address, "enable variable address")
        token = action_selector(value)
        if type(force) is not bool:
            raise ApplicationError("Force must be a boolean")
        if not token.isdecimal():
            token = str(self._variables.resolve_level_tag(address, token))
        return self.client.command(f"ENABLE SET {address} {token}" + (" FORCE" if force else ""))

    def remove(self, address):
        """Request native deletion of its saved value file.

        Build2001 leaves the live object/cache intact and ignores file deletion
        failure. Its200 status does not independently prove any value removal.
        """
        return self.client.command("ENABLE REMOVE " + _token(address, "enable variable address"))

    def get(self, address, attribute="*"):
        return self._variables.get(_token(address, "enable address"), attribute)

    def state(self, address):
        return self.get(address, "State")

    def groups(self, application):
        return self._variables.groups(application)

    def level(self, address):
        result = self.get(address, "Level")
        levels = {}
        for resolved, fields in result["objects"].items():
            if len(fields) != 1 or next(iter(fields)).casefold() != "level":
                raise ApplicationError("Expected native Enable Level attribute")
            value = next(iter(fields.values()))
            if not re.fullmatch(r"[0-9]+", value) or not 0 <= int(value) <= 255:
                raise ApplicationError("Native Enable Level must be an integer in 0..255")
            levels[resolved] = int(value)
        return {"levels": levels, "cached": True, "device_verified": False, "response": result["response"]}

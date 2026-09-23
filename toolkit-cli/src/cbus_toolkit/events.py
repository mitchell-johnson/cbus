"""C-Gate event, status and configuration monitoring on a command session."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .native import _token


@dataclass(frozen=True)
class EventRecord:
    category: str
    text: str
    raw: str
    timestamp: str | None = None
    code: int | None = None


def parse_event(raw: str) -> EventRecord:
    if not isinstance(raw, str):
        raise ValueError("C-Gate event must be text")
    if any(c in raw for c in "\r\n\x00"):
        raise ValueError("C-Gate event must be one line without NUL")
    if raw == "###!!!Event buffer overflow. Events have been missed.!!!###":
        return EventRecord("overflow", raw, raw)
    category, text = "event", raw
    if raw[:3] in ("#e#", "#s#", "#c#"):
        category = {"#e#": "event", "#s#": "status", "#c#": "configuration"}[raw[:3]]
        text = raw[3:].lstrip(" ")
    match = re.match(r"^(\d{8}-\d{6}(?:\.\d+)?) ([789]\d\d)(?: |$)", text)
    if match:
        return EventRecord(category, text[match.end():], raw, match[1], int(match[2]))
    if category == "event" and not raw.startswith("#e#"):
        raise ValueError("Unrecognized C-Gate event framing")
    return EventRecord(category, text, raw)


class NativeEvents:
    def __init__(self, client):
        self.client = client

    def subscribe(self, mode="e8s1c1"):
        mode = _token(mode, "event mode")
        if mode.upper() in ("ON", "OFF"):
            mode = mode.upper()
        elif not re.fullmatch(r"e[+0-9]s[01]c[01]", mode):
            raise ValueError("Event mode must be ON, OFF or e[+0-9]s[01]c[01]")
        response = self.client.command("EVENT " + mode)
        if response.code != 200:
            raise RuntimeError("Event subscription did not complete: " + response.final)
        return response

    def request_state(self, address):
        """Ask an already loaded network for its current event snapshot."""
        return self.client.command("GETSTATE " + _token(address, "network or C-Group address"))

    def read(self):
        return parse_event(self.client.read_event())

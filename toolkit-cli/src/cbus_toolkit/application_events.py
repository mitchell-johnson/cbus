"""Bounded projection of retained native Lighting event records.

The literal C-Gate 3.4 Lighting capture in
``rust/testdata/fixtures/native_cgate_lighting_events.json`` pins these forms.
This is a client-side event filter, not the original Toolkit Application Log.
Unknown grammars stay opaque; a missing source is never replaced with zero.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .events import EventRecord


_ADDRESS = (
    r"(?P<address>//(?P<project>[^/\s]+)/(?P<network>[^/\s]+)/"
    r"(?P<application>[0-9]{1,3})/(?P<group>[0-9]{1,3}))"
)
_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_CONTEXT = r"(?: sessionId=(?P<session_id>cmd[0-9]+) commandId=(?P<command_id>[^\s]+))?"
_LEVEL = re.compile(
    _ADDRESS + r" (?:(?P<oid>" + _UUID + r"|-) )?"
    r"(?:(?P<change>new) level=(?P<level>[0-9]{1,3}) sourceunit=(?P<source_unit>[0-9]{1,3})"
    r" ramptime=(?P<ramp_seconds>[0-9]{1,4})|"
    r"(?P<terminated>ramp terminated) new level=(?P<terminated_level>[0-9]{1,3})"
    r" sourceunit=(?P<terminated_source>[0-9]{1,3}))" + _CONTEXT
)
_STATUS = re.compile(
    r"lighting (?P<kind>on|off|ramp|terminateramp) " + _ADDRESS + r" (?P<values>.*)"
)
_SOURCE = r"#sourceunit=(?P<source_unit>[0-9]{1,3}) OID=(?P<oid>" + _UUID + r")?" + _CONTEXT
_STATUS_VALUES = {
    "on": re.compile(r" " + _SOURCE),
    "off": re.compile(r" " + _SOURCE),
    "ramp": re.compile(r"(?P<level>[0-9]{1,3}) (?P<ramp_seconds>[0-9]{1,4}) " + _SOURCE),
    "terminateramp": re.compile(r"#level=(?P<level>[0-9]{1,3}) " + _SOURCE),
}


@dataclass(frozen=True)
class LightingEvent:
    address: str
    project: str
    network: str
    application: int
    group: int
    kind: str
    source_unit: int
    level: int
    ramp_seconds: int | None
    oid: str | None
    session_id: str | None
    command_id: str | None


def project_lighting_event(record: EventRecord) -> LightingEvent | None:
    """Read only the admitted native Lighting grammar, preserving its facts.

    A native 730 level-change row and its separate status row remain separate.
    The address's exact project/network spelling is retained. Explicit source
    zero is a literal source byte, not a verified originating-unit identity.
    """
    if record.category == "event" and record.code == 730:
        match = _LEVEL.fullmatch(record.text)
        if match is None:
            return None
        fields = match.groupdict()
        terminated = fields["terminated"] is not None
        kind = "ramp_terminated" if terminated else "level_change"
        level = int(fields["terminated_level"] if terminated else fields["level"])
        source = int(fields["terminated_source"] if terminated else fields["source_unit"])
        ramp = None if terminated else int(fields["ramp_seconds"])
    elif record.category == "status":
        match = _STATUS.fullmatch(record.text)
        if match is None:
            return None
        fields = match.groupdict()
        kind = fields["kind"]
        values = _STATUS_VALUES[kind].fullmatch(fields["values"])
        if values is None:
            return None
        fields.update(values.groupdict())
        source = int(fields["source_unit"])
        level = 255 if kind == "on" else 0 if kind == "off" else int(fields["level"])
        ramp = int(fields["ramp_seconds"]) if kind == "ramp" else None if kind == "terminateramp" else 0
    else:
        return None
    application, group = int(fields["application"]), int(fields["group"])
    if not (48 <= application <= 95 and 0 <= group <= 255 and 0 <= source <= 255 and 0 <= level <= 255):
        return None
    if ramp is not None and not 0 <= ramp <= 1020:
        return None
    return LightingEvent(
        fields["address"], fields["project"], fields["network"], application, group,
        kind, source, level, ramp, None if fields["oid"] == "-" else fields["oid"],
        fields["session_id"], fields["command_id"],
    )


@dataclass(frozen=True)
class LightingEventFilter:
    application: int | None = None
    group: int | None = None
    source_unit: int | None = None

    def __post_init__(self):
        for name, lower, upper in (("application", 48, 95), ("group", 0, 255), ("source_unit", 0, 255)):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper):
                raise ValueError(f"Lighting event {name} must be an integer in {lower}..{upper}")

    @property
    def active(self) -> bool:
        return any(value is not None for value in (self.application, self.group, self.source_unit))

    def matches(self, record: EventRecord, projection: LightingEvent | None = None) -> bool:
        """AND the supplied selectors; overflow always survives filtering."""
        if record.category == "overflow" or not self.active:
            return True
        projection = projection if projection is not None else project_lighting_event(record)
        return projection is not None and all(
            value is None or getattr(projection, name) == value
            for name, value in (("application", self.application), ("group", self.group), ("source_unit", self.source_unit))
        )

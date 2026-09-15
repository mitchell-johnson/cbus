"""Typed native Trigger Control operations and cached attribute reads."""
from __future__ import annotations

import re
from dataclasses import dataclass
import xml.etree.ElementTree as ET

from .native import _token


class ApplicationError(ValueError):
    pass


@dataclass(frozen=True)
class TriggerEvent:
    timestamp: str
    address: str
    oid: str
    kind: str
    selector: int | None
    source_unit: int
    session_id: str | None
    command_id: str | None
    raw: str


def parse_trigger_event(line):
    """Decode a native702 Trigger Control event; return None for other events.

    An event correlated to this command session can describe C-Gate's own
    outgoing message. It does not independently establish physical execution.
    """
    if not isinstance(line, str):
        raise ApplicationError("Native event must be text")
    if not re.search(r'\b702\s+.*\[trigger\] (?:event|min|max|indicatorkill)\b', line):
        return None
    match = re.fullmatch(r'(?:#e# )?([0-9]{8}-[0-9]{6}(?:\.[0-9]{3})?) 702 (\S+) (\S+) \[trigger\] (event|min|max|indicatorkill) action=(-?[0-9]+) sourceUnit=([0-9]+)(?: (.*))?', line)
    if match is None:
        raise ApplicationError("Malformed native Trigger Control event")
    timestamp, address, oid, kind, selector, source, tail = match.groups()
    selector, source = int(selector), int(source)
    _byte(source, "Event source unit")
    if kind == 'indicatorkill':
        if selector != -1:
            raise ApplicationError("Indicator kill event must use action=-1")
        selector = None
    else:
        _byte(selector, "Event action selector")
        if (kind == 'min' and selector != 0) or (kind == 'max' and selector != 255):
            raise ApplicationError("Native min/max event has an inconsistent selector")
    metadata = {}
    for token in (tail or '').split():
        key, separator, value = token.partition('=')
        if not separator or not value or key in metadata:
            raise ApplicationError("Malformed native Trigger Control event metadata")
        metadata[key] = value
    return TriggerEvent(timestamp, address, oid, kind, selector, source,
                        metadata.get('sessionId'), metadata.get('commandId'), line)


def _byte(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ApplicationError(f"{field} must be an integer in 0..255")
    return value


def action_selector(value):
    """Return a numeric selector string or a validated database level-tag name."""
    if isinstance(value, int):
        return str(_byte(value, "Action selector"))
    if not isinstance(value, str):
        raise ApplicationError("Action selector must be a byte, integer percentage or level tag")
    if value.endswith('%'):
        if not re.fullmatch(r'[0-9]+%', value) or not 0 <= int(value[:-1]) <= 100:
            raise ApplicationError("Action percentage must be an integer in 0..100%")
        # Native Bk.b uses integer division, so50% becomes127, not128.
        return str(int(value[:-1]) * 255 // 100)
    if re.fullmatch(r'[+-]?[0-9]+', value):
        return str(_byte(int(value), "Action selector"))
    if value.lower().startswith(('0x', '0b')) or value.startswith('$'):
        try:
            number = int(value[1:], 16) if value.startswith('$') else int(value, 16 if value.lower().startswith('0x') else 2)
        except ValueError as error:
            raise ApplicationError("Invalid numeric action selector") from error
        return str(_byte(number, "Action selector"))
    if not value.strip() or len(value) > 1024 or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApplicationError("Level tag must be nonempty text without control characters, up to 1024 characters")
    return value


def encode_trigger_event(group, selector):
    """Encode one Trigger Control SAL event; names require native resolution."""
    token = action_selector(selector)
    if not token.isdecimal():
        raise ApplicationError("Offline event encoding requires a numeric action selector")
    return bytes((2, _byte(group, "Trigger group"), int(token)))


def encode_indicator_kill(group):
    return bytes((9, _byte(group, "Trigger group")))


def _attributes(response):
    result = {}
    for line in response.lines:
        match = re.fullmatch(r'300[- ]([^\s]+):\s+([^=]+)=(.*)', line)
        if match is None:
            raise RuntimeError("Malformed native application attribute response")
        address, name, value = match.groups()
        record = result.setdefault(address, {})
        name = name.strip()
        if not name or name.casefold() in {key.casefold() for key in record}:
            raise RuntimeError("Duplicate or empty native application attribute")
        record[name] = value
    if not result:
        raise RuntimeError("Native application attribute response is empty")
    return result


class NativeTrigger:
    """Trigger events, indicator clearing and native cached state; no retries.

    Native Trigger groups expose State/Name/EventLevel, not the last action
    selector as a GET Level parameter. State reads do not poll a physical unit.
    """
    def __init__(self, client):
        self.client = client

    def event(self, group, selector, *, force=False):
        group = _token(group, "trigger group address")
        token = action_selector(selector)
        if not isinstance(force, bool):
            raise ApplicationError("Force must be a boolean")
        if not token.isdecimal():
            token = str(self.resolve_level_tag(group, token))
        return self.client.command(f'TRIGGER EVENT {group} {token}' + (' FORCE' if force else ''))

    def resolve_level_tag(self, group, name):
        """Resolve the exact saved tag before sending a numeric event.

        Native3.4's TriggerEvent method rejects named selectors even after its
        database lookup. Reading native XML also supports names with spaces.
        No fallback to a guessed selector or automatic event replay is allowed.
        """
        from .programming import xml_text
        group = _token(group, "trigger group address")
        if not isinstance(name, str) or not name.strip() or len(name) > 1024 or any(ord(character) < 32 or ord(character) == 127 for character in name):
            raise ApplicationError("Invalid level tag name")
        response = self.client.command('DBGETXML ' + group)
        document = xml_text(response)
        if '<!DOCTYPE' in document.upper() or '<!ENTITY' in document.upper():
            raise ApplicationError("Native level XML contains a forbidden declaration")
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise ApplicationError("Malformed native level-tag XML") from error
        if root.tag not in ('Group', 'NetVar'):
            raise ApplicationError("Level tag lookup requires one database Group or NetVar")
        matches = [level for level in root.findall('Level') if level.findtext('TagName') == name]
        if len(matches) != 1:
            raise ApplicationError("Level tag must match exactly one database level")
        value = matches[0].get('Value')
        if value is None or not re.fullmatch(r'[0-9]+', value) or not 0 <= int(value) <= 255:
            raise ApplicationError("Named level has no valid byte Value")
        return int(value)

    def indicator_kill(self, group):
        return self.client.command('TRIGGER INDICATORKILL ' + _token(group, "trigger group address"))

    def get(self, address, attribute='*'):
        response = self.client.command(f'GET {_token(address, "trigger address")} {_token(attribute, "attribute")}')
        return {'objects': _attributes(response), 'cached': True, 'response': response}

    def state(self, address):
        return self.get(address, 'State')

    def groups(self, application):
        result = self.get(application, 'Groups')
        parsed = {}
        for address, fields in result['objects'].items():
            if len(fields) != 1 or next(iter(fields)).lower() != 'groups':
                raise RuntimeError("Expected native Groups attribute")
            value = next(iter(fields.values()))
            if value and not re.fullmatch(r'[0-9]+(?:,[0-9]+)*', value):
                raise RuntimeError("Malformed native trigger group list")
            groups = [int(item) for item in value.split(',')] if value else []
            if any(not 0 <= group <= 255 for group in groups) or len(groups) != len(set(groups)):
                raise RuntimeError("Invalid native trigger group addresses")
            parsed[address] = groups
        return {'groups': parsed, 'cached': True, 'response': result['response']}

"""Independent synthetic Trigger Control SAL decoder and persisted state.

The literal native wire capture establishes EVENT02/group/selector and
INDICATORKILL09/group. Native receiver source also supports MIN01 and MAX79.
No client encoders are imported. A kill preserves the last selector while
clearing the modeled indicator; every repeated EVENT remains a distinct event.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy


class ApplicationPacketError(ValueError):
    pass


def _integer(value, low=0, high=255):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


class TriggerState:
    def __init__(self):
        self.groups = {}
        self.events = deque(maxlen=256)
        self.sequence = 0

    def receive(self, payload):
        """Atomically apply a complete SAL command chain; return command count."""
        if not isinstance(payload, bytes) or not 2 <= len(payload) <= 32:
            raise ApplicationPacketError("Invalid Trigger Control SAL payload length")
        commands = []
        offset = 0
        while offset < len(payload):
            opcode = payload[offset]
            size = 3 if opcode == 2 else 2 if opcode in (1, 9, 121) else None
            if size is None or offset + size > len(payload):
                raise ApplicationPacketError("Unsupported or truncated Trigger Control command")
            group = payload[offset + 1]
            selector = payload[offset + 2] if opcode == 2 else 0 if opcode == 1 else 255 if opcode == 121 else None
            commands.append((opcode, group, selector))
            offset += size
        for opcode, group, selector in commands:
            self.sequence += 1
            record = self.groups.setdefault(group, {'selector': None, 'indicator_active': False, 'event_count': 0, 'kill_count': 0})
            if opcode == 9:
                record['indicator_active'] = False
                record['kill_count'] += 1
                command = 'indicator_kill'
            else:
                record['selector'] = selector
                record['indicator_active'] = True
                record['event_count'] += 1
                command = 'event' if opcode == 2 else 'min' if opcode == 1 else 'max'
            self.events.append({'sequence': self.sequence, 'command': command, 'group': group,
                                'selector': selector, 'indicator_active': record['indicator_active']})
        return len(commands)

    def snapshot(self):
        return {'format': 'cbus-synthetic-triggers-v1', 'sequence': self.sequence,
                'groups': [{'group': group, **deepcopy(record)} for group, record in sorted(self.groups.items())],
                'events': list(deepcopy(self.events))}

    @classmethod
    def from_snapshot(cls, snapshot):
        state = cls()
        if not isinstance(snapshot, dict) or set(snapshot) != {'format', 'sequence', 'groups', 'events'} or snapshot['format'] != 'cbus-synthetic-triggers-v1':
            raise ApplicationPacketError("Invalid synthetic trigger snapshot")
        if not _integer(snapshot['sequence'], 0, (1 << 63)-1) or not isinstance(snapshot['groups'], list) or len(snapshot['groups']) > 256 or not isinstance(snapshot['events'], list) or len(snapshot['events']) > 256:
            raise ApplicationPacketError("Invalid synthetic trigger snapshot bounds")
        state.sequence = snapshot['sequence']
        for row in snapshot['groups']:
            if not isinstance(row, dict) or set(row) != {'group', 'selector', 'indicator_active', 'event_count', 'kill_count'}:
                raise ApplicationPacketError("Invalid synthetic trigger group fields")
            if not _integer(row['group']) or row['group'] in state.groups or (row['selector'] is not None and not _integer(row['selector'])) or not isinstance(row['indicator_active'], bool) or not all(_integer(row[key], 0, state.sequence) for key in ('event_count', 'kill_count')):
                raise ApplicationPacketError("Invalid synthetic trigger group state")
            state.groups[row['group']] = {key: value for key, value in row.items() if key != 'group'}
        previous = max(0, state.sequence - len(snapshot['events']))
        for event in snapshot['events']:
            if not isinstance(event, dict) or set(event) != {'sequence', 'command', 'group', 'selector', 'indicator_active'}:
                raise ApplicationPacketError("Invalid synthetic trigger event fields")
            if event['sequence'] != previous + 1 or not _integer(event['group']) or event['group'] not in state.groups or event['command'] not in ('event', 'min', 'max', 'indicator_kill') or not isinstance(event['indicator_active'], bool) or (event['selector'] is not None and not _integer(event['selector'])):
                raise ApplicationPacketError("Invalid synthetic trigger event")
            if (event['command'] == 'indicator_kill') != (event['selector'] is None) or event['indicator_active'] != (event['command'] != 'indicator_kill'):
                raise ApplicationPacketError("Inconsistent synthetic trigger event")
            state.events.append(dict(event))
            previous = event['sequence']
        if previous != state.sequence or sum(record['event_count'] + record['kill_count'] for record in state.groups.values()) != state.sequence:
            raise ApplicationPacketError("Inconsistent synthetic trigger event counts")
        return state

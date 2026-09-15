"""Prewritten finite predicate cases, independent of emulation machinery."""
from pathlib import Path
import hashlib
import json

OUT = Path(__file__).resolve().parent
ALL = list(range(1, 32))
def group(address, missing=None):
    return {'address': address, 'level_addresses': [v for v in ALL if v != missing]}

rows = [
    ('disabled-empty', False, None, None, None),
    ('disabled-present-missing', False, group(1, 1), group(2, 17), group(3, 31)),
    ('enabled-empty', True, None, None, None),
    ('enabled-unused', True, group(255, 1), None, group(255, 31)),
    ('on-complete', True, group(1), None, None),
    ('off-complete', True, None, group(2), None),
    ('override-complete', True, None, None, group(3)),
    ('on-missing-first', True, group(1, 1), None, None),
    ('off-missing-middle', True, None, group(2, 17), None),
    ('override-missing-last', True, None, None, group(3, 31)),
    ('on-short-circuits-later', True, group(1, 31), group(2), group(3, 1)),
    ('complete-on-unused-off-missing-override', True, group(1), group(255), group(3, 16)),
]

def expectation(enabled, groups, required):
    events = []
    if required:
        events.append({'event': 'enabled', 'value': enabled})
        if not enabled: return {'value': False, 'semantic_events': events}
    for role in ('on', 'off', 'override'):
        selected = groups[role]
        events.append({'event': 'group', 'role': role, 'present': selected is not None})
        if selected is None: continue
        events.append({'event': 'group', 'role': role, 'present': True})
        events.append({'event': 'address', 'role': role, 'value': selected['address']})
        if selected['address'] == 255: continue
        if not required: return {'value': True, 'semantic_events': events}
        events.append({'event': 'group', 'role': role, 'present': True})
        for address in ALL:
            found = address in selected['level_addresses']
            events.append({'event': 'find', 'role': role, 'address': address, 'create': False, 'found': found})
            if not found: return {'value': True, 'semantic_events': events}
    return {'value': False, 'semantic_events': events}

cases = []
for name, enabled, on, off, override in rows:
    groups = {'on': on, 'off': off, 'override': override}
    cases.append({'id': name, 'enabled': enabled, 'groups': groups,
                  'expected': {'selected': expectation(enabled, groups, False),
                               'required': expectation(enabled, groups, True)}})
raw = (json.dumps(cases, indent=2) + '\n').encode()
with (OUT / 'cases.json').open('xb') as stream: stream.write(raw)
print(json.dumps({'cases': len(cases), 'sha256': hashlib.sha256(raw).hexdigest()}))

"""Extract every Toolkit 1.18 unit/agent/documentor factory registration.

Reads the pinned original EXE/MAP locally. It never loads or executes vendor
code, and the committed receipt contains only hashes, addresses, symbol names,
type literals and derived CSV-report facts. The receipt is the denominator for
database CSV report profiles: every statically registered unit type, its
selected class, its exact-class CGate agent, the report-relevant virtual
methods and whether the Python CLI admits it.

Usage:
    python research/csv_factory_registry_static.py --exe CBusToolkit.exe \
        --map CBusToolkit.map --output research/experiments/2026-09-30/csv-factory-registry-static.json \
        --module src/cbus_toolkit/toolkit_database_csv_registry.py
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

import capstone
import pefile


EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA256 = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
FACTORIES = {
    'unit': 'CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType',
    'documentor': 'CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType',
    'agent': 'CIS_TCustomFlashObject.TFlashAgentFactory.RegisterAgent',
}
DYNAMIC_OWNER = 'CIS_TRegisterExtraUnits.TRegisterExtraUnits.'
AGENT_LOOKUP = 'CIS_TCustomFlashObject.TFlashAgentFactory.GetFlashAgent'
REPORT_SERIALIZER = 'CIS_TCommonCBus.TCBUSUnitManager.AsCSV'
# Unit VMT offsets called by TCBUSUnitManager.AsCSV, relative to the class
# reference (VMT self pointer + 0x58).
UNIT_SLOTS = {'area': 0xEC, 'interaction': 0x10C, 'primary': 0xB0, 'secondary': 0xB4}
DIMMER_PREDICATE = 'CIS_TCBusDimmerUnit.TCBusDimmerUnit.IsInteractionGroup'
RELAY_PREDICATE = 'CIS_TCBus1RelayUnit.TCBus1RelayUnit.IsInteractionGroup'
DIMMER_CHANNEL_SLOT = 0x188
RELAY_CHANNEL_SLOT = 0x160
AGENT_SLOTS = {'agent_load': 0x94, 'load_groups': 0xD4}
CONSTANT_GETTER = bytes.fromhex('558bec83c4f88945fcc745f8')
# TRELDN8B.IsInteractionGroup: unsigned (slot - 8) borrow, i.e. slot < 8.
SLOT_BELOW_8 = bytes.fromhex('558bec83c4f48955f88945fc8b45f883e8080f92c08845f78a45f78be55dc3')
# The admitted Python profiles, as (unit type, pinned firmware, class). The
# class must equal the one selected by the registration covering the firmware.
ADMITTED_MODELS = {
    'TRELAY4': 'Captured cached-object replay: relay predicate max(GetMaxChannels, 6) exposes six slots; native 4.4 shape only.',
    'TKEYEx': 'Nine stored GroupAddress slots; inherited Neo predicate exposes eight; SecondApplicationBlocks selects each slot application.',
    'TST7SENPIRSS': 'Eight stored GroupAddress slots, all visible; SecondApplicationBlocks selects each slot application.',
    'TST7SENPIROA': 'Eight stored GroupAddress slots, all visible; unused secondary application.',
    'TCBusEDLTUnit': 'Sixteen eDLT widget groups (Widget6-21) in stored order; no Area.',
}
DIN_AGENT = 'TDinRailOutputCGateAgent'
REMAP_AGENT = 'TMarshallingBoxCGateAgent'
REMAP_CLASSES = ('TRELDN8', 'TRELDN8SP', 'TRELMB8')
REMAP_INDICES = (1, 2, 3, 4, 7, 8, 9, 10, 11)
RELAY_AGENT = 'TCBus1RelayCGateAgent'
ADMITTED_AGENTS = ('TCBus1RelayCGateAgent', 'TCBusKEYExCGateAgent', DIN_AGENT, REMAP_AGENT,
                   'TCBusST7PIRSensorCGateAgent', 'TCBusEDLTCGateAgent')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def firmware_key(value):
    if type(value) is not str or re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', value) is None:
        return None
    parts = [int(part) for part in value.split('.')]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def firmware_in(value, low, high):
    key, lower, upper = firmware_key(value), firmware_key(low), firmware_key(high)
    return None not in (key, lower, upper) and lower <= key <= upper


class _Image:
    def __init__(self, exe_bytes, map_bytes):
        self.pe = pefile.PE(data=exe_bytes, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        segments = {index: next(self.base + section.VirtualAddress
                                for section in self.pe.sections if section.Name.startswith(name))
                    for index, name in ((1, b'.text'), (2, b'.itext'))}
        self.symbols = {}
        self.by_name = {}
        for line in map_bytes.decode('ascii').splitlines():
            match = re.match(r'^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$', line)
            if match:
                address = int(match[2], 16) + segments[int(match[1])]
                self.symbols.setdefault(address, set()).add(match[3])
                self.by_name.setdefault(match[3], set()).add(address)
        self.starts = sorted(self.symbols)
        self.disassembler = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

    def raw(self, address, length):
        data = self.pe.get_data(address - self.base, length)
        if len(data) != length:
            raise ValueError('Original PE read ended early')
        return data

    def pointer(self, address):
        return struct.unpack('<I', self.raw(address, 4))[0]

    def address(self, name):
        rows = self.by_name.get(name, set())
        if len(rows) != 1:
            raise ValueError('Expected one MAP symbol: ' + name)
        return next(iter(rows))

    def name(self, address):
        rows = self.symbols.get(address)
        return sorted(rows)[0] if rows else None

    def owner(self, address):
        return self.name(self.starts[bisect.bisect_right(self.starts, address) - 1])

    def wide(self, address):
        data = b''
        while len(data) < 256:
            pair = self.raw(address + len(data), 2)
            if pair == b'\0\0':
                return data.decode('utf-16-le')
            data += pair
        raise ValueError(f'Unterminated UTF-16 literal at {address:#x}')

    def class_name(self, reference):
        name = self.name(reference)
        if name is None or '..' not in name:
            raise ValueError(f'Class reference {reference:#x} has no MAP class symbol')
        return name.split('..', 1)[1]

    def method(self, address):
        name = self.name(address)
        return None if name is None else '.'.join(name.split('.')[-2:])

    def calls(self, target):
        found = []
        for section in self.pe.sections:
            if not section.Name.startswith((b'.text', b'.itext')):
                continue
            start, data = self.base + section.VirtualAddress, section.get_data()
            for match in re.finditer(b'\xe8', data):
                offset = match.start()
                if offset + 5 <= len(data) and start + offset + 5 + struct.unpack(
                        '<i', data[offset + 1:offset + 5])[0] == target:
                    found.append(start + offset)
        return found

    def operands(self, call):
        """Resolve eax/ecx/edx sources and pushes in the straight-line block."""
        for back in range(48, 0, -1):
            rows = list(self.disassembler.disasm(self.raw(call - back, back + 5), call - back))
            if rows and rows[-1].address == call and rows[-1].mnemonic == 'call':
                break
        else:
            raise ValueError(f'Cannot synchronise registration block at {call:#x}')
        cut = max((index + 1 for index, row in enumerate(rows[:-1])
                   if row.mnemonic in ('call', 'ret') or row.mnemonic.startswith('j')), default=0)
        state, pushes = {}, []
        for row in rows[cut:-1]:
            if row.mnemonic == 'push' and row.op_str.startswith('0x'):
                pushes.append(int(row.op_str, 16))
            elif row.mnemonic == 'mov':
                target, source = (part.strip() for part in row.op_str.split(',', 1))
                if target not in ('eax', 'ecx', 'edx'):
                    continue
                if source.startswith('dword ptr [0x'):
                    state[target] = ('memory', int(source[11:-1], 16))
                elif source.startswith('0x'):
                    state[target] = ('immediate', int(source, 16))
                elif target == 'eax' and source == 'dword ptr [eax]':
                    state[target] = ('dereference', state.get('eax'))
                else:
                    state[target] = ('dynamic', source)
        return state, pushes


def _report_slots(image, reference):
    vmt = image.pointer(reference)
    if vmt != reference + 0x58:
        raise ValueError(f'Unexpected Delphi class reference at {reference:#x}')
    slots = {name: image.method(image.pointer(vmt + offset)) for name, offset in UNIT_SLOTS.items()}
    predicate = image.pointer(vmt + UNIT_SLOTS['interaction'])
    for predicate_name, offset, kind in ((DIMMER_PREDICATE, DIMMER_CHANNEL_SLOT, 'dimmer'),
                                         (RELAY_PREDICATE, RELAY_CHANNEL_SLOT, 'relay')):
        if image.name(predicate) == predicate_name:
            getter = image.pointer(vmt + offset)
            code = image.raw(getter, 16)
            slots['channel_getter'] = image.method(getter)
            slots['channels'] = (struct.unpack('<I', code[12:])[0]
                                 if code[:12] == CONSTANT_GETTER else None)
            slots['predicate_kind'] = kind
    if 'predicate_kind' not in slots and image.raw(predicate, len(SLOT_BELOW_8)) == SLOT_BELOW_8:
        getter = image.pointer(vmt + DIMMER_CHANNEL_SLOT)
        code = image.raw(getter, 16)
        slots['channel_getter'] = image.method(getter)
        slots['channels'] = (struct.unpack('<I', code[12:])[0]
                             if code[:12] == CONSTANT_GETTER else None)
        slots['predicate_kind'] = 'unsigned_slot_below_8'
    return slots


def _agent_slots(image, reference):
    vmt = image.pointer(reference)
    result = {}
    for name, offset in AGENT_SLOTS.items():
        method = image.method(image.pointer(vmt + offset))
        result[name] = method if method and method.rsplit('.', 1)[-1] in (
            'AgentLoad', 'LoadGroups') else None
    return result


def _visible(slots):
    if slots.get('predicate_kind') == 'relay' and slots.get('channels') is not None:
        return max(slots['channels'], 6)
    if slots.get('predicate_kind') == 'unsigned_slot_below_8':
        return min(8, slots['channels'])
    return slots.get('channels')


def _decision(row, admitted):
    """Return the admitted association model or an explicit refusal reason."""
    klass, agent, slots = row['class'], row['agent'], row['report_slots']
    point = admitted.get((row['unit_type'].upper(), klass))
    if point is not None and firmware_in(point, row['firmware_min'], row['firmware_max']):
        if klass in ADMITTED_MODELS:
            model = ADMITTED_MODELS[klass]
        elif klass in REMAP_CLASSES:
            count = slots['channels']
            model = (f'Sixteen DIN loads, then marshalling-box reload of stored GroupAddress '
                     f'indices {list(REMAP_INDICES[:count])}; all {count} final groups visible.')
        else:
            model = (f'DIN per-channel reload of stored GroupAddress[0:{slots["channels"]}]; '
                     f'all {slots["channels"]} visible, remaining columns unavailable.')
        return {'admitted': True, 'admitted_firmware': point, 'association_model': model}
    if agent is None:
        reason = ('no exact-class CGate agent registration; the report group manager is '
                  'not populated by an admitted loader')
    elif agent == RELAY_AGENT:
        reason = (f'shares {RELAY_AGENT} and the six-slot relay predicate with RELAY4, but the '
                  'admitted RELAY4 profile is a captured shape and this class logic-association '
                  'loader has no admitted native shape')
    elif agent in ADMITTED_AGENTS:
        reason = (f'shares admitted agent {agent}, but no admitted firmware point selects '
                  'this registration')
    else:
        reason = f'agent {agent} has no admitted CSV association model'
    return {'admitted': False, 'refusal_reason': reason}


def source_registry(exe_path, map_path, admitted_profiles):
    exe_bytes, map_bytes = Path(exe_path).read_bytes(), Path(map_path).read_bytes()
    if _sha(exe_bytes) != EXE_SHA256 or _sha(map_bytes) != MAP_SHA256:
        raise ValueError('Toolkit EXE/MAP digest differs from the pinned original')
    image = _Image(exe_bytes, map_bytes)
    targets = {kind: image.address(name) for kind, name in FACTORIES.items()}
    sites = {kind: image.calls(address) for kind, address in targets.items()}

    agents, documentors, units, dynamic = {}, {}, [], []
    for call in sites['agent']:
        state, _ = image.operands(call)
        if state.get('ecx', ('',))[0] != 'memory' or state.get('edx', ('',))[0] != 'memory':
            raise ValueError(f'Unparsed agent registration at {call:#x}')
        unit_class = image.class_name(state['edx'][1])
        # GetFlashAgent linearly scans registrations and returns the first
        # exact class match; the receipt proves every class has at most one.
        if unit_class in agents:
            raise ValueError('Duplicate agent registration for ' + unit_class)
        agents[unit_class] = (image.class_name(state['ecx'][1]), state['ecx'][1], call)
    for kind in ('unit', 'documentor'):
        for call in sites[kind]:
            state, pushes = image.operands(call)
            if state.get('ecx', ('',))[0] != 'memory' or state.get('edx', ('',))[0] != 'immediate':
                if kind == 'unit' and image.owner(call).startswith(DYNAMIC_OWNER):
                    dynamic.append({'callsite': hex(call), 'owner': image.owner(call),
                                    'source': 'runtime unit-type INI; type/class not static'})
                    continue
                raise ValueError(f'Unparsed {kind} registration at {call:#x}')
            if len(pushes) < 2:
                raise ValueError(f'Missing firmware bounds at {call:#x}')
            row = {'unit_type': image.wide(state['edx'][1]),
                   'firmware_min': image.wide(pushes[-2]),
                   'firmware_max': image.wide(pushes[-1]),
                   'class_reference': state['ecx'][1], 'callsite': hex(call)}
            if kind == 'unit':
                units.append(row)
            else:
                documentors.setdefault(row['unit_type'].upper(), []).append(
                    [image.class_name(row['class_reference']), row['firmware_min'],
                     row['firmware_max']])

    admitted = {(kind.upper(), klass): firmware for kind, firmware, klass in admitted_profiles}
    registrations = []
    for row in units:
        klass = image.class_name(row['class_reference'])
        agent = agents.get(klass)
        result = {
            'unit_type': row['unit_type'], 'firmware_min': row['firmware_min'],
            'firmware_max': row['firmware_max'], 'class': klass,
            'class_registration': row['callsite'],
            'agent': agent[0] if agent else None,
            'agent_registration': hex(agent[2]) if agent else None,
            'agent_methods': _agent_slots(image, agent[1]) if agent else None,
            'documentors': documentors.get(row['unit_type'].upper(), []),
            'report_slots': _report_slots(image, row['class_reference']),
        }
        visible = _visible(result['report_slots'])
        if visible is not None:
            result['report_slots']['visible_groups'] = visible
        result.update(_decision(result, admitted))
        registrations.append(result)

    for kind, firmware, klass in admitted_profiles:
        if not any(row['admitted'] and row['unit_type'].upper() == kind.upper()
                   and row['class'] == klass and firmware_in(firmware, row['firmware_min'],
                                                             row['firmware_max'])
                   for row in registrations):
            raise ValueError(f'Admitted {kind} {firmware} {klass} has no matching registration')

    types = sorted({row['unit_type'].upper() for row in registrations})
    admitted_types = sorted({row['unit_type'].upper() for row in registrations if row['admitted']})
    by_agent = Counter(row['agent'] for row in registrations if not row['admitted'])
    return {
        'format': 'cbus-toolkit-csv-factory-registry-static-v1',
        'original_execution': False,
        'original_inputs': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'factories': {kind: {'method': FACTORIES[kind], 'address': hex(targets[kind]),
                             'callsites': len(sites[kind])} for kind in FACTORIES},
        'report_path': {
            'serializer': REPORT_SERIALIZER,
            'serializer_address': hex(image.address(REPORT_SERIALIZER)),
            'unit_vmt_slots': {name: hex(offset) for name, offset in UNIT_SLOTS.items()},
            'agent_lookup': AGENT_LOOKUP,
            'agent_lookup_rule': 'first exact-class registration; no parent-class fallback',
            'agent_vmt_slots': {name: hex(offset) for name, offset in AGENT_SLOTS.items()},
            'dimmer_predicate': 'zero-based slot < GetMaxChannels (VMT 0x188)',
            'relay_predicate': 'zero-based slot < max(GetMaxChannels (VMT 0x160), 6)',
            'din_loader': ('TBasicDinRailOutputCGateAgent.LoadGroups: when GroupAddress is '
                           'non-empty and the primary application resolves, clear the report '
                           'group manager and append one group per channel from GroupAddress[0:channels]'),
            'marshalling_loader': ('TMarshallingBoxCGateAgent.LoadGroups: after the DIN loader, '
                                   'for TRELMB8 or TRELDN8 (including TRELDN8SP) clear again and append '
                                   'stored indices 1-4 then 7-11 while channels remain'),
        },
        'summary': {
            'static_registrations': len(registrations),
            'dynamic_registration_sites': len(dynamic),
            'unit_types': len(types),
            'admitted_types': len(admitted_types),
            'admitted_registrations': sum(row['admitted'] for row in registrations),
            'unadmitted_types': len(set(types) - set(admitted_types)),
            'agent_registrations': len(agents),
            'documentor_registrations': len(sites['documentor']),
            'unadmitted_registrations_by_agent': dict(sorted(
                ((agent or '<none>'), count) for agent, count in by_agent.items())),
        },
        'admitted_types': admitted_types,
        'unregistered_fallback': {'OWNED_UNKNOWN': 'no factory registration; generic TCBusUnitGeneric capture'},
        'dynamic_registrations': dynamic,
        'registrations': registrations,
        'limits': [
            'Static EXE/MAP extraction only; no original Toolkit code was executed.',
            'Runtime INI registrations through TRegisterExtraUnits are not enumerable statically.',
            'Factory selection among overlapping registrations (for example KEYGL5) is not modelled here; admitted profiles name the class their own review pins.',
            'Admission requires the exact class and agent of an already implemented profile; the synthetic firmware point is within the registration range but is not a device firmware claim.',
        ],
    }


def dumps(receipt):
    """Stable JSON with one line per registration."""
    head = dict(receipt, registrations=None)
    text = json.dumps(head, indent=1)
    rows = ',\n'.join('  ' + json.dumps(row, separators=(',', ':'))
                       for row in receipt['registrations'])
    return text.replace('"registrations": null', '"registrations": [\n' + rows + '\n ]') + '\n'


def registry_module(receipt):
    rows = [(row['unit_type'], row['firmware_min'], row['firmware_max'], row['class'],
             row['agent'] or '', '' if row['admitted'] else row['refusal_reason'])
            for row in receipt['registrations']]
    body = ''.join(f'    {row!r},\n' for row in rows)
    return f'''"""Toolkit 1.18 unit-factory registry for database CSV profile refusals.

Generated by research/csv_factory_registry_static.py from the pinned original
EXE/MAP (receipt research/experiments/2026-09-30/csv-factory-registry-static.json).
Do not edit by hand. Each row is (unit type, firmware min, firmware max,
selected class, exact-class CGate agent, refusal reason or '' when admitted).
"""
from __future__ import annotations

import re


REGISTRATIONS = (
{body})


def _firmware(value):
    if type(value) is not str or re.fullmatch(r'[0-9]+(?:\\.[0-9]+)*', value) is None:
        return None
    parts = [int(part) for part in value.split('.')]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def registrations_for(unit_type, firmware=None):
    """Static registrations for a type, optionally limited to one firmware."""
    kind = unit_type.upper() if type(unit_type) is str else ''
    rows = [row for row in REGISTRATIONS if row[0].upper() == kind]
    key = _firmware(firmware)
    if key is not None:
        rows = [row for row in rows if None not in (_firmware(row[1]), _firmware(row[2]))
                and _firmware(row[1]) <= key <= _firmware(row[2])]
    return tuple(rows)


def refusal_reason(unit_type, firmware):
    """Explain why a type/firmware is outside the admitted CSV profiles."""
    rows = registrations_for(unit_type, firmware)
    if not rows:
        if registrations_for(unit_type):
            return (f'Toolkit 1.18 registers {{unit_type}} but no static registration covers '
                    f'firmware {{firmware}}')
        return f'{{unit_type}} has no static Toolkit 1.18 unit-factory registration'
    reasons = []
    for kind, low, high, klass, agent, reason in rows:
        detail = reason or 'admitted only at its pinned firmware and stored shape'
        reasons.append(f'registry {{kind}} {{low}}-{{high}} -> {{klass}}/'
                       f'{{agent or "no agent"}}: {{detail}}')
    return '; '.join(reasons)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--module', type=Path)
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from cbus_toolkit.toolkit_database_csv_projection import admitted_profiles
    receipt = source_registry(args.exe, args.map, admitted_profiles())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(receipt), encoding='utf-8')
    if args.module:
        args.module.write_text(registry_module(receipt), encoding='utf-8')


if __name__ == '__main__':
    main()

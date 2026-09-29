"""Compare ST7 sensor PP layouts and pin the Toolkit class for each sensor type.

This reads private decoded unit specifications, C-Gate's catalogue and the
Toolkit 1.18 EXE/MAP locally, and executes no vendor instructions. The receipt
contains digests, counts, class names and verdicts only: no parameter
descriptions, defaults or other specification content. Keep the vendor inputs
outside Git.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

import capstone
import pefile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cbus_toolkit.sensors import LAYOUTS  # noqa: E402
from cbus_toolkit.unitspec import (  # noqa: E402
    UnitCatalog, UnitSpecStore, _integer, compare_versions)


EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA256 = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
REFERENCE = 'SENPILL_ST7.xml'
SENSOR_TYPES = ('SENPILL', 'SENPIROA', 'SENPIRIA', 'SENPIRIB', 'SENPIRSS', 'SENPIR',
                'SENSOR', 'SENLL', 'SENPILLA', 'SENPIRIC', 'SENLLA', 'PE_CELL')
# Every sensor specification sharing the SENPILL/SENPIR/SENLL naming, including
# include-only bases that declare Type "SENPILL" but are never catalogued.
SPEC_PATTERN = re.compile(r'^SEN(PILL|PIR|LL)[A-Z0-9_]*\.xml$')
REGISTRATION_UNITS = ('CIS_TSENPILL', 'CIS_TSENPILLA', 'CIS_TSENPIRSS', 'CIS_TSENPIRIC',
                      'CIS_TSENPIR', 'CIS_TSENLL', 'CIS_TSENLLA')
ADMITTED_CLASS = 'TST7SENPILL'
ADMITTED_AGENT = 'TCBusST7MultisensorCGateAgent'
PIR_AGENT = 'CIS_TCBusST7SensorCGateAgent.TCBusST7PIRSensorCGateAgent'
LAYOUT_FIELDS = ('ArraySize', 'BitSize', 'BitAddress', 'ArraySkip', 'MinValue', 'MaxValue')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def version_key(version):
    if not re.fullmatch(r'[0-9]+(\.[0-9]+)*', version):
        raise ValueError('Unexpected version literal')
    return tuple(int(part) for part in version.split('.'))


def layout(parameter):
    fields = parameter.fields
    return [parameter.type, parameter.address,
            *(_integer(fields[name]) if fields.get(name, '').strip() else None for name in LAYOUT_FIELDS),
            fields.get('Protection', '').strip().lower()]


def spec_review(store, directory):
    reference = store.load(REFERENCE)
    ref_layout = {name: layout(p) for name, p in reference.parameters.items()}
    specs, hashes = {}, {}
    for path in sorted(directory.iterdir()):
        if not SPEC_PATTERN.match(path.name):
            continue
        spec = store.load(path.name)
        for source in spec.sources:
            hashes[source] = digest((directory / source).read_bytes())
        current = {name: layout(p) for name, p in spec.parameters.items()}
        shared = set(current) & set(ref_layout)
        workflow = {name: current.get(name) for name in LAYOUTS}
        specs[path.name] = {
            'declared_type': spec.unit_type,
            'include_chain': list(spec.sources),
            'parameter_count': len(current),
            'layout_sha256': canonical(current),
            'workflow_layout_sha256': canonical(workflow),
            'parameters_added': len(set(current) - set(ref_layout)),
            'parameters_removed': len(set(ref_layout) - set(current)),
            'parameters_changed': sum(current[name] != ref_layout[name] for name in shared),
            'defaults_changed': sum(spec.parameters[name].default != reference.parameters[name].default
                                    for name in shared),
            'full_layout_equal': current == ref_layout,
            'workflow_fields_equal': workflow == {name: ref_layout[name] for name in LAYOUTS},
        }
    return specs, hashes


class Toolkit:
    def __init__(self, exe_path, map_path):
        exe, symbols = exe_path.read_bytes(), map_path.read_bytes()
        if digest(exe) != EXE_SHA256 or digest(symbols) != MAP_SHA256:
            raise ValueError('Toolkit EXE/MAP digest differs from the pinned original')
        self.image = pefile.PE(data=exe, fast_load=True)
        self.base = self.image.OPTIONAL_HEADER.ImageBase
        segments = {index: next(self.base + section.VirtualAddress for section in self.image.sections
                                if section.Name.startswith(name))
                    for index, name in ((1, b'.text'), (2, b'.itext'))}
        self.symbols, self.names = {}, {}
        for line in symbols.decode('ascii').splitlines():
            match = re.match(r'^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$', line)
            if match:
                address = int(match[2], 16) + segments[int(match[1])]
                self.symbols.setdefault(address, match[3])
                self.names.setdefault(match[3], address)
        self.starts = sorted(self.symbols)
        self.decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

    def raw(self, address, length):
        value = self.image.get_data(address - self.base, length)
        if len(value) != length:
            raise ValueError('Original PE read ended early')
        return value

    def u32(self, address):
        return struct.unpack('<I', self.raw(address, 4))[0]

    def literal(self, address):
        # Delphi UnicodeString constant: codepage 1200, element size 2, refcount -1.
        try:
            codepage, size, count, length = struct.unpack('<HHiI', self.raw(address - 12, 12))
        except pefile.PEFormatError as error:
            raise ValueError(f'No string literal at {address:#x}') from error
        if (codepage, size, count) != (1200, 2, -1) or not 0 < length < 64:
            raise ValueError(f'No string literal at {address:#x}')
        return self.raw(address, 2 * length).decode('utf-16le')

    def code(self, name):
        start = self.names[name]
        end = self.starts[bisect.bisect_right(self.starts, start)]
        if end - start > 0x4000:
            raise ValueError('Original method span exceeds the static bound')
        return list(self.decoder.disasm(self.raw(start, end - start), start)), digest(self.raw(start, end - start))

    def target(self, instruction):
        operand = instruction.op_str
        return int(operand, 16) if operand.startswith('0x') else None

    def class_name(self, symbol_address):
        vmt = symbol_address + 0x58
        name = self.raw(self.u32(vmt - 0x38), 64)
        return name[1:1 + name[0]].decode('ascii')

    def ancestry(self, symbol_address, *, full=False):
        result, vmt = [], symbol_address + 0x58
        while True:
            result.append(self.class_name(vmt - 0x58))
            parent = self.u32(vmt - 0x30)
            if not parent:
                return result
            if not full and result[-1] in ('TCBusST7MultisensorUnit', 'TCBusST7MultisensorCGateAgent'):
                return result  # The ST7 sensor bases share every older ancestor.
            vmt = self.u32(parent)

    @staticmethod
    def memory_operand(instruction):
        match = re.fullmatch(r'dword ptr \[(0x[0-9a-f]+)\]', instruction.op_str.split(', ', 1)[-1])
        return int(match[1], 16) if match else None

    def registrations(self):
        register = self.names['CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType']
        rows, spans = [], {}
        for unit in REGISTRATION_UNITS:
            code, spans[unit] = self.code(unit + '.' + unit)
            pushes, unit_class, unit_type = [], None, None
            for ins in code:
                if ins.mnemonic == 'push' and ins.op_str.startswith('0x'):
                    pushes.append(int(ins.op_str, 16))
                elif ins.mnemonic == 'mov' and ins.op_str.startswith('ecx, dword ptr ['):
                    unit_class = self.memory_operand(ins)
                elif ins.mnemonic == 'mov' and re.fullmatch(r'edx, 0x[0-9a-f]+', ins.op_str):
                    unit_type = int(ins.op_str.split(', ')[1], 16)
                elif ins.mnemonic == 'call':
                    if self.target(ins) == register:
                        # Delphi register convention: EDX type, ECX class, then
                        # the two stack arguments in declaration order.
                        minimum, maximum = pushes[-2:]
                        rows.append({'unit_type': self.literal(unit_type),
                                     'firmware_min': self.literal(minimum),
                                     'firmware_max': self.literal(maximum),
                                     'class': self.class_name(unit_class),
                                     'ancestry': self.ancestry(unit_class),
                                     'callsite': hex(ins.address)})
                    pushes, unit_class, unit_type = [], None, None
        return rows, spans

    def agents(self):
        register = self.names['CIS_TCustomFlashObject.TFlashAgentFactory.RegisterAgent']
        name = 'CIS_TCBusST7SensorCGateAgent.CIS_TCBusST7SensorCGateAgent'
        code, span = self.code(name)
        rows, agent, unit = [], None, None
        for ins in code:
            if ins.mnemonic == 'mov' and ins.op_str.startswith('ecx, dword ptr ['):
                agent = self.memory_operand(ins)
            elif ins.mnemonic == 'mov' and ins.op_str.startswith('edx, dword ptr ['):
                unit = self.memory_operand(ins)
            elif ins.mnemonic == 'call' and self.target(ins) == register:
                rows.append({'unit_class': self.class_name(unit), 'agent_class': self.class_name(agent),
                             'agent_ancestry': self.ancestry(agent), 'callsite': hex(ins.address)})
        return rows, span

    def members(self, agent_symbol):
        """Resolve agent member offsets to C-Gate parameter names, base first."""
        chain = list(reversed(self.ancestry(self.names[agent_symbol], full=True)))
        result = {}
        for class_name in chain:
            create = next((symbol for symbol in self.names
                           if symbol.endswith('.' + class_name + '.InternalCreate')), None)
            if create is None:
                continue
            code, _ = self.code(create)
            text = None
            for index, ins in enumerate(code):
                if ins.mnemonic in ('push', 'mov') and re.search(r'(^|, )0x[0-9a-f]{6,8}$', ins.op_str):
                    try:
                        text = self.literal(int(ins.op_str.split(', ')[-1], 16))
                    except ValueError:
                        pass
                match = re.fullmatch(r'dword ptr \[e[a-d]x \+ (0x[0-9a-f]+)\], eax', ins.op_str)
                if ins.mnemonic == 'mov' and match:
                    caller = code[index - 2] if index >= 2 else None
                    helper = self.symbols.get(self.target(caller)) if caller is not None and caller.mnemonic == 'call' else None
                    if helper and '.CreateAttribute' in helper:
                        result[int(match[1], 16)] = helper.rsplit('.CreateAttribute', 1)[1]
                    elif text:
                        result[int(match[1], 16)] = text
                    text = None
                rename = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', ins.op_str)
                following = code[index + 1] if index + 1 < len(code) else None
                if (ins.mnemonic == 'mov' and rename and text and following is not None
                        and self.symbols.get(self.target(following), '').endswith('.SetName')):
                    result[int(rename[1], 16)] = text
                    text = None
        return result

    def pir_save(self):
        before, before_hash = self.code(PIR_AGENT + '.BeforeSaveProgrammingInformation')
        calls = [self.symbols.get(self.target(ins), hex(self.target(ins) or 0)) for ins in before
                 if ins.mnemonic == 'call' and self.target(ins) is not None]
        members = self.members('CIS_TCBusST7SensorCGateAgent..TCBusST7PIRSensorCGateAgent')
        conditional, text = [], None
        for ins in before:
            if ins.mnemonic == 'mov' and re.fullmatch(r'edx, 0x[0-9a-f]{6,8}', ins.op_str):
                text = self.literal(int(ins.op_str.split(', ')[1], 16))
            member = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', ins.op_str)
            if ins.mnemonic == 'mov' and member and text is not None:
                conditional.append({'parameter': members.get(int(member[1], 16), member[1]), 'value': text.strip(),
                                    'condition': 'PIR unit flag loaded from IndicatorBlockAssignment[0] == 7'})
                text = None
        forced_code, forced_hash = self.code(PIR_AGENT + '.PrepareForcedParameters')
        forced, value, index_value = [], None, None
        for position, ins in enumerate(forced_code):
            if ins.mnemonic == 'mov' and re.fullmatch(r'edx, 0x[0-9a-f]+|dl, [01]|edx, [0-9]+', ins.op_str):
                value = int(ins.op_str.split(', ')[1], 0)
            elif ins.mnemonic == 'xor' and ins.op_str in ('edx, edx', 'dl, dl'):
                value = 0
            elif ins.mnemonic == 'xor' and ins.op_str == 'ecx, ecx':
                index_value = 0
            member = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', ins.op_str)
            if ins.mnemonic == 'mov' and member and value is not None and position + 1 < len(forced_code):
                offset, following = int(member[1], 16), forced_code[position + 1]
                name = members.get(offset, 'member ' + hex(offset))
                helper = self.symbols.get(self.target(following), '')
                if following.op_str == 'ecx, dword ptr [eax]':
                    forced.append({'parameter': name, 'value': value})
                elif helper.endswith('.SetArrayInteger') and index_value is not None:
                    forced.append({'parameter': name, 'index': value, 'value': index_value})
                elif re.fullmatch(r'byte ptr \[eax \+ 0x58\], 0', following.op_str):
                    forced.append({'parameter': name, 'attribute_flag_0x58': 0})
        pir_unit = 'CIS_TCBusST7SensorUnit.TCBusST7PIRSensorUnit.'
        limits = {}
        for method in ('MaximumBlockCount', 'MaximumIndicatorCount'):
            code, _ = self.code(pir_unit + method)
            stores = [int(ins.op_str.split(', ')[1], 0) for ins in code
                      if ins.mnemonic == 'mov' and ins.op_str.startswith('dword ptr [ebp - 8], ')]
            if len(stores) != 1:
                raise ValueError('Unexpected constant method shape: ' + method)
            limits[method] = stores[0]
        return {'before_save_calls': calls, 'before_save_sha256': before_hash,
                'conditional_writes': conditional,
                'prepare_forced_parameters_sha256': forced_hash, 'forced': forced,
                'pir_unit_constants': limits}

    def firmware_scan(self, unit_symbol, agent_symbol):
        """Find class methods in the admitted ancestry that compare firmware."""
        classes = (set(self.ancestry(self.names[unit_symbol], full=True))
                   | set(self.ancestry(self.names[agent_symbol], full=True)))
        compare = self.names['CIS_Strings.VersionStringCompare']
        hits = []
        for start in self.starts:
            parts = self.symbols[start].split('.')
            if len(parts) < 3 or parts[1] not in classes:
                continue
            end = self.starts[bisect.bisect_right(self.starts, start)]
            if end - start > 0x20000:
                continue
            code = list(self.decoder.disasm(self.raw(start, end - start), start))
            for position, ins in enumerate(code):
                if ins.mnemonic == 'call' and self.target(ins) == compare:
                    thresholds = []
                    for previous in code[max(0, position - 3):position]:
                        if previous.mnemonic == 'mov' and re.fullmatch(r'edx, 0x[0-9a-f]+', previous.op_str):
                            thresholds.append(self.literal(int(previous.op_str.split(', ')[1], 16)))
                    method = parts[2]
                    override = next((symbol for symbol in self.names if symbol.endswith('.' + ADMITTED_CLASS + '.' + method)
                                     or symbol.endswith('.TCBusST7MultisensorUnit.' + method)), None)
                    hits.append({'method': '.'.join(parts[1:]), 'thresholds': thresholds,
                                 'overridden_by': override.split('.', 1)[1] if override else None})
        return {'classes_scanned': len(classes), 'version_comparisons': hits}


def overlap(first, second):
    low = max(first[0], second[0], key=version_key)
    high = min(first[1], second[1], key=version_key)
    return (low, high) if version_key(low) <= version_key(high) else None


def decide(catalogue, specs, registrations, agents):
    agent_for = {row['unit_class']: row['agent_class'] for row in agents}
    decisions = []
    for row in catalogue:
        spec = specs.get(row['spec'])
        segments = []
        for registration in registrations:
            if registration['unit_type'] != row['unit_type']:
                continue
            span = overlap((row['firmware_min'], row['firmware_max']),
                           (registration['firmware_min'], registration['firmware_max']))
            if span:
                segments.append({'firmware_min': span[0], 'firmware_max': span[1],
                                 'toolkit_class': registration['class'],
                                 'toolkit_agent': agent_for.get(registration['class'])})
        segments.sort(key=lambda segment: version_key(segment['firmware_min']))
        if not segments:
            segments = [{'firmware_min': row['firmware_min'], 'firmware_max': row['firmware_max'],
                         'toolkit_class': None, 'toolkit_agent': None}]
        elif version_key(segments[-1]['firmware_max']) < version_key(row['firmware_max']):
            # Catalogued firmware above the last Toolkit registration, such as
            # SENPILL 2.3.10..2.3.99 after TST7SENPILL's 2.3.9 maximum.
            segments.append({'firmware_above': segments[-1]['firmware_max'], 'firmware_max': row['firmware_max'],
                             'toolkit_class': None, 'toolkit_agent': None})
        for segment in segments:
            if spec is None:
                reason = 'specification-absent'
            elif not spec['workflow_fields_equal']:
                reason = 'workflow-layout-differs'
            elif not spec['full_layout_equal']:
                reason = 'layout-superset-or-changed'
            elif segment['toolkit_class'] is None:
                reason = 'no-toolkit-registration'
            elif (segment['toolkit_class'], segment['toolkit_agent']) != (ADMITTED_CLASS, ADMITTED_AGENT):
                reason = 'different-toolkit-class'
            else:
                reason = None
            decisions.append({**{key: row[key] for key in ('unit_type', 'catalog_number', 'spec')},
                              **segment, 'admitted': reason is None, 'refusal': reason})
    return decisions


def review(spec_dir, catalogue_path, exe_path, map_path):
    store = UnitSpecStore(spec_dir)
    specs, spec_hashes = spec_review(store, Path(spec_dir))
    catalogue_bytes = Path(catalogue_path).read_bytes()
    rows = sorted({(r['unit_type'], r['catalog_number'], r['minimum_version'], r['maximum_version'], r['spec_filename'])
                   for r in UnitCatalog.load(catalogue_path).records if r['unit_type'] in SENSOR_TYPES},
                  key=lambda r: (r[0], r[1], version_key(r[2])))
    catalogue = [dict(zip(('unit_type', 'catalog_number', 'firmware_min', 'firmware_max', 'spec'), row)) for row in rows]
    for name, spec in specs.items():
        spec['catalogued_as'] = sorted({row['unit_type'] for row in catalogue if row['spec'] == name})
    toolkit = Toolkit(Path(exe_path), Path(map_path))
    registrations, registration_spans = toolkit.registrations()
    agents, agent_span = toolkit.agents()
    decisions = decide(catalogue, specs, registrations, agents)
    # Consistency with C-Gate: every compared firmware string uses the same
    # numeric '.'-token order as Toolkit's VersionStringCompare.
    for row in decisions:
        compare_versions(row.get('firmware_min', row.get('firmware_above')), row['firmware_max'])
    return {
        'format': 'cbus-sensor-profile-review-v1',
        'original_execution': False,
        'inputs': {'unitspec_sha256': dict(sorted(spec_hashes.items())),
                   'cbusunits.xml': digest(catalogue_bytes),
                   'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'reference': {'spec': REFERENCE, 'workflow_fields': len(LAYOUTS),
                      'layout_fields': ['Type', 'Address', *LAYOUT_FIELDS, 'Protection']},
        'specs': specs,
        'toolkit': {
            'version_compare': 'CIS_Strings.VersionStringCompare: numeric StrToIntDef per "." token',
            'registration_initializer_sha256': registration_spans,
            'registrations': registrations,
            'agent_registration_sha256': agent_span,
            'agents': agents,
            'pir_save': toolkit.pir_save(),
            'admitted_class_firmware_scan': toolkit.firmware_scan('CIS_TSENPILL..TST7SENPILL',
                                                                  'CIS_TCBusST7SensorCGateAgent..TCBusST7MultisensorCGateAgent'),
        },
        'decisions': decisions,
        'limits': [
            'Static decoded-specification, catalogue and original EXE/MAP analysis; no original Toolkit GUI or dialog was executed.',
            'Layout equality compares names, type, address, array/bit geometry, protection and min/max; defaults and descriptions are counted separately.',
            'Toolkit class assignment is read from the unit-factory registrations and agent registrations, not from a running project.',
            'The firmware scan covers direct VersionStringCompare calls in class methods of the admitted unit and agent ancestry only.',
            'No native C-Gate, CNI, PCI or physical sensor was used by this review.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unitspec-dir', type=Path, required=True)
    parser.add_argument('--catalogue', type=Path, required=True, help='C-Gate unitspec/cbusunits.xml')
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = review(args.unitspec_dir, args.catalogue, args.exe, args.map)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

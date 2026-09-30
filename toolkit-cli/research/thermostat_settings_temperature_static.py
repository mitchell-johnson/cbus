"""Recover thermostat temperature load/save composition from pinned originals.

The EXE/MAP are read but never executed. Every scalar expected value is joined
from the committed original-instruction fixture; production conversion code is
not imported or used as an oracle. Optional output contains all 256 raw bytes,
both explicit global temperature preferences and nine distinct round trips.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thermostat_post_load_static import _Walker  # noqa: E402
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/thermostat-temperature-vectors.json'
FIXTURE_SHA256 = '188050a51a4324b0039dba68383a66d528baabcfe88210b3634ba1f372fd31d0'
AGENT = 'CIS_TCBusThermostatCGateAgent.'
BASE = AGENT + 'TCBusThermostatCGateAgent.'
BASIC = AGENT + 'TCBusBasicThermostatCGateAgent.'
PROGRAMMABLE = AGENT + 'TCBusProgrammableThermostatCGateAgent.'
MODEL = 'CIS_TThermostat.'
LOAD, SAVE = 'AfterLoadProgrammingInformation', 'BeforeSaveProgrammingInformation'

# Original agent PP slots, model owners, conversion profiles, and signed-byte
# handling are independent source transcriptions, verified below.
FIELDS = (
    ('MaximumSetTemperature', 0x12c, 'TZoneManagerService', 'simple_signed'),
    ('MinimumSetTemperature', 0x130, 'TZoneManagerService', 'simple_signed'),
    ('GuardUpperTemperature', 0x138, 'TZoneManagerService', 'guard_upper_signed'),
    ('GuardMaximumUpperTemperature', 0x13c, 'TZoneManagerService', 'guard_upper_signed'),
    ('GuardMinimumUpperTemperature', 0x140, 'TZoneManagerService', 'guard_signed'),
    ('GuardLowerTemperature', 0x144, 'TZoneManagerService', 'guard_signed'),
    ('GuardMaximumLowerTemperature', 0x148, 'TZoneManagerService', 'guard_signed'),
    ('GuardMinimumLowerTemperature', 0x14c, 'TZoneManagerService', 'guard_signed'),
    ('SetbackLevel', 0x15c, 'TZoneManagerService', 'shifted_offset_signed'),
    ('EvapStartProportionalTemperature', 0x160, 'TZoneManagerService', 'offset_signed'),
    ('EvapStopProportionalTemperature', 0x164, 'TZoneManagerService', 'offset_signed'),
    ('TemperatureOffset', 0x260, 'TTemperatureMeasurementService', 'special_quarter_signed'),
    ('TemperatureSendDifferential', 0x268, 'TTemperatureMeasurementService', 'special_quarter_unsigned'),
    ('EvapComfortStartTemp', 0x294, 'TUIService', 'whole_unsigned'),
    ('EvapComfortStepSize', 0x298, 'TUIService', 'half_offset_unsigned'),
)
PROFILES = {
    'simple_signed': ('SimpleCGateTempToUnitTemp', 'SimpleUnitTempToCGateTemp', True, False),
    'guard_upper_signed': ('CGateTempToUnitTemp', 'UnitTempToCGateTemp', True, True),
    'guard_signed': ('CGateTempToUnitTemp', 'UnitTempToCGateTemp', True, False),
    'shifted_offset_signed': ('CGateTempToTempOffsetWithShift', 'TempOffsetWithShiftToCGateTemp', True, False),
    'offset_signed': ('CGateTempToTempOffset', 'TempOffsetToCGateTemp', True, False),
    'special_quarter_signed': ('CGate16thDegreeToQuarterDegreeTempOffset',
                              'QuarterDegreesTempOffsetToCGateTemp', True, False),
    'special_quarter_unsigned': ('CGate16thDegreeToQuarterDegreeTempOffset',
                                'QuarterDegreesTempOffsetToCGateTemp', False, False),
    'whole_unsigned': ('CGateTempToWholeDegreesTemp', 'WholeDegreesTempToCGateTemp', False, False),
    'half_offset_unsigned': ('CGateTempToHalfDegreesTempOffset',
                            'HalfDegreesTempOffsetToCGateTemp', False, False),
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def _call_index(rows, symbol):
    matches = [index for index, (_a, mnemonic, _op, note) in enumerate(rows)
               if mnemonic == 'call' and note == symbol]
    if len(matches) != 1:
        raise ValueError('Expected exactly one call to ' + symbol)
    return matches[0]


def _attribute_definitions(image, rows):
    result = {}
    for index, (address, mnemonic, _op, note) in enumerate(rows):
        if mnemonic != 'call' or note != 'CIS_TCustomFlashObject.TFlashAttribute.Create':
            continue
        previous = rows[max(0, index - 12):index]
        literals = [(a, image.literal(int(op, 16))) for a, m, op, _n in previous
                    if m == 'push' and re.fullmatch('0x[0-9a-f]+', op)]
        literals = [(a, literal) for a, literal in literals if literal is not None]
        if not literals:
            continue
        name = literals[-1][1]
        store = next((re.fullmatch(r'dword ptr \[edx \+ (0x[0-9a-f]+)\], eax', op)
                      for _a, m, op, _n in rows[index + 1:index + 4] if m == 'mov' and op.startswith('dword')),
                     None)
        if store is None:
            raise ValueError('Missing created attribute destination: ' + name)
        classes = [n for _a, m, _op, n in previous if m == 'mov' and '..T' in n]
        result[name] = {'slot': int(store[1], 16), 'class': classes[-1], 'create': address}
    return result


def original_vectors():
    raw = FIXTURE.read_bytes()
    if _sha(raw) != FIXTURE_SHA256:
        raise ValueError('Original arithmetic fixture hash mismatch')
    fixture = json.loads(raw)
    if fixture['original_executable_sha256'] != EXE_SHA256:
        raise ValueError('Original arithmetic fixture executable differs')
    methods = fixture['methods']
    captured = {(methods[index], fahrenheit, value): expected
                for index, fahrenheit, value, expected in fixture['extended_original_emulator']}
    if len(captured) != 28840:
        raise ValueError('Original instruction fixture has missing/duplicate cases')
    for index, fahrenheit, value, expected in fixture['native_windows_original']:
        key = (methods[index], fahrenheit, value)
        if key in captured and captured[key] != expected:
            raise ValueError('Native and instruction-engine captures disagree')
        captured[key] = expected
    profiles = {}
    for name, (load, save, signed, cap_127) in PROFILES.items():
        rows = []
        for fahrenheit in (False, True):
            for raw in range(256):
                incoming = raw - 256 if signed and raw >= 128 else raw
                loaded = captured[load, fahrenheit, incoming]
                converted = captured[save, fahrenheit, loaded]
                limited = min(converted, 127) if cap_127 else converted
                stored = limited & 255 if signed else limited
                rows.append([fahrenheit, raw, loaded, converted, stored])
        profiles[name] = {'load_method': load, 'save_method': save, 'signed_input': signed,
                          'upper_127_cap_after_save_conversion': cap_127,
                          'save_encoding': 'low_unsigned_byte' if signed else 'integer_without_byte_cast',
                          'rows': rows}
    return {
        'format': 'cbus-thermostat-settings-temperature-roundtrips-v1',
        'source_fixture': 'thermostat-temperature-vectors.json',
        'source_fixture_sha256': FIXTURE_SHA256,
        'original_executable_sha256': EXE_SHA256,
        'expected_values_from': 'composition of captured original arithmetic rows plus source-pinned casts',
        'production_conversion_oracle_used': False,
        'row_fields': ['fahrenheit', 'raw_pp_byte', 'loaded_model_integer', 'converted_save_integer',
                       'saved_pp_integer'],
        'fields': {field: profile for field, _slot, _owner, profile in FIELDS},
        'profiles': profiles,
    }


def inspect(exe, map_path):
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image, checks, routines, cache = _Image(exe_raw, map_raw), {}, {}, {}
    walker = _Walker(image)

    def method(name):
        if name not in cache:
            rows, _tables, digest = walker.listing(name)
            cache[name] = rows
            routines[name] = {'address': hex(image.by_name[name]), 'sha256': digest}
        return cache[name]

    agent_definitions = {prefix: _attribute_definitions(image, method(prefix + 'InternalCreate'))
                         for prefix in (BASE, BASIC, PROGRAMMABLE)}
    model_definitions = {owner: _attribute_definitions(image, method(MODEL + owner + '.InternalCreate'))
                         for owner in sorted({owner for _f, _s, owner, _p in FIELDS})}
    field_evidence = {}
    for field, slot, owner, profile in FIELDS:
        load_name, save_name, signed, cap_127 = PROFILES[profile]
        setter_name, getter_name = MODEL + owner + '.Set' + field, MODEL + owner + '.Get' + field
        setter = method(setter_name)
        getter = method(getter_name)
        definition = model_definitions[owner][field]
        model_slot = definition['slot']
        checks[field + '_plain_integer_model'] = (
            definition['class'] == 'CIS_TIntegerAttribute..TIntegerAttribute'
            and ('mov', f'eax, dword ptr [eax + {hex(model_slot)}]') in [(m, op) for _a, m, op, _n in setter]
            and not any(m in ('cmp', 'add', 'sub', 'imul', 'idiv', 'and') for _a, m, _op, _n in setter)
            and not any('.SetMin' in n or '.SetMax' in n for _a, _m, _op, n
                        in method(MODEL + owner + '.InternalCreate')))
        sites = []
        for prefix in ((BASIC, PROGRAMMABLE) if owner == 'TUIService' else (BASE,)):
            checks[field + '_' + prefix + '_pp_slot'] = agent_definitions[prefix][field]['slot'] == slot
            load, save = method(prefix + LOAD), method(prefix + SAVE)
            set_index, get_index = _call_index(load, setter_name), _call_index(save, getter_name)
            load_window = load[max(0, set_index - 16):set_index + 1]
            conversion_index = next(index for index in range(set_index - 10, set_index)
                                    if load[index][3] == BASE + load_name)
            incoming_window = load[max(0, conversion_index - 8):conversion_index]
            load_ops = [(m, op) for _a, m, op, _n in incoming_window]
            checks[field + '_' + prefix + '_load'] = (
                ('mov', f'eax, dword ptr [eax + {hex(slot)}]') in load_ops
                and any(n == BASE + load_name for _a, _m, _op, n in load_window)
                and (('movsx', 'edx, al') in load_ops) == signed
                and any(n == AGENT + 'TSignedIntCGateAttribute.AsShortint'
                        for _a, _m, _op, n in incoming_window) == signed)
            save_window = save[get_index:get_index + 34]
            save_slot_index = next(index for index, (_a, m, op, _n) in enumerate(save_window)
                                   if m == 'mov' and op == f'eax, dword ptr [eax + {hex(slot)}]')
            save_window = save_window[:save_slot_index + 4]
            checks[field + '_' + prefix + '_save'] = (
                any(n == BASE + save_name for _a, _m, _op, n in save_window)
                and any(n == AGENT + 'TSignedIntCGateAttribute.SetShortintValue'
                        for _a, _m, _op, n in save_window) == signed
                and any(m == 'cmp' and op.endswith(', 0x7f') for _a, m, op, _n in save_window) == cap_127)
            sites.append({'agent': prefix.rstrip('.'), 'load_conversion': hex(load[conversion_index][0]),
                          'model_setter': hex(load[set_index][0]), 'model_getter': hex(save[get_index][0]),
                          'save_pp_slot_reference': hex(save_window[save_slot_index][0])})
        field_evidence[field] = {'profile': profile, 'pp_attribute_offset': hex(slot),
                                 'model_owner': owner, 'model_attribute_offset': hex(model_slot), 'sites': sites}
        for name in (load_name, save_name):
            rows = method(BASE + name)
            ops = [(m, op) for _a, m, op, _n in rows]
            checks[name + '_global_preference'] = (
                ('mov', 'eax, dword ptr [0x13c3ac8]') in ops
                and ('cmp', 'byte ptr [eax + 0x20], 0') in ops)
    # Both PP subclasses and model integers dispatch to the uncast integer
    # setter. The low-byte write is performed only by SetShortintValue itself.
    for pointer in (0xf42b48, 0x128b220, 0x850574):
        vmt = walker.dword(pointer)
        checks[hex(pointer) + '_integer_vmt'] = (
            walker.dword(vmt + 0x7c) == image.by_name['CIS_TIntegerAttribute.TIntegerAttribute.SetValue']
            and walker.dword(vmt + 0xa4) == image.by_name['CIS_TIntegerAttribute.TIntegerAttribute.SetAsInteger'])
    setter = method(AGENT + 'TSignedIntCGateAttribute.SetShortintValue')
    checks['explicit_signed_byte_store'] = all(pair in [(m, op) for _a, m, op, _n in setter] for pair in (
        ('mov', 'byte ptr [ebp - 5], dl'), ('xor', 'edx, edx'), ('mov', 'dl, byte ptr [ebp - 5]')))
    method(AGENT + 'TSignedIntCGateAttribute.AsShortint')
    integer = method('CIS_TIntegerAttribute.TIntegerAttribute.SetAsInteger')
    checks['integer_bounds_disabled_when_equal'] = all(pair in [(m, op) for _a, m, op, _n in integer]
        for pair in (('cmp', 'eax, dword ptr [edx + 0x54]'), ('je', '0x8509c3')))
    method('CIS_TIntegerAttribute.TIntegerAttribute.SetValue')
    method('CIS_TIntegerAttribute.TIntegerAttribute.InternalCreate')
    # The measurement hooks only attach a zone change handler; they do not
    # clamp either temperature integer during the fresh model load.
    for name in ('HookEvents', 'UnHookEvents'):
        method(MODEL + 'TTemperatureMeasurementService.' + name)
    load = method(BASE + LOAD)
    checks['measurement_load_unhooks_before_temperature_setters'] = (
        _call_index(load, MODEL + 'TTemperatureMeasurementService.UnHookEvents')
        < _call_index(load, MODEL + 'TTemperatureMeasurementService.SetTemperatureOffset')
        < _call_index(load, MODEL + 'TTemperatureMeasurementService.SetTemperatureSendDifferential')
        < _call_index(load, MODEL + 'TTemperatureMeasurementService.HookEvents'))
    controlled = method(AGENT + 'GetControlledZones')
    checks['master_controlled_zones_uses_installed_zones'] = (
        any(n == MODEL + 'TCBusParameters.GetInstalledZones' for _a, _m, _op, n in controlled)
        and ('jne', '0x1294708') in [(m, op) for _a, m, op, _n in controlled]
        and image.pe.get_data(0x1294718 - image.base, 1) == b'\0')
    if failed := [name for name, ok in checks.items() if not ok]:
        raise ValueError('Source temperature mapping checks failed: ' + ', '.join(failed))
    vectors = original_vectors()
    if _sha(exe.read_bytes()) != EXE_SHA256 or _sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError('Original source changed during inspection')
    overflow = [{'profile': name, 'fahrenheit': row[0], 'raw': row[1], 'saved': row[4]}
                for name, profile in vectors['profiles'].items() for row in profile['rows']
                if not 0 <= row[4] <= 255]
    report = {
        'format': 'cbus-thermostat-settings-temperature-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed_this_run': False, 'physical_devices_accessed': False,
        'source_fixture_sha256': FIXTURE_SHA256,
        'production_conversion_oracle_used': False,
        'roundtrip_vector_sha256': _sha(_json(vectors)),
        'profile_count': len(PROFILES), 'field_count': len(FIELDS),
        'roundtrip_vector_count': sum(len(p['rows']) for p in vectors['profiles'].values()),
        'checks': dict(sorted(checks.items())), 'routines': dict(sorted(routines.items())),
        'fields': field_evidence, 'unsigned_save_values_outside_byte': overflow,
        'limits': [
            'This pins fresh scalar AfterLoad/BeforeSave composition, not the complete original form or '
            'retained UI event lifecycle. Caller must supply one unchanged global temperature preference.',
            'TemperatureUnits PP is a separate device UI setting and never selects these conversions.',
            'IntegerCGateAttribute and SignedIntCGateAttribute plain setters preserve integer overflow; '
            'only explicit SetShortintValue encodes low8. A one-byte PP editor must refuse unrepresentable values.',
            'The 4608 composed vectors reuse captured original arithmetic. No fresh original executable '
            'instructions or native project save were executed by this static verifier.',
        ],
    }
    return report, vectors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--vectors-output', type=Path)
    args = parser.parse_args()
    report, vectors = inspect(args.exe, args.map)
    if args.vectors_output:
        with args.vectors_output.open('xb') as stream:
            stream.write(_json(vectors))
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()

"""Source receipt for the three temperature report projections, without execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256
from csv_factory_registry_static import source_registry
from cbus_toolkit import project_documentation_temperature as model


def inspect(exe, map_file):
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    t = _Toolkit(raw, symbols)
    methods, checks = {}, {}

    def method(name):
        if name not in methods:
            methods[name] = t.method(name)
        return methods[name]

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in method(name)['instructions']

    def call(name, address, target):
        return has(name, address, 'call', hex(t.by_name[target]))

    def facts(name, entries):
        return all(has(name, *entry) for entry in entries)

    rows = [r for r in source_registry(exe, map_file, ())['registrations'] if r['unit_type'] in model.PROFILES]
    checks['factory'] = sorted((r['unit_type'], r['class'], r['agent'], r['firmware_min'], r['firmware_max']) for r in rows) == [
        ('SENTEMP', 'TSENTEMP', 'TSENTEMPCGateAgent', '1.00', '1.2.68'),
        ('SENTEMP4', 'TPC_RDTS', 'TCBusDigitalTemperatureSensorCGateAgent', '0', '9'),
        ('SENTEMPB', 'TSENTEMPPro', 'TSENTEMPProCGateAgent', '0', '9')]
    for cls, names in [('TSENTEMP', ['TSENTEMP', 'TCBUSUnit', 'TSENTEMP']),
                       ('TSENTEMPPro', ['TSENTEMPPro', 'TCBUSUnit', 'TSENTEMPPro']),
                       ('TCBusDigitalTemperatureSensor', ['TCBUSUnit', 'TCBUSUnit', 'TCBusDigitalTemperatureSensor'])]:
        checks[cls + ':dependency_slots'] = [t.slot(f'CIS_{cls}..{cls}', offset).rsplit('.', 2)[-2]
                                             for offset in (0x128, 0x12c, 0x130)] == names
    bodies = {name: f'CIS_T{cls}Documentor.T{cls}Documentor.DocumentHTML' for name, cls in (
        ('SENTEMP', 'SENTEMP'), ('SENTEMPB', 'SENTEMPPro'), ('SENTEMP4', 'DigitalTemperatureSensor'))}
    for kind, address in [('SENTEMP', 0xfcf1fc), ('SENTEMPB', 0xfd2ae5), ('SENTEMP4', 0x12ea58c)]:
        checks[kind + ':base_first'] = call(bodies[kind], address, 'CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML')
        checks[kind + ':temperature_preference'] = any(m == 'mov' and op == 'eax, dword ptr [0x13c3ac8]'
                                                      for _, m, op in method(bodies[kind])['instructions'])
    checks['degree_resources'] = [t.resource(t.dword(v)) for v in (0x13c3c88, 0x13c3c84, 0x13c2b2c, 0x13c2b28)] == ['°C', '°C', '°F', '°F']
    for cls, fields in [('TSENTEMP', ['ControlGroupAddress', 'EnableGroupAddress', 'IndicatorIndex', 'IndicatorFunction', 'TemperatureHigh', 'TemperatureLow', 'OffsetMode', 'OffsetGroupAddress', 'TemperatureOffset']),
                        ('TSENTEMPPro', ['BroadcastTriggerGroup', 'BroadcastTriggerLevel', 'BroadcastInterval', 'TemperatureChangeThreshold', 'ThermostatRegulationZones', 'GroupAddress', 'TemperatureGroup', 'EconomyGroup', 'ControlledGroup', 'ModeHeating', 'EconomyOffset', 'TemperatureOffset', 'TargetTemperature'])]:
        create = f'CIS_{cls}CGateAgent.{cls}CGateAgent.InternalCreate'
        literals = method(create)['literals']
        checks[cls + ':pp_names'] = literals == fields
        checks[cls + ':pp_offsets'] = [op for _, mn, op in method(create)['instructions'] if mn == 'mov' and op.startswith('dword ptr [edx +')] == [
            f'dword ptr [edx + {hex(0x100 + i * 4)}], eax' for i in range(len(fields))]
    sentemp = 'CIS_TSENTEMPCGateAgent.TSENTEMPCGateAgent.AfterLoadProgrammingInformation'
    checks['SENTEMP:ceil_average'] = call(sentemp, 0x1223039, 'Math.Ceil') and facts(sentemp, [
        (0x1223003, 'mov', 'eax, dword ptr [eax + 0x110]'), (0x1223016, 'mov', 'eax, dword ptr [eax + 0x114]'),
        (0x1223024, 'add', 'ebx, eax'), (0x122302c, 'fdiv', 'dword ptr [0x1223124]')]) and struct.unpack('<f', t.pe.get_data(0x1223124 - t.base, 4))[0] == 2
    checks['SENTEMP:margin_difference'] = has(sentemp, 0x1223071, 'sub', 'ebx, eax') and call(sentemp, 0x122307d, 'CIS_TSENTEMP.TSENTEMP.SetMarginTemperature')
    checks['SENTEMP:heating_zero'] = facts(sentemp, [(0x1223085, 'mov', 'eax, dword ptr [eax + 0x118]'), (0x1223095, 'sete', 'al')])
    checks['SENTEMP:economy_pp'] = facts(sentemp, [(0x12230aa, 'mov', 'eax, dword ptr [eax + 0x11c]'), (0x12230de, 'mov', 'eax, dword ptr [eax + 0x120]')])
    pro = 'CIS_TSENTEMPProCGateAgent.TSENTEMPProCGateAgent.AfterLoadProgrammingInformation'
    checks['Pro:modes'] = facts(pro, [(0x1224b60, 'cmp', 'eax, 0xac'), (0x1224b6f, 'mov', 'dl, 2'),
        (0x1224b8d, 'cmp', 'eax, 0xe4'), (0x1224b9c, 'mov', 'dl, 3'), (0x1224bba, 'cmp', 'eax, 0x19'), (0x1224bc7, 'mov', 'dl, 1')])
    checks['Pro:selector_address'] = call(pro, 0x1224c7f, 'CIS_TCommonCBus.TLevelManager.FindLevelByAddress')
    checks['Pro:interval_sentinel_default_clamp'] = facts(pro, [(0x1224ca4, 'cmp', 'eax, 0xff'),
        (0x1224cdf, 'mov', 'edx, 6'), (0x12254d1, 'cmp', 'dword ptr [ebp - 0x70], 3'), (0x12254e6, 'cmp', 'dword ptr [ebp - 0x74], 0x3c')])
    checks['Pro:threshold_sentinels_halving_clamp'] = facts(pro, [(0x1224d1c, 'add', 'eax, 0xffffff02'), (0x1224d21, 'sub', 'eax, 2'),
        (0x1224d5f, 'mov', 'edx, 6'), (0x1224d7c, 'sar', 'eax, 1'), (0x1225470, 'cmp', 'dword ptr [ebp - 0x60], 1'), (0x1225485, 'cmp', 'dword ptr [ebp - 0x64], 0x20')])
    checks['Pro:display_threshold_divisor'] = has(bodies['SENTEMPB'], 0xfd3051, 'fdiv', 'dword ptr [0xfd35c0]') and struct.unpack('<f', t.pe.get_data(0xfd35c0 - t.base, 4))[0] == 2
    checks['Pro:group_mapping'] = facts(pro, [(0x1224ea6, 'mov', 'eax, dword ptr [eax + 0x114]'), (0x1224ef3, 'mov', 'eax, dword ptr [eax + 0x11c]'),
        (0x1224f40, 'mov', 'eax, dword ptr [eax + 0x120]'), (0x12250ad, 'mov', 'eax, dword ptr [eax + 0x114]'), (0x12250ff, 'mov', 'eax, dword ptr [eax + 0x118]')])
    checks['Pro:target_array_indices'] = facts(pro, [(0x122522d, 'mov', 'eax, dword ptr [eax + 0x130]'),
        (0x1225256, 'xor', 'edx, edx'), (0x122529e, 'mov', 'edx, 1')])
    checks['Pro:target_economy_clamps'] = facts(pro, [(0x12252e5, 'cmp', 'dword ptr [ebp - 0x14], 0x14'),
        (0x12253c1, 'cmp', 'dword ptr [ebp - 0x40], 1'), (0x12253d6, 'cmp', 'dword ptr [ebp - 0x44], 0x32'),
        (0x1225411, 'cmp', 'dword ptr [ebp - 0x50], 0'), (0x1225424, 'cmp', 'dword ptr [ebp - 0x54], 0x31')])
    channel = 'CIS_TCBusDigitalTemperatureSensorCGateAgent.TCBusDigitalTemperatureSensorChannelParameters.'
    checks['Digital:pp_names'] = all(s in method(channel + 'Create')['literals'] for s in ('Channel%d', 'ChannelMode', 'ChannelName', 'BroadcastInterval', 'BroadcastThreshold', 'HVACCommunicationGroup', 'HVACZones'))
    load = channel + 'AfterLoadProgrammingInformation'
    checks['Digital:hvac_unused_mode'] = facts(load, [(0x12ecbd1, 'cmp', 'eax, 0xac'), (0x12ecc21, 'mov', 'dl, 2'), (0x12ecc30, 'xor', 'edx, edx'), (0x12ecc3f, 'mov', 'dl, 1')])
    checks['Digital:trim_and_empty_name'] = call(load, 0x12ecc8a, 'SysUtils.Trim') and 'Channel %d' in method(load)['literals']
    checks['Digital:interval_seconds_disabled_default'] = facts(load, [(0x12ecd7e, 'add', 'edx, edx'), (0x12ecd80, 'lea', 'edx, [edx + edx*4]'), (0x12ecd90, 'mov', 'edx, 0x3c')])
    checks['Digital:threshold_eighths_disabled_default'] = facts(load, [(0x12ecde1, 'fmul', 'dword ptr [0x12ecfa4]'), (0x12ecdfb, 'push', '0x3fe00000')]) and struct.unpack('<f', t.pe.get_data(0x12ecfa4 - t.base, 4))[0] == .125
    checks['Digital:four_channels'] = has('CIS_TCBusDigitalTemperatureSensor.TCBusDigitalTemperatureSensor.GetMaxChannels', 0x11c2929, 'mov', 'dword ptr [ebp - 8], 4')
    checks['Digital:absolute_fahrenheit_threshold'] = call(bodies['SENTEMP4'], 0x12ea86e, 'CIS_jcl.CelsiusToFahrenheit') and not any(m == 'fsub' for _, m, _ in method(bodies['SENTEMP4'])['instructions'])
    checks['Digital:malformed_final_table'] = '</table>' not in method(bodies['SENTEMP4'])['literals'] and facts(bodies['SENTEMP4'], [(0x12ea8e6, 'mov', 'edx, 0x12eaa44'), (0x12ea8f3, 'xor', 'eax, eax')]) and t.literal(0x12eaa44) == '</tr>'
    interval = 'CIS_TDocumentorCommon.DisplaySENTEMPProInterval'
    checks['interval_minutes_seconds'] = facts(interval, [(0xca6070, 'cmp', 'dword ptr [ebp - 4], 6'), (0xca6083, 'idiv', 'ecx'), (0xca60c9, 'add', 'eax, eax'), (0xca60cb, 'lea', 'eax, [eax + eax*4]')]) and method(interval)['literals'] == ['%dm', '%ds']
    checks['zones_labels'] = method('CIS_TDocumentorCommon.DisplayZones')['literals'] == ['Unswitched Zone', ', ', 'Zone 1', ', ', 'Zone 2', ', ', 'Zone 3', ', ', 'Zone 4']
    method('CIS_TThermostatCommon.IntegerToZones')
    checks['decimal_half_up'] = facts('SysUtils.FloatToDecimal', [(0x61cd96, 'cmp', 'byte ptr [ebx + edi + 3], 0x35'), (0x61cd9b, 'jb', '0x61cdc2'), (0x61cda5, 'inc', 'byte ptr [ebx + edi + 3]')])
    method('CIS_jcl.CelsiusToFahrenheit')
    method('SysUtils.FloatToText')
    for cls in ('TSENTEMP', 'TSENTEMPPro'):
        for dependency in ('Input', 'Other'):
            method(f'CIS_{cls}.{cls}.Describe{dependency}GroupDependencyAdvanced')
    checks['dependency_labels'] = [t.resource(v) for v in (0xfcf6d0, 0xfcf6d8, 0xfcf6e0, 0xfd3648, 0xfd3650, 0xfd3658, 0xfd3660, 0xfd3668)] == [
        'Control Group', 'Enable Group', 'Economy Group', 'Controlled Group', 'Enable Group', 'Economy Group', 'Communication Group', 'Temperature Group']
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError('Temperature source checks failed: ' + ', '.join(failed))
    return {'format': 'cbus-project-documentor-temperature-static-v1', 'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
            'original_executed': False, 'original_generated_page_comparison': 'not_obtained',
            'model_sha256': hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest(), 'factory': rows,
            'format_basis': model.TEMPERATURE_FORMAT_BASIS, 'checks': checks,
            'methods': {name: {'start': hex(m['start']), 'end': hex(m['end']), 'sha256': m['sha256']} for name, m in sorted(methods.items())},
            'limits': ['Only consumed complete saved PP fields; no original programming-load success/failure or prior mutable model state.',
                       'Existing displayed group/level records are required; native auto-creation is not projected.',
                       'Explicit Celsius or Fahrenheit with period decimal; no running preferences or Windows locale observed.',
                       'Original malformed Digital table and disabled broadcast default values are retained.',
                       'Source/method evidence is not original complete generated-page acceptance.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.exe, args.map)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'checks': len(report['checks']), 'methods': len(report['methods'])}))

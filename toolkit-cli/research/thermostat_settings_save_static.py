"""Pin the recovered thermostat scalar AfterLoad/BeforeSave normalization.

Reads the exact Toolkit EXE/MAP without executing vendor instructions. The
receipt records source addresses, hashes, explicit arithmetic/call checks and
independent scalar examples, never proprietary bytes or site data. This is a
bounded scalar lifecycle receipt, not complete original form acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thermostat_post_load_static import _Walker  # noqa: E402
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cbus_toolkit.thermostat_post_load import form_save_fans, form_save_scalars  # noqa: E402

AGENT = 'CIS_TCBusThermostatCGateAgent.'
BASE = AGENT + 'TCBusThermostatCGateAgent.'
BASIC = AGENT + 'TCBusBasicThermostatCGateAgent.'
PROGRAMMABLE = AGENT + 'TCBusProgrammableThermostatCGateAgent.'
LOAD = 'AfterLoadProgrammingInformation'
SAVE = 'BeforeSaveProgrammingInformation'
PINS = {
    BASE + LOAD: '2334495515fab9b4f1942a3c1a1caf58003877da1e82b3d00c91a907719b69be',
    BASE + SAVE: '8c12c86a1e8eeb8da70d889b9a6dcc1f9ecf4c67b80a0259bb70759b440fad82',
    BASIC + LOAD: 'e9e5b47cc0d3ccda66271e5d888ffbffc0e213c94defa99a1718a813a7cea96e',
    BASIC + SAVE: 'a5faac0e1ac58855344ea8bbff3f3a43846537028afbc6a0a747cb1c400d4d27',
    PROGRAMMABLE + LOAD: '8e869e22ac8e8d586f6941d291ab8ccccd5adcb2ba0aa7d035971f9fad2d1fc5',
    PROGRAMMABLE + SAVE: 'efb5759d3d169d32cd32d01b74981715a6398f9fa701bfcb9ead9540c692122d',
    'CIS_CBus.LevelToPercent': '3a160d69301b27c4f68d9b1840afb438693f7ec862cf84175eabf77ef4dc445a',
    'CIS_CBus.PercentToLevel': '0559d6a4df3728a3ffe7a30d05fcfd41db35239df09d1aeef951295c694d0795',
    'CIS_TThermostat.TThermostat.HeatingFanControlEnabled':
        '11a56b7dbea131e97b4c5234ec67c744f2ec5a49ddffc0b4e85133f1bb75f38a',
    'CIS_TThermostat.TThermostat.CoolingFanControlEnabled':
        '89f4815316889fb531e9a15559fab027333e6ce505859334b58ade6edc269c62',
    BASE + 'IntVirtualRestrictedPlantTypeToUnitPlantType':
        '9a742c38d2a7e04b84a44fab7bcf09d0512916295af28a465b204c0306a5abf8',
    'CIS_TThermostatCommon.IntegerToZones':
        'a2978f441b20a2a672a2dca0315e068fc3f8e9b80343df3be5570703b5026b03',
    'CIS_TThermostatCommon.ZonesToInteger':
        'aed1d5cc9f6014cc8c10b0daf016ec38642a5fe7e68a2da4169f7c93eaca05d4',
}
BRIGHTNESS = ('DisplayBacklightIdleBrightness', 'DisplayBacklightActiveBrightness',
              'KeyBacklightIdleBrightness', 'KeyBacklightActiveBrightness')
# Hand-calculated from the two integer divisions, independent of production.
BRIGHTNESS_VECTORS = ((0, 0), (1, 2), (2, 2), (3, 2), (4, 5), (5, 5), (6, 7),
                      (63, 63), (64, 63), (127, 127), (128, 127), (129, 130),
                      (252, 252), (253, 255), (254, 255), (255, 255))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _sequence(rows, expected):
    actual = [(m, op) for _a, m, op, _note in rows]
    return any(actual[i:i + len(expected)] == list(expected)
               for i in range(len(actual) - len(expected) + 1))


def _region(rows, start, end):
    return [row for row in rows if start <= row[0] < end]


def _calls(rows, suffix):
    return [a for a, m, _op, note in rows if m == 'call' and note.endswith(suffix)]


def _fan_values(modes):
    values = {'ControlledZones': 1, 'InternalPlantModes': modes, 'VentPlantType': 0}
    for side in ('Heating', 'Cooling'):
        values.update({side + 'PlantFan' + field: value for field, value in (
            ('SpeedControlEnable', 1), ('Speeds', 0), ('DefaultSpeed', 1),
            ('OnDelay', 0), ('OffDelay', 0), ('Enable', 1))})
    return values


def inspect(exe: Path, map_path: Path):
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Image(exe_raw, map_raw)
    walker = _Walker(image)
    methods, routines, checks = {}, {}, {}
    for name, digest in PINS.items():
        rows, _tables, actual = walker.listing(name)
        if actual != digest:
            raise ValueError('Pinned routine changed: ' + name)
        methods[name] = rows
        routines[name] = {'address': hex(image.by_name[name]), 'sha256': actual}
    checks['routine_hashes'] = True
    checks['level_to_percent_integer_arithmetic'] = _sequence(methods['CIS_CBus.LevelToPercent'], (
        ('add', 'eax, 2'), ('imul', 'eax, eax, 0x64'), ('mov', 'ecx, 0xff'), ('cdq', ''),
        ('idiv', 'ecx')))
    checks['percent_to_level_integer_arithmetic'] = _sequence(methods['CIS_CBus.PercentToLevel'], (
        ('mov', 'edx, eax'), ('shl', 'eax, 8'), ('sub', 'eax, edx'), ('mov', 'ecx, 0x64'),
        ('cdq', ''), ('idiv', 'ecx')))
    for family, prefix in (('basic', BASIC), ('programmable', PROGRAMMABLE)):
        load, save = methods[prefix + LOAD], methods[prefix + SAVE]
        checks[family + '_inherits_common_lifecycle'] = (
            len(_calls(load, 'TCBusThermostatCGateAgent.' + LOAD)) == 1
            and len(_calls(save, 'TCBusThermostatCGateAgent.' + SAVE)) == 1)
        checks[family + '_brightness_roundtrip'] = (
            len(_calls(load, 'CIS_CBus.LevelToPercent')) == 4
            and len(_calls(save, 'CIS_CBus.PercentToLevel')) == 4
            and all(len(_calls(load, '.Set' + field)) == 1
                    and len(_calls(save, '.Get' + field)) == 1 for field in BRIGHTNESS))
        checks[family + '_beep_boolean'] = (
            len(_calls(load, '.SetBeepEnable')) == 1 and len(_calls(save, '.GetBeepEnable')) == 1
            and any(m == 'setg' for _a, m, _op, _n in _region(
                load, _calls(load, '.SetBeepEnable')[0] - 32, _calls(load, '.SetBeepEnable')[0])))
    # >1 clamps directly rewrite the listed PP attribute before loading its UI field.
    clamp_sites = (
        ('basic_temperature_units', BASIC, 0x1297761, 0x1297792, 0x270, 0),
        ('programmable_temperature_units', PROGRAMMABLE, 0x12994fa, 0x129952b, 0x270, 0),
        ('time_units', PROGRAMMABLE, 0x1299758, 0x1299789, 0x2a4, 0),
        ('evap_program', PROGRAMMABLE, 0x1299789, 0x12997ba, 0x2a8, 0),
        ('nonevap_program', PROGRAMMABLE, 0x12997ba, 0x12997ee, 0x2ac, 1),
        ('basic_timer', BASIC, 0x1297b8b, 0x1297bbf, 0x2a4, 1),
    )
    for name, prefix, start, end, slot, default in clamp_sites:
        rows = _region(methods[prefix + LOAD], start, end)
        instructions = [(m, op) for _a, m, op, _n in rows]
        checks[name + '_clamp'] = (
            instructions.count(('mov', f'eax, dword ptr [eax + {hex(slot)}]')) == 2
            and ('dec', 'eax') in instructions and ('jle', hex(end)) in instructions
            and (('xor', 'edx, edx') if default == 0 else ('mov', 'edx, 1')) in instructions
            and ('call', 'dword ptr [ecx + 0x7c]') in instructions)
    rows = _region(methods[PROGRAMMABLE + LOAD], 0x1299ac1, 0x1299b15)
    checks['send_interval_above_six_becomes_two'] = (
        _sequence(rows, (('cmp', 'eax, 6'), ('jle', '0x1299aed')))
        and ('mov', 'dl, 2') in [(m, op) for _a, m, op, _n in rows]
        and len(_calls(rows, '.SetSendInterval')) == 1
        and len(_calls(methods[PROGRAMMABLE + SAVE], '.GetSendInterval')) == 1)
    common_load, common_save = methods[BASE + LOAD], methods[BASE + SAVE]
    divisor = struct.unpack('<f', image.pe.get_data(0x128f99c - image.base, 4))[0]
    checks['fan_delay_load_divide_six_round'] = divisor == 6 and sum(
        m == 'fdiv' and op == 'dword ptr [0x128f99c]' for _a, m, op, _n in common_load) == 4
    checks['fan_delay_save_times_six'] = all(_sequence(
        _region(common_save, _calls(common_save, '.Get' + side + 'PlantFan' + delay)[0],
                _calls(common_save, '.Get' + side + 'PlantFan' + delay)[0] + 16),
        (('mov', 'edx, eax'), ('add', 'edx, edx'), ('lea', 'edx, [edx + edx*2]')))
        for side in ('Heating', 'Cooling') for delay in ('OnDelay', 'OffDelay'))
    rows = _region(common_save, 0x129513b, 0x1295221)
    checks['slave_internal_plant_and_zones_zero'] = (
        len(_calls(rows, '.GetZoneManagerMasterSlave')) == 1
        and ('jne', '0x12951db') in [(m, op) for _a, m, op, _n in rows]
        and len(_calls(rows, '.IntVirtualRestrictedPlantTypeToUnitPlantType')) == 1
        and sum(m == 'xor' and op == 'edx, edx' for _a, m, op, _n in _region(
            rows, 0x12951db, 0x1295221)) == 2)
    checks['relay_drive_always_zero'] = _sequence(
        _region(common_save, 0x1296564, 0x1296587),
        (('xor', 'edx, edx'), ('mov', 'cl, 1'), ('call', '0x62f294')))
    checks['variable_fan_coil_boolean'] = (
        len(_calls(common_load, '.SetVariableFanCoilEnable')) == 1
        and _sequence(_region(common_load, 0x128f7ae, 0x128f7d8),
                      (('test', 'eax, eax'), ('setg', 'al')))
        and len(_calls(common_save, '.GetVariableFanCoilEnable')) == 1)
    checks['brightness_literal_vectors'] = all(
        ((raw + 2) * 100 // 255) * 255 // 100 == expected for raw, expected in BRIGHTNESS_VECTORS)
    scalar_input = {'BeepEnable': 3, 'VariableFanCoilEnable': 2, 'TemperatureUnits': 9,
                    'ControlledZones': 1, 'InstalledZones': 1, 'InternalPlantType': 11, 'TimerEnable': 3}
    checks['scalar_model_literal_vectors'] = all(
        form_save_scalars(scalar_input | dict.fromkeys(BRIGHTNESS, raw), 'basic')
        == dict.fromkeys(BRIGHTNESS, expected) | {'BeepEnable': 1, 'VariableFanCoilEnable': 1,
            'TemperatureUnits': 0, 'EnableHVACRelayDrive': 0, 'InternalPlantType': 8,
            'ControlledZones': 1, 'TimerEnable': 1}
        for raw, expected in BRIGHTNESS_VECTORS)
    checks['virtual_plant_eleven_saves_as_eight'] = _sequence(
        methods[BASE + 'IntVirtualRestrictedPlantTypeToUnitPlantType'],
        (('cmp', 'byte ptr [ebp - 8], 0xb'), ('jne', '0x128df8b'),
         ('mov', 'dword ptr [ebp - 0xc], 8')))
    fan_vectors = []
    for modes, first, second in ((0x14, (0, 1), (1, 1)), (0x12, (1, 0), (1, 1))):
        values = _fan_values(modes)
        saved = form_save_fans(values)
        resaved = form_save_fans(values | saved)
        fields = ('HeatingPlantFanSpeeds', 'CoolingPlantFanSpeeds')
        checks['fan_single_pass_' + hex(modes)] = (
            tuple(saved[n] for n in fields) == first and tuple(resaved[n] for n in fields) == second)
        fan_vectors.append({'input': values, 'first_save_expected': dict(zip(fields, first)),
                            'second_save_expected': dict(zip(fields, second))})
    if failed := sorted(name for name, ok in checks.items() if not ok):
        raise ValueError('Source normalization checks failed: ' + ', '.join(failed))
    if _sha(exe.read_bytes()) != EXE_SHA256 or _sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError('Original input changed during inspection')
    return {
        'format': 'cbus-thermostat-settings-save-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'physical_devices_accessed': False,
        'model_module_sha256': _sha((ROOT / 'src/cbus_toolkit/thermostat_post_load.py').read_bytes()),
        'checks': dict(sorted(checks.items())), 'routines': routines,
        'brightness_formula_for_bytes': '(((raw + 2) * 100) // 255 * 255) // 100',
        'brightness_parameters': list(BRIGHTNESS),
        'brightness_vectors': [{'raw': raw, 'saved': saved} for raw, saved in BRIGHTNESS_VECTORS],
        'fan_single_pass_vectors': fan_vectors,
        'rules': {
            'both_families': {'TemperatureUnits_above_1': 0, 'BeepEnable': 'int(raw > 0)',
                              'VariableFanCoilEnable': 'int(raw > 0)', 'EnableHVACRelayDrive': 0,
                              'master_InternalPlantType_11': 8,
                              'slave_InternalPlantType': 0, 'slave_InternalPlantZones': 0},
            'programmable': {'TimeUnits_above_1': 0, 'EvapProgramEnabled_above_1': 0,
                             'NonEvapProgramEnabled_above_1': 1, 'SendInterval_above_6': 2},
            'basic': {'TimerEnable': 'int(raw > 0)'},
        },
        'limits': [
            'Static source evidence and independent scalar vectors; the original object model/form was not run.',
            'Fan save is deliberately one pass: copying a zero source speed can require another later form save.',
            'TemperatureOffset/TemperatureSendDifferential and other temperature fields consume the global '
            'Toolkit TemperatureUnit preference, not the thermostat TemperatureUnits PP setting.',
            'No complete event-driven cross-control lifecycle, project-group creation, remote schedule, '
            'guard or remaining non-scalar normalization is established by this receipt.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
